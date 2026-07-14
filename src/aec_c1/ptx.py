"""Small PTX-style parser for the public C1 input shape."""

from __future__ import annotations

from dataclasses import dataclass
import re


class PTXParseError(ValueError):
    """Raised when PTX input is outside the supported bootstrap subset."""


@dataclass(frozen=True)
class Parameter:
    name: str
    dtype: str


@dataclass(frozen=True)
class RegisterDecl:
    prefix: str
    dtype: str
    count: int


@dataclass(frozen=True)
class PTXInstruction:
    opcode: str
    operands: tuple[str, ...]
    predicate: str | None = None
    predicate_negated: bool = False
    source_line: int = 0


@dataclass(frozen=True)
class PTXProgram:
    kernel_name: str
    parameters: tuple[Parameter, ...]
    registers: tuple[RegisterDecl, ...]
    items: tuple[str | PTXInstruction, ...]


PARAM_RE = re.compile(r"\.param\s+\.(?P<dtype>\w+)\s+(?P<name>\w+)")
REG_RE = re.compile(r"\.reg\s+\.(?P<dtype>\w+)\s+%(?P<prefix>[A-Za-z]+)(?:<(?P<count>\d+)>)?")
ENTRY_RE = re.compile(r"\.entry\s+(?P<name>\w+)\s*\(")
PRED_RE = re.compile(r"@(?P<neg>!)?%(?P<pred>p\d*)\s+")


def parse_ptx(text: str) -> PTXProgram:
    kernel_name = ""
    parameters: list[Parameter] = []
    registers: list[RegisterDecl] = []
    items: list[str | PTXInstruction] = []
    in_body = False

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if not kernel_name:
            entry = ENTRY_RE.search(line)
            if entry:
                kernel_name = entry.group("name")
        param = PARAM_RE.search(line)
        if param and not in_body:
            parameters.append(Parameter(name=param.group("name"), dtype=param.group("dtype")))
            continue
        if line == "{":
            in_body = True
            continue
        if line == "}":
            in_body = False
            continue
        if not in_body:
            continue
        reg = REG_RE.match(line.rstrip(";"))
        if reg:
            registers.append(
                RegisterDecl(
                    prefix=reg.group("prefix"),
                    dtype=reg.group("dtype"),
                    count=int(reg.group("count") or "1"),
                )
            )
            continue
        if line.endswith(":"):
            items.append(line[:-1])
            continue
        if line.endswith(";"):
            line = line[:-1].strip()
        predicate = None
        predicate_negated = False
        pred = PRED_RE.match(line)
        if pred:
            predicate = pred.group("pred")
            predicate_negated = bool(pred.group("neg"))
            line = line[pred.end() :].strip()
        if not line:
            continue
        opcode, operands = _split_instruction(line)
        items.append(
            PTXInstruction(
                opcode=opcode,
                operands=tuple(operands),
                predicate=predicate,
                predicate_negated=predicate_negated,
                source_line=line_no,
            )
        )

    if not kernel_name:
        raise PTXParseError("PTX entry kernel name was not found")
    return PTXProgram(
        kernel_name=kernel_name,
        parameters=tuple(parameters),
        registers=tuple(registers),
        items=tuple(items),
    )


def _split_instruction(line: str) -> tuple[str, list[str]]:
    parts = line.split(None, 1)
    opcode = parts[0]
    if len(parts) == 1:
        return opcode, []
    return opcode, _split_operands(parts[1])


def _split_operands(text: str) -> list[str]:
    operands: list[str] = []
    current: list[str] = []
    bracket_depth = 0
    for char in text:
        if char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
        if char == "," and bracket_depth == 0:
            operands.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        operands.append("".join(current).strip())
    return operands
