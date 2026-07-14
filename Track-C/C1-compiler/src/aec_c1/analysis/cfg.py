"""Control-flow graph utilities for PTX-style C1 input."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ptx import PTXInstruction, PTXProgram


class CFGError(ValueError):
    """Raised when PTX control flow cannot be represented as a CFG."""


@dataclass
class BasicBlock:
    name: str
    instructions: list[PTXInstruction] = field(default_factory=list)
    item_indices: list[int] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    predecessors: set[str] = field(default_factory=set)
    successors: set[str] = field(default_factory=set)
    branch_successors: set[str] = field(default_factory=set)
    fallthrough_successor: str | None = None

    @property
    def terminator(self) -> PTXInstruction | None:
        if not self.instructions:
            return None
        inst = self.instructions[-1]
        if terminator_kind(inst) in {"conditional_branch", "unconditional_branch", "return"}:
            return inst
        return None


@dataclass(frozen=True)
class NaturalLoop:
    header: str
    tail: str
    blocks: frozenset[str]


@dataclass
class CFG:
    blocks: dict[str, BasicBlock]
    entry: str
    label_to_block: dict[str, str]
    item_to_block: dict[int, str]
    block_order: list[str]

    def reverse_postorder(self) -> list[str]:
        visited: set[str] = set()
        postorder: list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            for succ in sorted(self.blocks[name].successors):
                visit(succ)
            postorder.append(name)

        visit(self.entry)
        return list(reversed(postorder))

    def dominators(self) -> dict[str, set[str]]:
        reachable = self.reverse_postorder()
        doms = {name: set(reachable) for name in reachable}
        doms[self.entry] = {self.entry}
        changed = True
        while changed:
            changed = False
            for name in reachable:
                if name == self.entry:
                    continue
                preds = [pred for pred in self.blocks[name].predecessors if pred in doms]
                if preds:
                    new_dom = set.intersection(*(doms[pred] for pred in preds))
                else:
                    new_dom = set()
                new_dom.add(name)
                if new_dom != doms[name]:
                    doms[name] = new_dom
                    changed = True
        return doms

    def backedges(self) -> list[tuple[str, str]]:
        doms = self.dominators()
        edges: list[tuple[str, str]] = []
        for tail, block in self.blocks.items():
            for succ in block.successors:
                if succ in doms.get(tail, set()):
                    edges.append((tail, succ))
        return edges

    def natural_loops(self) -> list[NaturalLoop]:
        loops: list[NaturalLoop] = []
        for tail, header in self.backedges():
            if tail == header:
                # Self-loop: natural loop is just {header}.  External
                # predecessors are outside the loop.
                loops.append(NaturalLoop(header=header, tail=tail, blocks=frozenset({header})))
                continue
            loop_blocks = {header, tail}
            worklist = [tail]
            while worklist:
                block_name = worklist.pop()
                for pred in self.blocks[block_name].predecessors:
                    # Stop at the header: its external predecessors (preheader
                    # etc.) are outside the natural loop.
                    if pred != header and pred not in loop_blocks:
                        loop_blocks.add(pred)
                        worklist.append(pred)
            loops.append(NaturalLoop(header=header, tail=tail, blocks=frozenset(loop_blocks)))
        return loops


def build_cfg(program: PTXProgram) -> CFG:
    labels = _collect_labels(program)
    leaders = _find_leaders(program, labels)
    blocks: dict[str, BasicBlock] = {}
    label_to_block: dict[str, str] = {}
    item_to_block: dict[int, str] = {}
    block_order: list[str] = []

    leader_indices = sorted(leaders)
    synthetic_index = 0
    for pos, leader in enumerate(leader_indices):
        end = leader_indices[pos + 1] if pos + 1 < len(leader_indices) else len(program.items)
        block_labels: list[str] = []
        instructions: list[PTXInstruction] = []
        item_indices: list[int] = []
        item_index = leader
        while item_index < end:
            item = program.items[item_index]
            if isinstance(item, str):
                block_labels.append(item)
            else:
                instructions.append(item)
                item_indices.append(item_index)
            item_index += 1
        if leader == 0 and not block_labels:
            name = "entry"
        elif block_labels:
            name = block_labels[0]
        else:
            name = f"block_{synthetic_index}"
            synthetic_index += 1
        if name in blocks:
            raise CFGError(f"duplicate block name: {name}")
        blocks[name] = BasicBlock(name=name, instructions=instructions, item_indices=item_indices, labels=block_labels)
        block_order.append(name)
        for item_index in item_indices:
            item_to_block[item_index] = name
        for label in block_labels:
            if label in label_to_block:
                raise CFGError(f"duplicate label: {label}")
            label_to_block[label] = name

    if not blocks:
        raise CFGError("PTX program has no basic blocks")
    entry = "entry" if "entry" in blocks else block_order[0]
    _connect_edges(program, blocks, block_order, label_to_block)
    return CFG(
        blocks=blocks,
        entry=entry,
        label_to_block=label_to_block,
        item_to_block=item_to_block,
        block_order=block_order,
    )


def terminator_kind(inst: PTXInstruction | None) -> str:
    if inst is None:
        return "fallthrough"
    base = inst.opcode.split(".")[0]
    if base == "bra":
        return "conditional_branch" if inst.predicate is not None else "unconditional_branch"
    if base == "ret":
        return "return"
    return "fallthrough"


def _collect_labels(program: PTXProgram) -> dict[str, int]:
    labels: dict[str, int] = {}
    for index, item in enumerate(program.items):
        if isinstance(item, str):
            if item in labels:
                raise CFGError(f"duplicate label: {item}")
            labels[item] = index
    return labels


def _find_leaders(program: PTXProgram, labels: dict[str, int]) -> set[int]:
    leaders = {0}
    for index, item in enumerate(program.items):
        if isinstance(item, str):
            leaders.add(index)
            continue
        kind = terminator_kind(item)
        if kind in {"conditional_branch", "unconditional_branch"}:
            if len(item.operands) != 1:
                raise CFGError(f"line {item.source_line}: branch expects one target")
            target = item.operands[0]
            if target not in labels:
                raise CFGError(f"line {item.source_line}: undefined branch target {target}")
            leaders.add(labels[target])
            if index + 1 < len(program.items):
                leaders.add(index + 1)
        elif kind == "return" and index + 1 < len(program.items):
            leaders.add(index + 1)
    return leaders


def _connect_edges(
    program: PTXProgram,
    blocks: dict[str, BasicBlock],
    block_order: list[str],
    label_to_block: dict[str, str],
) -> None:
    next_block = {block_order[index]: block_order[index + 1] for index in range(len(block_order) - 1)}
    for name in block_order:
        block = blocks[name]
        terminator = block.terminator
        kind = terminator_kind(terminator)
        if kind in {"conditional_branch", "unconditional_branch"}:
            assert terminator is not None
            target = terminator.operands[0]
            if target not in label_to_block:
                raise CFGError(f"line {terminator.source_line}: undefined branch target {target}")
            target_block = label_to_block[target]
            block.successors.add(target_block)
            block.branch_successors.add(target_block)
            if kind == "conditional_branch" and name in next_block:
                block.successors.add(next_block[name])
                block.fallthrough_successor = next_block[name]
        elif kind == "fallthrough" and name in next_block:
            block.successors.add(next_block[name])
            block.fallthrough_successor = next_block[name]

    for name, block in blocks.items():
        for succ in block.successors:
            blocks[succ].predecessors.add(name)
