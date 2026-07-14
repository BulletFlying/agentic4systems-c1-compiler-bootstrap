"""Non-optimizing M2.2-A passes used to establish the framework."""

from __future__ import annotations

from ..analysis import AnalysisManager, CFG, Uniformity
from ..ir import IRBlock, IRModule
from .base import PassResult


class ValidateProgramPass:
    name = "validate-program"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        del analyses
        if not module.function.name:
            raise ValueError("IR function has no kernel name")
        if not module.function.program.items:
            raise ValueError("IR function has no executable items")
        return PassResult(details={"kernel": module.function.name})


class MaterializeCFGPass:
    name = "materialize-cfg"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg: CFG = analyses.get("cfg")
        blocks = tuple(
            IRBlock(
                name=name,
                instruction_count=len(cfg.blocks[name].instructions),
                predecessors=tuple(sorted(cfg.blocks[name].predecessors)),
                successors=tuple(sorted(cfg.blocks[name].successors)),
            )
            for name in cfg.block_order
        )
        changed = blocks != module.function.blocks
        module.function.blocks = blocks
        return PassResult(
            changed=changed,
            details={"basic_blocks": len(blocks), "entry": cfg.entry},
        )


class RecordUniformityPass:
    name = "record-uniformity"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        facts = analyses.get("uniformity")
        counts = {state.value: 0 for state in Uniformity}
        for branch in facts.branch_states.values():
            counts[branch.state.value] += 1
        value = {
            "branches": len(facts.branch_states),
            "unknown": counts[Uniformity.UNKNOWN.value],
            "uniform": counts[Uniformity.UNIFORM.value],
            "varying": counts[Uniformity.VARYING.value],
        }
        changed = module.metadata.get("uniformity") != value
        module.metadata["uniformity"] = value
        return PassResult(changed=changed, details=value)


class RecordLoopAnalysisPass:
    name = "record-loop-analysis"

    def run(self, module: IRModule, analyses: AnalysisManager) -> PassResult:
        cfg: CFG = analyses.get("cfg")
        value = {
            "backedges": len(cfg.backedges()),
            "natural_loops": len(cfg.natural_loops()),
        }
        changed = module.metadata.get("loops") != value
        module.metadata["loops"] = value
        return PassResult(changed=changed, details=value)
