"""AEC ISA profiles, encoder, and small disassembler helpers.

The default profile follows Track-B Appendix A.  A C2 profile is kept
separate because C2 renumbers LOADI/CPY/CVT* and adds tensor opcodes.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable


class EncodeError(ValueError):
    """Raised when an instruction cannot be encoded in the selected profile."""


@dataclass(frozen=True)
class ISAProfile:
    name: str
    opcodes: dict[str, int]
    types: dict[str, int]
    memory_spaces: dict[str, int]
    compare_ops: dict[str, int]
    special_registers: dict[str, int]
    supports_tensor: bool = False


TRACK_B_V1 = ISAProfile(
    name="track_b_v1",
    opcodes={
        "ADD": 0x0001,
        "SUB": 0x0002,
        "MUL": 0x0003,
        "MAD": 0x0004,
        "FMA": 0x0005,
        "DIV": 0x0006,
        "NEG": 0x0007,
        "ABS": 0x0008,
        "MIN": 0x0009,
        "MAX": 0x000A,
        "AND": 0x0010,
        "OR": 0x0011,
        "XOR": 0x0012,
        "NOT": 0x0013,
        "SHL": 0x0014,
        "SHR": 0x0015,
        "BFX": 0x0016,
        "BINS": 0x0017,
        "POPC": 0x0018,
        "FLO": 0x0019,
        "CMP": 0x0020,
        "CMPP": 0x0021,
        "SEL": 0x0022,
        "PICK": 0x0023,
        "LD": 0x0030,
        "ST": 0x0031,
        "LDC": 0x0032,
        "ATOM": 0x0033,
        "BR": 0x0040,
        "BRX": 0x0041,
        "CALL": 0x0043,
        "RET": 0x0044,
        "HALT": 0x0045,
        "SYNC.CT": 0x0047,
        "MBAR": 0x0049,
        "CVTFF": 0x0050,
        "CVTFI": 0x0051,
        "CVTIF": 0x0052,
        "CVTII": 0x0053,
        "CPY": 0x0054,
        "LOADI": 0x0055,
        "LOADI64": 0x0056,
        "SHUF": 0x0057,
        "VOTE": 0x0058,
        "MTCH": 0x0059,
        "RCP": 0x0070,
        "RSQ": 0x0071,
        "SIN": 0x0072,
        "COS": 0x0073,
        "EXP": 0x0074,
        "LOG": 0x0075,
        "SQRT": 0x0076,
        "RDTSC": 0x0080,
    },
    types={
        "b32": 0x0,
        "b64": 0x1,
        "u32": 0x2,
        "s32": 0x3,
        "u8": 0x4,
        "s8": 0x5,
        "f32": 0x8,
        "f64": 0x9,
        "f16": 0xA,
        "bf16": 0xB,
        "none": 0xF,
    },
    memory_spaces={"gmem": 0, "smem": 1, "cmem": 2, "lmem": 3, "pmem": 4},
    compare_ops={"eq": 0, "ne": 1, "lt": 2, "le": 3, "gt": 4, "ge": 5},
    special_registers={
        "%tid": 0x0100,
        "%tid.x": 0x0100,
        "%ntid": 0x0101,
        "%ntid.x": 0x0101,
        "%ctaid": 0x0102,
        "%ctaid.x": 0x0102,
        "%nctaid": 0x0103,
        "%nctaid.x": 0x0103,
        "%laneid": 0x0104,
        "%warpid": 0x0105,
        "%tid.y": 0x0110,
        "%ntid.y": 0x0111,
        "%ctaid.y": 0x0112,
        "%nctaid.y": 0x0113,
        "%tid.z": 0x0120,
        "%ntid.z": 0x0121,
        "%ctaid.z": 0x0122,
        "%nctaid.z": 0x0123,
    },
)


C2_B3_V2 = ISAProfile(
    name="c2_b3_v2",
    opcodes={
        **{k: v for k, v in TRACK_B_V1.opcodes.items() if k not in {"LOADI", "CPY", "LOADI64", "CVTFF", "CVTFI", "CVTIF", "CVTII"}},
        "LOADI": 0x0050,
        "CPY": 0x0051,
        "LOADI64": 0x0052,
        "CVTFF": 0x0053,
        "CVTFI": 0x0054,
        "CVTIF": 0x0055,
        "CVTII": 0x0056,
        "TMUL": 0x0060,
        "TMUL_S": 0x0061,
        "TLDA": 0x0062,
        "TSTA": 0x0063,
        "TMOV": 0x0064,
        "TDUP": 0x0065,
    },
    types={
        "f32": 0,
        "f64": 1,
        "f16": 2,
        "bf16": 3,
        "f8e4m3": 4,
        "f8e5m2": 5,
        "f4e2m1": 6,
        "s32": 7,
        "u32": 8,
        "s8": 9,
        "u8": 10,
        "s4": 11,
        "u4": 12,
        "b32": 13,
        "b64": 14,
        "none": 15,
    },
    memory_spaces=TRACK_B_V1.memory_spaces,
    compare_ops=TRACK_B_V1.compare_ops,
    special_registers=TRACK_B_V1.special_registers,
    supports_tensor=True,
)


PROFILES = {TRACK_B_V1.name: TRACK_B_V1, C2_B3_V2.name: C2_B3_V2}

PRED_ENABLE = 0x8000
PRED_NEGATE = 0x4000
TYPE_SHIFT = 3
FAMILY_SHIFT = 8
SPACE_SHIFT = 11


@dataclass
class AECInstruction:
    opcode: str
    dtype: str = "none"
    dest: int = 0
    src1: int = 0
    src2: int = 0
    src3: int = 0
    imm: int = 0
    predicate: int | None = None
    predicate_negated: bool = False
    compare: str | None = None
    memory_space: str | None = None
    cvt_src_type: str | None = None
    family: int = 0


def encode_instruction(inst: AECInstruction, profile: ISAProfile = TRACK_B_V1) -> tuple[int, int, int, int]:
    opcode_name = inst.opcode.upper()
    if opcode_name not in profile.opcodes:
        raise EncodeError(f"unsupported opcode for {profile.name}: {inst.opcode}")
    if inst.dtype not in profile.types:
        raise EncodeError(f"unsupported type for {profile.name}: {inst.dtype}")

    opcode = profile.opcodes[opcode_name]
    pred_ctrl = 0

    if opcode_name.startswith("CVT") and inst.cvt_src_type:
        if inst.cvt_src_type not in profile.types:
            raise EncodeError(f"unsupported conversion source type: {inst.cvt_src_type}")
        pred_ctrl |= (profile.types[inst.dtype] & 0xF) << TYPE_SHIFT
        pred_ctrl |= (profile.types[inst.cvt_src_type] & 0xF) << 10
    else:
        pred_ctrl |= (profile.types[inst.dtype] & 0xF) << TYPE_SHIFT

    if opcode_name == "BRX":
        if inst.predicate is None:
            raise EncodeError("BRX requires a predicate")
        pred_ctrl |= inst.predicate & 0x7
    elif inst.predicate is not None:
        pred_ctrl |= PRED_ENABLE | (inst.predicate & 0x7)
        if inst.predicate_negated:
            pred_ctrl |= PRED_NEGATE
    elif inst.predicate_negated:
        raise EncodeError("predicate_negated requires a predicate")

    if inst.compare:
        if inst.compare not in profile.compare_ops:
            raise EncodeError(f"unsupported compare operation: {inst.compare}")
        pred_ctrl |= (profile.compare_ops[inst.compare] & 0x7) << FAMILY_SHIFT
    elif inst.memory_space:
        if inst.memory_space not in profile.memory_spaces:
            raise EncodeError(f"unsupported memory space: {inst.memory_space}")
        pred_ctrl |= (profile.memory_spaces[inst.memory_space] & 0x7) << SPACE_SHIFT
    elif inst.family:
        pred_ctrl |= (inst.family & 0x7) << FAMILY_SHIFT

    word0 = inst.imm & 0xFFFFFFFF if _uses_immediate(opcode_name) else inst.src3 & 0xFFFFFFFF
    word1 = inst.src2 & 0xFFFFFFFF
    word2 = ((inst.dest & 0xFFFF) << 16) | (inst.src1 & 0xFFFF)
    word3 = ((opcode & 0xFFFF) << 16) | (pred_ctrl & 0xFFFF)
    return (word0, word1, word2, word3)


def _uses_immediate(opcode_name: str) -> bool:
    return opcode_name in {"LOADI", "LOADI64", "BR", "BRX", "CALL"}


def instructions_to_bytes(instructions: Iterable[AECInstruction], profile: ISAProfile = TRACK_B_V1) -> bytes:
    out = bytearray()
    for inst in instructions:
        out += struct.pack("<4I", *encode_instruction(inst, profile))
    return bytes(out)


def words_to_msb_hex(words: tuple[int, int, int, int]) -> str:
    word0, word1, word2, word3 = words
    return f"{word3:08x}{word2:08x}{word1:08x}{word0:08x}"


def bytes_to_words(blob: bytes) -> list[tuple[int, int, int, int]]:
    if len(blob) % 16 != 0:
        raise EncodeError(f"AEC raw binary length is not a multiple of 16 bytes: {len(blob)}")
    return list(struct.iter_unpack("<4I", blob))


def decode_words_to_instruction(words: tuple[int, int, int, int], profile: ISAProfile = TRACK_B_V1) -> AECInstruction:
    word0, word1, word2, word3 = words
    opcode_value = (word3 >> 16) & 0xFFFF
    pred_ctrl = word3 & 0xFFFF
    reverse_opcodes = {value: key for key, value in profile.opcodes.items()}
    reverse_types = {value: key for key, value in profile.types.items()}
    reverse_cmp = {value: key for key, value in profile.compare_ops.items()}
    reverse_spaces = {value: key for key, value in profile.memory_spaces.items()}

    opcode = reverse_opcodes.get(opcode_value)
    if opcode is None:
        raise EncodeError(f"unknown opcode for {profile.name}: 0x{opcode_value:04x}")

    dtype_code = (pred_ctrl >> TYPE_SHIFT) & 0xF
    dtype = reverse_types.get(dtype_code)
    if dtype is None:
        raise EncodeError(f"unknown type for {profile.name}: 0x{dtype_code:x}")

    predicate = None
    predicate_negated = False
    if opcode == "BRX":
        predicate = pred_ctrl & 0x7
    elif pred_ctrl & PRED_ENABLE:
        predicate = pred_ctrl & 0x7
        predicate_negated = bool(pred_ctrl & PRED_NEGATE)

    compare = None
    memory_space = None
    cvt_src_type = None
    if opcode in {"CMP", "CMPP"}:
        compare = reverse_cmp.get((pred_ctrl >> FAMILY_SHIFT) & 0x7)
        if compare is None:
            raise EncodeError(f"unknown compare op for {profile.name}: 0x{(pred_ctrl >> FAMILY_SHIFT) & 0x7:x}")
    elif opcode in {"LD", "ST", "LDC"}:
        memory_space = reverse_spaces.get((pred_ctrl >> SPACE_SHIFT) & 0x7)
        if memory_space is None:
            raise EncodeError(f"unknown memory space for {profile.name}: 0x{(pred_ctrl >> SPACE_SHIFT) & 0x7:x}")
    elif opcode.startswith("CVT"):
        src_type_code = (pred_ctrl >> 10) & 0xF
        cvt_src_type = reverse_types.get(src_type_code)
        if cvt_src_type is None:
            raise EncodeError(f"unknown conversion source type for {profile.name}: 0x{src_type_code:x}")

    return AECInstruction(
        opcode=opcode,
        dtype=dtype,
        dest=(word2 >> 16) & 0xFFFF,
        src1=word2 & 0xFFFF,
        src2=word1 & 0xFFFFFFFF,
        src3=word0 & 0xFFFFFFFF if not _uses_immediate(opcode) else 0,
        imm=word0 & 0xFFFFFFFF if _uses_immediate(opcode) else 0,
        predicate=predicate,
        predicate_negated=predicate_negated,
        compare=compare,
        memory_space=memory_space,
        cvt_src_type=cvt_src_type,
    )


def decode_instruction(words: tuple[int, int, int, int], profile: ISAProfile = TRACK_B_V1) -> str:
    word0, word1, word2, word3 = words
    opcode_value = (word3 >> 16) & 0xFFFF
    pred_ctrl = word3 & 0xFFFF
    reverse_opcodes = {value: key for key, value in profile.opcodes.items()}
    reverse_types = {value: key for key, value in profile.types.items()}
    opcode = reverse_opcodes.get(opcode_value, f"OP_{opcode_value:04x}")
    dtype = reverse_types.get((pred_ctrl >> TYPE_SHIFT) & 0xF, f"type{(pred_ctrl >> TYPE_SHIFT) & 0xF:x}")
    dest = (word2 >> 16) & 0xFFFF
    src1 = word2 & 0xFFFF
    src2 = word1 & 0xFFFF
    src3 = word0 & 0xFFFF
    pred = _decode_predicate(opcode, pred_ctrl)

    reverse_specials = {value: key for key, value in profile.special_registers.items()}

    if opcode == "LOADI":
        text = f"LOADI R{dest}, 0x{word0:08x}"
    elif opcode == "LOADI64":
        imm64 = ((word1 & 0xFFFFFFFF) << 32) | (word0 & 0xFFFFFFFF)
        text = f"LOADI64 R{dest}, 0x{imm64:016x}"
    elif opcode in {"BR", "CALL"}:
        text = f"{opcode} {word0}"
    elif opcode == "BRX":
        text = f"BRX P{pred_ctrl & 0x7}, {word0}"
    elif opcode == "HALT":
        text = "HALT"
    elif opcode in {"LD", "ST", "LDC"}:
        reverse_spaces = {value: key for key, value in profile.memory_spaces.items()}
        space = reverse_spaces.get((pred_ctrl >> SPACE_SHIFT) & 0x7, "space?")
        if opcode == "ST":
            text = f"ST.{space}.{dtype} [R{src1}], R{src2}"
        else:
            text = f"{opcode}.{space}.{dtype} R{dest}, [R{src1}]"
    elif opcode in {"CMP", "CMPP"}:
        reverse_cmp = {value: key for key, value in profile.compare_ops.items()}
        cmp_op = reverse_cmp.get((pred_ctrl >> FAMILY_SHIFT) & 0x7, "cmp?")
        dst_prefix = "P" if opcode == "CMPP" else "R"
        text = f"{opcode}.{cmp_op}.{dtype} {dst_prefix}{dest}, R{src1}, R{src2}"
    elif opcode.startswith("CVT"):
        src_type = reverse_types.get((pred_ctrl >> 10) & 0xF, "type?")
        text = f"{opcode}.{dtype}.{src_type} R{dest}, R{src1}"
    elif opcode == "CPY":
        source = reverse_specials.get(src1, f"R{src1}")
        text = f"CPY.{dtype} R{dest}, {source}"
    elif opcode == "RDTSC":
        text = f"{opcode}.{dtype} R{dest}, R{src1}"
    elif opcode in {"NEG", "ABS", "NOT", "POPC", "FLO", "RCP", "RSQ", "SIN", "COS", "EXP", "LOG", "SQRT"}:
        text = f"{opcode}.{dtype} R{dest}, R{src1}"
    elif opcode in {"MAD", "FMA"}:
        text = f"{opcode}.{dtype} R{dest}, R{src1}, R{src2}, R{src3}"
    else:
        text = f"{opcode}.{dtype} R{dest}, R{src1}, R{src2}"

    return f"{pred}{text}"


def _decode_predicate(opcode: str, pred_ctrl: int) -> str:
    if opcode == "BRX" or (pred_ctrl & PRED_ENABLE) == 0:
        return ""
    neg = "!" if pred_ctrl & PRED_NEGATE else ""
    return f"@{neg}P{pred_ctrl & 0x7} "
