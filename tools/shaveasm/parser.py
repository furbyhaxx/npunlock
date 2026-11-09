"""Parse vendor SHAVE syntax without modifying scheduling or packet boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass


class AssemblyError(ValueError):
    """Assembly syntax or an encoding is unsupported or invalid."""


@dataclass(frozen=True)
class Instruction:
    """One operation, its unexpanded operands and original source line."""

    mnemonic: str
    operands: tuple[str, ...]
    line: int


@dataclass(frozen=True)
class Packet:
    """Operations explicitly issued together by the source."""

    operations: tuple[Instruction, ...]


@dataclass(frozen=True)
class Directive:
    """A directive and its unmodified argument text."""

    name: str
    arguments: str
    line: int


@dataclass(frozen=True)
class Label:
    """A named position in the current section."""

    name: str
    line: int


Statement = Packet | Directive | Label


def _without_comments(source: str) -> str:
    out: list[str] = []
    index = 0
    quote = ""
    block = False
    line_comment = False
    while index < len(source):
        char = source[index]
        pair = source[index : index + 2]
        if line_comment:
            out.append("\n" if char == "\n" else " ")
            line_comment = char != "\n"
        elif block:
            if pair == "*/":
                out.extend("  ")
                index += 1
                block = False
            else:
                out.append("\n" if char == "\n" else " ")
        elif quote:
            out.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                out.append(source[index])
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            out.append(char)
        elif pair == "/*":
            block = True
            out.extend("  ")
            index += 1
        elif pair == "//" or char == ";":
            line_comment = True
            out.append(" ")
        else:
            out.append(char)
        index += 1
    if block:
        raise AssemblyError("unterminated block comment")
    if quote:
        raise AssemblyError("unterminated quoted string")
    return "".join(out)


def parse(source: str) -> list[Statement]:
    """Preserve labels/directives and join explicit inline or continued VLIW packets."""
    result: list[Statement] = []
    pending: list[Instruction] = []

    def flush() -> None:
        if pending:
            result.append(Packet(tuple(pending)))
            pending.clear()

    for line_number, raw in enumerate(_without_comments(source).splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        label = re.match(r"^([A-Za-z_.$][\w.$]*):\s*", line)
        if label:
            flush()
            result.append(Label(label[1], line_number))
            line = line[label.end() :]
            if not line:
                continue
        if line.startswith("."):
            flush()
            fields = line.split(None, 1)
            result.append(Directive(fields[0].lower(), fields[1] if len(fields) == 2 else "", line_number))
            continue
        continued = line.startswith("||")
        if continued:
            if not pending:
                raise AssemblyError(f"line {line_number}: orphan packet continuation")
            line = line[2:].strip()
        else:
            flush()
        for operation in line.split("||"):
            fields = operation.strip().split(None, 1)
            if not fields:
                raise AssemblyError(f"line {line_number}: empty packet operation")
            mnemonic = fields[0].upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9_.]*", mnemonic):
                raise AssemblyError(f"line {line_number}: invalid mnemonic {fields[0]!r}")
            operands = tuple(re.split(r"[\s,]+", fields[1].strip())) if len(fields) == 2 else ()
            pending.append(Instruction(mnemonic, operands, line_number))
    flush()
    return result
