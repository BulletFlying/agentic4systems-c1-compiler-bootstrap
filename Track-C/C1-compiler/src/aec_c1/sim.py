"""Small Track-B semantic simulator used by C1 compiler tests."""

from __future__ import annotations

from dataclasses import dataclass, field
import struct

from .isa import AECInstruction, TRACK_B_V1


MASK32 = 0xFFFFFFFF


class SimulationError(RuntimeError):
    """Raised when generated AEC code violates the simulated Track-B subset."""


@dataclass(frozen=True)
class MemoryAccess:
    op: str
    space: str
    block: int
    thread: int
    global_thread: int
    address: int
    size: int


@dataclass(frozen=True)
class BranchTrace:
    pc: int
    target: int
    predicate: int
    block: int
    warp_start: int
    lane_count: int
    decisions: tuple[bool, ...]
    uniform: bool
    taken: bool


@dataclass
class LaneState:
    block: int
    thread: int
    block_dim: tuple[int, int, int]
    grid_dim: tuple[int, int, int]
    warp_size: int
    registers: list[int] = field(default_factory=lambda: [0] * 256)
    predicates: list[bool] = field(default_factory=lambda: [False] * 8)

    @property
    def block_x(self) -> int:
        return self.block % self.grid_dim[0]

    @property
    def block_y(self) -> int:
        return (self.block // self.grid_dim[0]) % self.grid_dim[1]

    @property
    def block_z(self) -> int:
        return self.block // (self.grid_dim[0] * self.grid_dim[1])

    @property
    def thread_x(self) -> int:
        return self.thread % self.block_dim[0]

    @property
    def thread_y(self) -> int:
        return (self.thread // self.block_dim[0]) % self.block_dim[1]

    @property
    def thread_z(self) -> int:
        return self.thread // (self.block_dim[0] * self.block_dim[1])

    @property
    def total_threads(self) -> int:
        return self.block_dim[0] * self.block_dim[1] * self.block_dim[2]

    @property
    def total_blocks(self) -> int:
        return self.grid_dim[0] * self.grid_dim[1] * self.grid_dim[2]

    @property
    def global_thread(self) -> int:
        return self.block * self.total_threads + self.thread


@dataclass
class SimulationResult:
    gmem: bytearray
    accesses: list[MemoryAccess]
    branch_trace: list[BranchTrace]
    dynamic_instruction_count: int
    brx_execution_count: int
    non_uniform_branch_failures: int


class TrackBSimulator:
    def __init__(
        self,
        instructions: list[AECInstruction],
        pmem: bytes | bytearray,
        gmem: bytes | bytearray,
        *,
        block_dim: tuple[int, int, int] | int,
        grid_dim: tuple[int, int, int] | int,
        warp_size: int = 32,
        max_steps: int = 10000,
    ) -> None:
        self.instructions = instructions
        self.pmem = bytearray(pmem)
        self.gmem = bytearray(gmem)
        if isinstance(block_dim, int):
            self.block_dim = (block_dim, 1, 1)
        else:
            self.block_dim = block_dim
        if isinstance(grid_dim, int):
            self.grid_dim = (grid_dim, 1, 1)
        else:
            self.grid_dim = grid_dim
        self.warp_size = warp_size
        self.max_steps = max_steps
        self.accesses: list[MemoryAccess] = []
        self.branch_trace: list[BranchTrace] = []
        self.dynamic_instruction_count = 0
        self.brx_execution_count = 0
        self.non_uniform_branch_failures = 0

    @property
    def total_blocks(self) -> int:
        return self.grid_dim[0] * self.grid_dim[1] * self.grid_dim[2]

    @property
    def total_threads_per_block(self) -> int:
        return self.block_dim[0] * self.block_dim[1] * self.block_dim[2]

    def run(self) -> SimulationResult:
        for block in range(self.total_blocks):
            for warp_start in range(0, self.total_threads_per_block, self.warp_size):
                lane_count = min(self.warp_size, self.total_threads_per_block - warp_start)
                lanes = [
                    LaneState(
                        block=block,
                        thread=warp_start + lane,
                        block_dim=self.block_dim,
                        grid_dim=self.grid_dim,
                        warp_size=self.warp_size,
                    )
                    for lane in range(lane_count)
                ]
                self._run_warp(lanes)
        return SimulationResult(
            gmem=self.gmem,
            accesses=self.accesses,
            branch_trace=self.branch_trace,
            dynamic_instruction_count=self.dynamic_instruction_count,
            brx_execution_count=self.brx_execution_count,
            non_uniform_branch_failures=self.non_uniform_branch_failures,
        )

    def _run_warp(self, lanes: list[LaneState]) -> None:
        pc = 0
        steps = 0
        while True:
            if not 0 <= pc < len(self.instructions):
                raise SimulationError(f"PC out of range: {pc}")
            if steps >= self.max_steps:
                raise SimulationError("simulation step limit exceeded")
            steps += 1
            self.dynamic_instruction_count += 1

            inst = self.instructions[pc]
            opcode = inst.opcode.upper()
            if opcode == "HALT":
                if inst.predicate is not None:
                    raise SimulationError("HALT cannot use a generic predicate guard")
                return
            if opcode == "BR":
                if inst.predicate is not None:
                    raise SimulationError("BR cannot use a generic predicate guard")
                pc = inst.imm
                continue
            if opcode == "BRX":
                pc = self._branchx_next_pc(inst, lanes, pc)
                continue

            for lane in lanes:
                if self._guard_passes(inst, lane):
                    self._execute_lane(inst, lane)
            pc += 1

    def _branchx_next_pc(self, inst: AECInstruction, lanes: list[LaneState], pc: int) -> int:
        if inst.predicate is None:
            raise SimulationError("BRX requires a predicate")
        raw_decisions = [lane.predicates[inst.predicate] for lane in lanes]
        decisions = [not d if inst.predicate_negated else d for d in raw_decisions]
        uniform = all(decisions) or not any(decisions)
        taken = all(decisions)
        self.brx_execution_count += 1
        self.branch_trace.append(
            BranchTrace(
                pc=pc,
                target=inst.imm,
                predicate=inst.predicate,
                block=lanes[0].block,
                warp_start=lanes[0].thread,
                lane_count=len(lanes),
                decisions=tuple(decisions),
                uniform=uniform,
                taken=taken,
            )
        )
        if not uniform:
            self.non_uniform_branch_failures += 1
            raise SimulationError(f"non-uniform BRX at PC {pc}")
        return inst.imm if taken else pc + 1

    def _guard_passes(self, inst: AECInstruction, lane: LaneState) -> bool:
        if inst.predicate is None:
            return True
        value = lane.predicates[inst.predicate]
        return not value if inst.predicate_negated else value

    def _execute_lane(self, inst: AECInstruction, lane: LaneState) -> None:
        opcode = inst.opcode.upper()
        if opcode == "LOADI":
            lane.registers[inst.dest] = inst.imm & MASK32
        elif opcode == "LOADI64":
            if inst.dest >= 255:
                raise SimulationError(f"LOADI64 dest {inst.dest} too high for register pair")
            lane.registers[inst.dest] = inst.imm & MASK32
            lane.registers[inst.dest + 1] = (inst.imm >> 32) & MASK32
        elif opcode == "CPY":
            if inst.dtype in {"b64", "f64"} and (inst.dest >= 255 or inst.src1 >= 255):
                raise SimulationError(f"CPY.{inst.dtype} dest {inst.dest} or src1 {inst.src1} too high for register pair")
            lane.registers[inst.dest] = self._copy_value(inst, lane)
            if inst.dtype in {"b64", "f64"}:
                lane.registers[inst.dest + 1] = lane.registers[inst.src1 + 1]
        elif opcode == "LD":
            self._execute_load(inst, lane)
        elif opcode == "ST":
            self._execute_store(inst, lane)
        elif opcode == "ADD":
            lane.registers[inst.dest] = self._binary_result(inst.dtype, "+", lane.registers[inst.src1], lane.registers[inst.src2])
        elif opcode == "SUB":
            lane.registers[inst.dest] = self._binary_result(inst.dtype, "-", lane.registers[inst.src1], lane.registers[inst.src2])
        elif opcode == "MUL":
            lane.registers[inst.dest] = self._binary_result(inst.dtype, "*", lane.registers[inst.src1], lane.registers[inst.src2])
        elif opcode == "MAD":
            lane.registers[inst.dest] = self._mad_result(
                inst.dtype,
                lane.registers[inst.src1],
                lane.registers[inst.src2],
                lane.registers[inst.src3],
            )
        elif opcode == "FMA":
            lane.registers[inst.dest] = self._fma_result(
                inst.dtype,
                lane.registers[inst.src1],
                lane.registers[inst.src2],
                lane.registers[inst.src3],
            )
        elif opcode == "AND":
            lane.registers[inst.dest] = (lane.registers[inst.src1] & lane.registers[inst.src2]) & MASK32
        elif opcode == "OR":
            lane.registers[inst.dest] = (lane.registers[inst.src1] | lane.registers[inst.src2]) & MASK32
        elif opcode == "XOR":
            lane.registers[inst.dest] = (lane.registers[inst.src1] ^ lane.registers[inst.src2]) & MASK32
        elif opcode == "SHL":
            lane.registers[inst.dest] = (lane.registers[inst.src1] << (lane.registers[inst.src2] & 31)) & MASK32
        elif opcode == "SHR":
            lane.registers[inst.dest] = (lane.registers[inst.src1] >> (lane.registers[inst.src2] & 31)) & MASK32
        elif opcode == "CMPP":
            lane.predicates[inst.dest] = self._compare(inst.compare, inst.dtype, lane.registers[inst.src1], lane.registers[inst.src2])
        else:
            raise SimulationError(f"unsupported simulated opcode: {inst.opcode}")

    def _execute_load(self, inst: AECInstruction, lane: LaneState) -> None:
        space = self._require_space(inst)
        address = lane.registers[inst.src1] & MASK32
        size = _type_size(inst.dtype)
        blob = self._read(space, address, size)
        if inst.dtype == "b64":
            lane.registers[inst.dest] = int.from_bytes(blob[:4], "little")
            lane.registers[inst.dest + 1] = int.from_bytes(blob[4:8], "little")
        else:
            lane.registers[inst.dest] = int.from_bytes(blob, "little")
        self._record_access("LD", space, lane, address, size)

    def _execute_store(self, inst: AECInstruction, lane: LaneState) -> None:
        space = self._require_space(inst)
        if space == "pmem":
            raise SimulationError("store to pmem is illegal")
        address = lane.registers[inst.src1] & MASK32
        size = _type_size(inst.dtype)
        value = lane.registers[inst.src2] & MASK32
        self._write(space, address, value.to_bytes(size, "little"))
        self._record_access("ST", space, lane, address, size)

    def _copy_value(self, inst: AECInstruction, lane: LaneState) -> int:
        if inst.src1 >= 0x0100:
            return self._special_value(inst.src1, lane)
        return lane.registers[inst.src1] & MASK32

    def _special_value(self, selector: int, lane: LaneState) -> int:
        if selector == TRACK_B_V1.special_registers["%tid.x"]:
            return lane.thread_x
        if selector == TRACK_B_V1.special_registers["%tid.y"]:
            return lane.thread_y
        if selector == TRACK_B_V1.special_registers["%tid.z"]:
            return lane.thread_z
        if selector == TRACK_B_V1.special_registers["%ntid.x"]:
            return lane.block_dim[0]
        if selector == TRACK_B_V1.special_registers["%ntid.y"]:
            return lane.block_dim[1]
        if selector == TRACK_B_V1.special_registers["%ntid.z"]:
            return lane.block_dim[2]
        if selector == TRACK_B_V1.special_registers["%ctaid.x"]:
            return lane.block_x
        if selector == TRACK_B_V1.special_registers["%ctaid.y"]:
            return lane.block_y
        if selector == TRACK_B_V1.special_registers["%ctaid.z"]:
            return lane.block_z
        if selector == TRACK_B_V1.special_registers["%nctaid.x"]:
            return lane.grid_dim[0]
        if selector == TRACK_B_V1.special_registers["%nctaid.y"]:
            return lane.grid_dim[1]
        if selector == TRACK_B_V1.special_registers["%nctaid.z"]:
            return lane.grid_dim[2]
        if selector == TRACK_B_V1.special_registers["%laneid"]:
            return lane.thread_x % lane.warp_size
        if selector == TRACK_B_V1.special_registers["%warpid"]:
            return lane.thread_x // lane.warp_size
        raise SimulationError(f"unsupported special register selector: 0x{selector:04x}")

    def _binary_result(self, dtype: str, op: str, lhs_bits: int, rhs_bits: int) -> int:
        if dtype == "f32":
            lhs = bits_to_f32(lhs_bits)
            rhs = bits_to_f32(rhs_bits)
            if op == "+":
                return f32_to_bits(lhs + rhs)
            if op == "-":
                return f32_to_bits(lhs - rhs)
            if op == "*":
                return f32_to_bits(lhs * rhs)
        if op == "+":
            return (lhs_bits + rhs_bits) & MASK32
        if op == "-":
            return (lhs_bits - rhs_bits) & MASK32
        if op == "*":
            return (lhs_bits * rhs_bits) & MASK32
        raise SimulationError(f"unsupported binary operation: {op}")

    def _mad_result(self, dtype: str, lhs_bits: int, rhs_bits: int, add_bits: int) -> int:
        if dtype == "f32":
            product = bits_to_f32(f32_to_bits(bits_to_f32(lhs_bits) * bits_to_f32(rhs_bits)))
            return f32_to_bits(product + bits_to_f32(add_bits))
        return ((lhs_bits * rhs_bits) + add_bits) & MASK32

    def _fma_result(self, dtype: str, lhs_bits: int, rhs_bits: int, add_bits: int) -> int:
        if dtype == "f32":
            return f32_to_bits(bits_to_f32(lhs_bits) * bits_to_f32(rhs_bits) + bits_to_f32(add_bits))
        return ((lhs_bits * rhs_bits) + add_bits) & MASK32

    def _compare(self, compare: str | None, dtype: str, lhs_bits: int, rhs_bits: int) -> bool:
        if compare is None:
            raise SimulationError("CMPP requires a compare operation")
        if dtype == "f32":
            lhs: int | float = bits_to_f32(lhs_bits)
            rhs: int | float = bits_to_f32(rhs_bits)
        else:
            lhs = lhs_bits & MASK32
            rhs = rhs_bits & MASK32
        if compare == "eq":
            return lhs == rhs
        if compare == "ne":
            return lhs != rhs
        if compare == "lt":
            return lhs < rhs
        if compare == "le":
            return lhs <= rhs
        if compare == "gt":
            return lhs > rhs
        if compare == "ge":
            return lhs >= rhs
        raise SimulationError(f"unsupported compare operation: {compare}")

    def _require_space(self, inst: AECInstruction) -> str:
        if inst.memory_space is None:
            raise SimulationError(f"{inst.opcode} requires a memory space")
        return inst.memory_space

    def _read(self, space: str, address: int, size: int) -> bytes:
        memory = self._memory(space)
        if address + size > len(memory):
            raise SimulationError(f"{space} read out of range: address={address} size={size}")
        return bytes(memory[address : address + size])

    def _write(self, space: str, address: int, data: bytes) -> None:
        memory = self._memory(space)
        if address + len(data) > len(memory):
            raise SimulationError(f"{space} write out of range: address={address} size={len(data)}")
        memory[address : address + len(data)] = data

    def _memory(self, space: str) -> bytearray:
        if space == "gmem":
            return self.gmem
        if space == "pmem":
            return self.pmem
        raise SimulationError(f"unsupported memory space: {space}")

    def _record_access(self, op: str, space: str, lane: LaneState, address: int, size: int) -> None:
        if space != "gmem":
            return
        self.accesses.append(
            MemoryAccess(
                op=op,
                space=space,
                block=lane.block,
                thread=lane.thread,
                global_thread=lane.global_thread,
                address=address,
                size=size,
            )
        )


def f32_to_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def bits_to_f32(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & MASK32))[0]


def _type_size(dtype: str) -> int:
    if dtype == "b64":
        return 8
    if dtype in {"b32", "u32", "s32", "f32"}:
        return 4
    raise SimulationError(f"unsupported simulated type: {dtype}")
