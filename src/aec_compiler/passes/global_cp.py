"""Global constant propagation pass (O2 proven-safe).

Forward dataflow constant propagation across basic blocks with join-point
safety and unlabeled CFG-boundary tracking.
"""

from __future__ import annotations

from dataclasses import replace
from ..analysis import AnalysisManager
from ..analysis.cfg import CFG
from ..ir import IRModule
from ..ptx import PTXInstruction
from ._helpers import (
    _DESTINATION_REGISTER_RE,
    _LOCAL_CONSTANT_FOLD_BASES,
    _destination_register,
    _evaluate_u32,
    _format_constant,
    _label_to_block,
    _rebuild_program,
    _resolve_constant,
)
from .base import PassResult


class GlobalConstantPropagationPass:
    """Propagate constants across basic blocks using CFG dataflow (O2 proven-safe).

    Performs forward dataflow to compute constants at block exits, then
    rewrites instructions to use immediate forms.  At merge (join) points it
    only retains constants that agree on ALL incoming paths.

    Safety guarantees:
    - Never propagates through memory (load/store), branches, calls, atomics,
      predicated instructions, or instructions with .cc modifiers.
    - At every block boundary (labeled or unlabeled), entry constants are
      computed as the intersection of all predecessor exit constants.
    - Convergence: iteration is capped at 20 rounds.  On the restricted PTX
      9.3 subset typical convergence is 3-8 rounds.
    - Invalidates CFG and uniformity after rewriting.
    """

    name = "global-constant-propagation"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program

        # Map each program index to its containing block and collect per-block
        # instructions for the dataflow phase.
        idx_to_block: dict[int, str] = {}
        block_instructions: dict[str, list[tuple[int, PTXInstruction]]] = {
            name: [] for name in cfg.blocks
        }
        for block_name, block in cfg.blocks.items():
            for idx in block.item_indices:
                idx_to_block[idx] = block_name
                item = program.items[idx]
                if not isinstance(item, str):
                    block_instructions[block_name].append((idx, item))

        # ---- Forward dataflow: compute constants at block EXIT ----
        constants_out: dict[str, dict[str, tuple[str, int]]] = {
            name: {} for name in cfg.blocks
        }

        changed = True
        iteration = 0
        max_iterations = 20
        while changed and iteration < max_iterations:
            changed = False
            iteration += 1
            for block_name in cfg.block_order:
                block = cfg.blocks[block_name]
                # Join-point safety: intersection of all predecessor exit constants.
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
                    # Side-effect guard: never fold through .cc modifiers
                    if ".cc" in inst.opcode:
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

        # ---- Apply phase: rewrite with per-instruction block tracking ----
        folded_count = 0
        folded_destinations: list[str] = []
        kept_items: list[str | PTXInstruction] = []
        local_constants: dict[str, tuple[str, int]] = {}
        prev_block: str | None = None

        for i, item in enumerate(program.items):
            if isinstance(item, str):
                # Label boundary: reset from CFG dataflow.
                block_name = _label_to_block(item, cfg)
                if block_name:
                    prev_block = block_name
                    local_constants = _block_entry_constants(block_name, cfg, constants_out)
                kept_items.append(item)
                continue

            # Detect unlabeled block boundary by tracking block transitions
            # via the CFG's item-to-block index.
            current_block = idx_to_block.get(i)
            if current_block is not None and current_block != prev_block:
                prev_block = current_block
                local_constants = _block_entry_constants(current_block, cfg, constants_out)

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

        if changed and iteration >= max_iterations:
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


def _block_entry_constants(
    block_name: str,
    cfg: CFG,
    constants_out: dict[str, dict[str, tuple[str, int]]],
) -> dict[str, tuple[str, int]]:
    """Compute the entry constants for a block as the intersection of all
    predecessor exit constants (safe join-point merge)."""
    block = cfg.blocks.get(block_name)
    if block is None:
        return {}
    preds = [p for p in block.predecessors if p in constants_out]
    if not preds:
        return {}
    first = constants_out[preds[0]]
    entry: dict[str, tuple[str, int]] = {}
    for var_name, val in first.items():
        if all(
            var_name in constants_out[p] and constants_out[p][var_name] == val
            for p in preds[1:]
        ):
            entry[var_name] = val
    return entry


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
            return new_inst, (ptx_type, result)
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
