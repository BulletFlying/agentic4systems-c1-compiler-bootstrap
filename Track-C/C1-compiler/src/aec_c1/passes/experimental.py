"""O3 experimental passes: Global CP, LICM, block simplification, load reuse.

These passes are NOT proven safe for scoring-critical O2.  Enable only
for research and performance exploration.  Each has known limitations
documented in its class docstring.
"""

from __future__ import annotations

from dataclasses import replace
from ..analysis import AnalysisManager
from ..analysis.cfg import CFG, terminator_kind
from ..ir import IRModule
from ..ptx import PTXInstruction, PTXProgram
from ._helpers import (
    _DESTINATION_REGISTER_RE,
    _LOCAL_CONSTANT_FOLD_BASES,
    _PURE_RESULT_BASES,
    _destination_register,
    _evaluate_u32,
    _format_constant,
    _is_immediate,
    _label_to_block,
    _rebuild_program,
    _resolve_constant,
)
from .base import PassResult


# ===========================================================================
# Global Constant Propagation (O3 experimental)
# ===========================================================================

class GlobalConstantPropagationPass:
    """Propagate constants across basic blocks using CFG facts (O3 experimental).

    Performs forward dataflow to compute constants at block exits, then
    rewrites instructions to use immediate forms.  At merge points it only
    retains constants that agree on all incoming paths.

    Safety:
    - Never propagates through memory, branches, or predicated instructions.
    - Requires valid CFG and uniformity analyses.
    - Invalidates CFG and uniformity after rewriting.
    - Known: may not converge — iteration capped at 20 with warning.
    - Known: apply phase resets at label boundaries only, not unlabeled CFG
      fall-through edges.
    """

    name = "global-constant-propagation"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program

        block_instructions: dict[str, list[tuple[int, PTXInstruction]]] = {
            name: [] for name in cfg.blocks
        }
        for block_name, block in cfg.blocks.items():
            for idx in block.item_indices:
                item = program.items[idx]
                if not isinstance(item, str):
                    block_instructions[block_name].append((idx, item))

        # Forward dataflow: compute constants at block EXIT
        constants_out: dict[str, dict[str, tuple[str, int]]] = {
            name: {} for name in cfg.blocks
        }

        changed = True
        iteration = 0
        while changed and iteration < 20:
            changed = False
            iteration += 1
            for block_name in cfg.block_order:
                block = cfg.blocks[block_name]
                incoming: dict[str, tuple[str, int]] = {}
                preds = [p for p in block.predecessors if p in constants_out]
                if preds:
                    first = constants_out[preds[0]]
                    for var_name, val in first.items():
                        if all(
                            var_name in constants_out[p] and constants_out[p][var_name] == val
                            for p in preds[1:]
                        ):
                            incoming[var_name] = val

                local = dict(incoming)
                for _idx, inst in block_instructions.get(block_name, []):
                    if inst.predicate is not None:
                        continue
                    _, new_const = _fold_with_constants(inst, local)
                    dest = _destination_register(inst)
                    if dest is not None and not dest.startswith("%p"):
                        if new_const is not None:
                            local[dest] = new_const
                        else:
                            local.pop(dest, None)

                if local != constants_out.get(block_name):
                    constants_out[block_name] = local
                    changed = True

        # Apply phase
        folded_count = 0
        folded_destinations: list[str] = []
        kept_items: list[str | PTXInstruction] = []
        local_constants: dict[str, tuple[str, int]] = {}

        for item in program.items:
            if isinstance(item, str):
                block_name = _label_to_block(item, cfg)
                block = cfg.blocks.get(block_name) if block_name else None
                entry: dict[str, tuple[str, int]] = {}
                if block:
                    preds = [p for p in block.predecessors if p in constants_out]
                    if preds:
                        first = constants_out[preds[0]]
                        for var_name, val in first.items():
                            if all(
                                var_name in constants_out[p] and constants_out[p][var_name] == val
                                for p in preds[1:]
                            ):
                                entry[var_name] = val
                local_constants = dict(entry)
                kept_items.append(item)
                continue

            folded, new_constant = _fold_with_constants(item, local_constants)
            dest = _destination_register(item)
            if dest is not None and not dest.startswith("%p"):
                if new_constant is not None:
                    local_constants[dest] = new_constant
                else:
                    local_constants.pop(dest, None)

            if folded != item:
                folded_count += 1
                folded_destinations.append(dest or "<unknown>")
            kept_items.append(folded)

        if changed and iteration >= 20:
            folded_destinations.append("<global-cp-did-not-converge>")

        details = {
            "folded_instruction_count": folded_count,
            "folded_destinations": sorted(folded_destinations),
            "transforms_applied": folded_count,
            "dataflow_iterations": iteration,
            "converged": not changed,
        }
        if folded_count == 0:
            return PassResult(details=details)

        module.function.program = _rebuild_program(program, kept_items)
        return PassResult(
            changed=True,
            details=details,
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )


def _fold_with_constants(
    inst: PTXInstruction,
    constants: dict[str, tuple[str, int]],
) -> tuple[PTXInstruction, tuple[str, int] | None]:
    if inst.predicate is not None:
        return inst, None

    opcode_parts = inst.opcode.split(".")
    base = opcode_parts[0]
    ptx_type = opcode_parts[-1] if len(opcode_parts) >= 2 else ""

    if base not in _LOCAL_CONSTANT_FOLD_BASES | {"and", "or", "xor", "shl", "shr", "mad"}:
        return inst, None

    dest = _destination_register(inst)
    if dest is None or dest.startswith("%p"):
        return inst, None

    sources = list(inst.operands[1:]) if dest else list(inst.operands)
    rewritten = False
    resolved_sources: list[tuple[str, int] | None] = []

    for src in sources:
        known = _resolve_constant(src, ptx_type, constants)
        resolved_sources.append(known)
        if known is not None:
            rewritten = True

    if not rewritten:
        return inst, None

    new_operands = [inst.operands[0]] if dest else []
    for i, src in enumerate(sources):
        known = resolved_sources[i]
        if known is not None:
            new_operands.append(_format_constant(known))
        else:
            new_operands.append(src)

    new_inst = replace(inst, operands=tuple(new_operands))

    if all(r is not None for r in resolved_sources):
        if base == "mov" and len(resolved_sources) == 1:
            return new_inst, resolved_sources[0]
        elif base in {"add", "sub", "mul"} and len(resolved_sources) == 2 and ptx_type == "u32":
            result = _evaluate_u32(base, resolved_sources[0][1], resolved_sources[1][1])
            return new_inst, ("u32", result)
        elif base in {"and", "or", "xor"} and len(resolved_sources) == 2:
            if base == "and":
                val = resolved_sources[0][1] & resolved_sources[1][1]
            elif base == "or":
                val = resolved_sources[0][1] | resolved_sources[1][1]
            else:
                val = resolved_sources[0][1] ^ resolved_sources[1][1]
            result = val & 0xFFFFFFFF
            return replace(new_inst, opcode=f"mov.{ptx_type}", operands=(new_operands[0], _format_constant((ptx_type, result)))), (ptx_type, result)

    return new_inst, None


# ===========================================================================
# Block Simplification (O3 experimental)
# ===========================================================================

class BlockSimplificationPass:
    """Simplify the CFG by removing empty blocks and threading jumps (O3 experimental).

    Known: self-cycles are detected and skipped, but complex mutual cycles
    between empty blocks may still produce dangling references.
    """

    name = "block-simplification"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program

        label_to_block: dict[str, str] = {}
        for name, block in cfg.blocks.items():
            for label in block.labels:
                label_to_block[label] = name

        empty_blocks: set[str] = set()
        jump_blocks: dict[str, str] = {}

        for name, block in cfg.blocks.items():
            if not block.instructions:
                successors = list(block.successors)
                if len(successors) == 1:
                    empty_blocks.add(name)
            elif len(block.instructions) == 1 and block.terminator is not None:
                kind = terminator_kind(block.terminator)
                if kind == "unconditional_branch":
                    target_label = block.terminator.operands[0]
                    target_block = label_to_block.get(target_label)
                    if target_block and target_block != name:
                        jump_blocks[name] = target_block

        redirect: dict[str, str] = {}

        def resolve_chain(block_name: str, visited: frozenset[str] | None = None) -> str:
            if visited is None:
                visited = frozenset()
            if block_name in visited:
                return block_name
            if block_name in redirect:
                return redirect[block_name]
            if block_name in jump_blocks:
                target = resolve_chain(jump_blocks[block_name], visited | {block_name})
                redirect[block_name] = target
                return target
            if block_name in empty_blocks:
                block = cfg.blocks[block_name]
                succs = list(block.successors)
                if len(succs) == 1:
                    target = resolve_chain(succs[0], visited | {block_name})
                    redirect[block_name] = target
                    return target
            return block_name

        for name in cfg.blocks:
            resolve_chain(name)

        redirect = {k: v for k, v in redirect.items() if v != k}

        if not redirect:
            return PassResult(
                details={"redirected_blocks": 0, "removed_labels": 0, "transforms_applied": 0},
            )

        removed_labels = 0
        kept_items: list[str | PTXInstruction] = []
        redirected_labels: set[str] = set()

        for item in program.items:
            if isinstance(item, str):
                block_name = label_to_block.get(item)
                if block_name in empty_blocks:
                    removed_labels += 1
                    redirected_labels.add(item)
                    continue
                kept_items.append(item)
                continue

            base = item.opcode.split(".", 1)[0]
            if base == "bra" and item.operands:
                target = item.operands[0]
                target_block = label_to_block.get(target)
                if target_block and target_block in redirect:
                    new_target_block = redirect[target_block]
                    new_target = _find_block_label(new_target_block, cfg)
                    if new_target and new_target != target:
                        new_operands = (new_target,) + item.operands[1:]
                        item = replace(item, operands=new_operands)
            kept_items.append(item)

        details = {
            "redirected_blocks": len(redirect),
            "removed_labels": removed_labels,
            "redirected_labels": sorted(redirected_labels),
            "transforms_applied": len(redirect),
        }
        if not redirected_labels:
            return PassResult(details=details)

        module.function.program = _rebuild_program(program, kept_items)
        return PassResult(
            changed=True,
            details=details,
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )


def _find_block_label(block_name: str, cfg: CFG) -> str | None:
    block = cfg.blocks.get(block_name)
    if block is None:
        return None
    if block.labels:
        return block.labels[0]
    if block_name == "entry":
        return None
    return block_name


# ===========================================================================
# Loop-Invariant Code Motion (O3 experimental)
# ===========================================================================

class LoopInvariantCodeMotionPass:
    """Hoist loop-invariant pure computations out of natural loops (O3 experimental).

    Known: only handles simple loops with a unique preheader.  Multi-entry
    loops are skipped.  Insertion before preheader terminator may not be safe
    if the terminator is not a branch.
    """

    name = "loop-invariant-code-motion"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program

        loops = cfg.natural_loops()
        if not loops:
            return PassResult(
                details={"hoisted_count": 0, "loops_found": 0, "transforms_applied": 0},
            )

        index_to_block: dict[int, str] = {}
        for name, block in cfg.blocks.items():
            for idx in block.item_indices:
                index_to_block[idx] = name

        def_map: dict[str, tuple[int, str]] = {}
        for i, item in enumerate(program.items):
            if isinstance(item, str):
                continue
            dest = _destination_register(item)
            block_name = index_to_block.get(i)
            if dest is not None and block_name is not None:
                def_map[dest] = (i, block_name)

        total_hoisted = 0
        all_kept: dict[int, str | PTXInstruction] = {
            i: item for i, item in enumerate(program.items)
        }
        insertions: dict[int, list[PTXInstruction]] = {}

        for loop in loops:
            loop_blocks = loop.blocks
            header = loop.header

            header_block = cfg.blocks[header]
            preheaders = [p for p in header_block.predecessors if p not in loop_blocks]
            if len(preheaders) != 1:
                continue
            preheader = preheaders[0]
            preheader_block = cfg.blocks[preheader]

            if not preheader_block.item_indices:
                continue
            insert_before = preheader_block.item_indices[-1]

            invariant: set[int] = set()
            changed = True
            while changed:
                changed = False
                for block_name in sorted(loop_blocks):
                    block = cfg.blocks[block_name]
                    for idx in block.item_indices:
                        if idx in invariant:
                            continue
                        item = program.items[idx]
                        if isinstance(item, str):
                            continue
                        if item.predicate is not None:
                            continue
                        base = item.opcode.split(".", 1)[0]
                        if base not in _PURE_RESULT_BASES:
                            continue

                        operands = list(item.operands[1:]) if _destination_register(item) else list(item.operands)
                        all_invariant = True
                        for op in operands:
                            op = op.strip()
                            if op.startswith("[") and op.endswith("]"):
                                op = op[1:-1].strip()
                            if _is_immediate(op):
                                continue
                            if op.startswith("%"):
                                def_info = def_map.get(op)
                                if def_info is None:
                                    continue
                                def_idx, def_block = def_info
                                if def_block not in loop_blocks or def_idx in invariant:
                                    continue
                                all_invariant = False
                                break

                        if all_invariant:
                            invariant.add(idx)
                            changed = True

            if not invariant:
                continue

            for idx in sorted(invariant):
                item = program.items[idx]
                if isinstance(item, str):
                    continue
                all_kept.pop(idx, None)
                insertions.setdefault(insert_before, []).append(item)
                total_hoisted += 1

        if total_hoisted == 0:
            return PassResult(
                details={"hoisted_count": 0, "loops_found": len(loops), "transforms_applied": 0},
            )

        rebuilt: list[str | PTXInstruction] = []
        for i, item in enumerate(program.items):
            if i in insertions:
                rebuilt.extend(insertions[i])
            if i in all_kept:
                rebuilt.append(all_kept[i])

        module.function.program = _rebuild_program(program, rebuilt)
        return PassResult(
            changed=True,
            details={
                "hoisted_count": total_hoisted,
                "loops_found": len(loops),
                "transforms_applied": total_hoisted,
            },
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )


# ===========================================================================
# Repeated Global Load Reuse (O3 experimental)
# ===========================================================================

class RepeatedGlobalLoadReusePass:
    """Eliminate repeated global loads from the same address (O3 experimental).

    Known: clears cache on labels, stores, branches, calls, atomics, and
    predicated instructions, but does NOT clear on non-branch terminators
    or untracked side-effecting operations.
    """

    name = "repeated-global-load-reuse"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        del analyses
        program = module.function.program
        replaced_count = 0
        kept_items: list[str | PTXInstruction] = []
        load_cache: dict[tuple[str, str], str] = {}

        for item in program.items:
            if isinstance(item, str):
                load_cache.clear()
                kept_items.append(item)
                continue

            base = item.opcode.split(".", 1)[0]

            if base in {"st", "bra", "ret", "brx", "call", "atom"}:
                load_cache.clear()
                kept_items.append(item)
                continue

            if item.predicate is not None:
                load_cache.clear()
                kept_items.append(item)
                continue

            if base == "ld" and item.opcode.startswith("ld.global"):
                parts = item.opcode.split(".")
                if len(parts) < 3:
                    kept_items.append(item)
                    continue
                ptx_type = parts[2]
                dest = item.operands[0].strip()
                addr_operand = item.operands[1].strip()
                if addr_operand.startswith("[") and addr_operand.endswith("]"):
                    addr_reg = addr_operand[1:-1].strip()
                else:
                    addr_reg = addr_operand

                cache_key = (addr_reg, ptx_type)
                if cache_key in load_cache:
                    src = load_cache[cache_key]
                    new_inst = PTXInstruction(
                        opcode=f"mov.{ptx_type}", operands=(dest, src),
                    )
                    kept_items.append(new_inst)
                    replaced_count += 1
                else:
                    load_cache[cache_key] = dest
                    kept_items.append(item)
                continue

            dest = _destination_register(item)
            if dest is not None:
                stale_keys = [k for k in load_cache if k[0] == dest]
                for k in stale_keys:
                    del load_cache[k]

            kept_items.append(item)

        details = {
            "replaced_load_count": replaced_count,
            "transforms_applied": replaced_count,
        }
        if replaced_count == 0:
            return PassResult(details=details)

        module.function.program = _rebuild_program(program, kept_items)
        return PassResult(
            changed=True,
            details=details,
            invalidated_analyses=frozenset({"cfg", "uniformity"}),
        )
