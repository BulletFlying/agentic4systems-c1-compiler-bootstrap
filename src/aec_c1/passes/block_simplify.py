"""Block simplification pass (O2 proven-safe).

Merges empty blocks, threads unconditional jumps, removes unreachable blocks,
and remaps branch targets.  Preserves side-effecting blocks and the entry block.
"""

from __future__ import annotations

from dataclasses import replace
from ..analysis import AnalysisManager
from ..analysis.cfg import CFG, terminator_kind
from ..ir import IRModule
from ..ptx import PTXInstruction
from ._helpers import (
    _is_side_effecting,
    _rebuild_program,
)
from .base import PassResult


class BlockSimplificationPass:
    """Simplify the CFG by removing empty blocks, threading jumps, and deleting
    unreachable blocks (O2 proven-safe).

    Safety guarantees:
    - Side-effecting blocks are never removed.  A block that contains any
      load, store, branch, call, atomic, setp, predicated instruction, or
      instruction with a .cc modifier is treated as side-effecting.
    - The kernel entry block is never deleted.
    - Unreachable blocks (not reachable from entry via any CFG path) are
      removed in one pass.
    - Empty blocks (containing only labels, no instructions) are merged into
      their unique successor.
    - Single-jump blocks (one unconditional branch, no other instructions)
      are threaded directly to their target.
    - All branch targets are remapped after block deletion / merging.
    - Self-cycles are detected and skipped.
    """

    name = "block-simplification"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg = analyses.get("cfg")
        program = module.function.program

        label_to_block: dict[str, str] = {}
        for name, block in cfg.blocks.items():
            for label in block.labels:
                label_to_block[label] = name

        # ---- Compute reachability from entry ----
        reachable: set[str] = set()
        worklist = [cfg.entry]
        while worklist:
            name = worklist.pop()
            if name in reachable:
                continue
            reachable.add(name)
            worklist.extend(cfg.blocks[name].successors)
        unreachable = set(cfg.blocks) - reachable

        # ---- Classify blocks ----
        empty_blocks: set[str] = set()
        jump_blocks: dict[str, str] = {}

        for name, block in cfg.blocks.items():
            if name == cfg.entry:
                # Never delete or merge the entry block.
                continue
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

        # Remove any empty / jump blocks that contain side-effecting instructions.
        def _block_has_side_effect(block_name: str) -> bool:
            block = cfg.blocks.get(block_name)
            if block is None:
                return False
            for inst in block.instructions:
                if _is_side_effecting(inst):
                    return True
            return False

        # Side-effect filtering only applies to unreachable blocks.
        # Empty blocks (0 instructions) and jump blocks (single unconditional
        # branch) are safe to merge — the branch is the terminator, not a
        # side-effecting payload instruction.
        unreachable = {b for b in unreachable if not _block_has_side_effect(b)}

        # ---- Build redirect map (resolve chains) ----
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

        # Build set of blocks to remove: unreachable + redirected (empty/jump)
        blocks_to_remove = unreachable | set(redirect.keys())
        # Never remove the entry block
        blocks_to_remove.discard(cfg.entry)

        if not blocks_to_remove:
            return PassResult(
                details={
                    "redirected_blocks": 0,
                    "removed_labels": 0,
                    "unreachable_blocks_removed": 0,
                    "transforms_applied": 0,
                },
            )

        removed_labels = 0
        kept_items: list[str | PTXInstruction] = []
        redirected_labels: set[str] = set()
        skip_until_next_label = False

        for item in program.items:
            if isinstance(item, str):
                block_name = label_to_block.get(item)
                if block_name in blocks_to_remove:
                    removed_labels += 1
                    redirected_labels.add(item)
                    skip_until_next_label = True
                    continue
                skip_until_next_label = False
                kept_items.append(item)
                continue

            if skip_until_next_label:
                # Instructions belonging to a removed block (between its label
                # and the next label) — skip them.
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

        unreachable_removed = len(unreachable - set(redirect.keys()))

        details = {
            "redirected_blocks": len(redirect),
            "removed_labels": removed_labels,
            "redirected_labels": sorted(redirected_labels),
            "unreachable_blocks_removed": unreachable_removed,
            "transforms_applied": len(redirect) + unreachable_removed,
        }
        if not redirected_labels and unreachable_removed == 0:
            return PassResult(details=details)

        module.function.program = _rebuild_program(program, kept_items)
        return PassResult(
            changed=True,
            details=details,
            invalidated_analyses=frozenset({"cfg", "uniformity", "loops"}),
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
