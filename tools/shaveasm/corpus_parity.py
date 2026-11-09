"""Compare cached vendor objects and diagnose the complete assembly corpus."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from .coverage import operand_shape
from .elf import Elf32, ElfError, compare_sections
from .encoding import encode_packet_with_fixups
from .objwriter import _Assembler, _PendingPacket, assemble
from .parser import AssemblyError, Directive, Instruction, Label, Packet, Statement, parse

_DEFAULT_CORPORA = (
    Path("/mnt/cache/build-shave/native-asm-corpus"),
    Path("/mnt/cache/build-shave/native-dynamic-example-corpus"),
)
_DEFAULT_OUTPUT = Path("/mnt/cache/build-shave/corpus-parity")
_DIAGNOSTIC_NOTE = (
    "Diagnostic continuation removes unparseable lines and replaces rejected packets with one-slot NOPs. "
    "Rejected directives can be partially applied. Offsets, symbol sizes, and branch-delay findings after a rejection are approximate; "
    "unsupported branch forms cannot be checked as branches. Only exact object comparison proves parity."
)


def _line(error: str, fallback: int | None = None) -> int | None:
    match = re.search(r"\bline (\d+)", error)
    return int(match[1]) if match else fallback


def _category(error: str, statement: Statement | None = None) -> str:
    if "data or alignment inside delay window" in error:
        return "delay_window_directive"
    if any(message in error for message in ("content after .end", "no current section", "instruction outside executable section")):
        return "other"
    if ".size expression" in error or "invalid symbol size" in error:
        return "expression"
    if any(word in error for word in ("relocation", "symbol", "local label", "binding")):
        return "symbol_relocation"
    if isinstance(statement, Packet):
        return "instruction"
    if isinstance(statement, Directive):
        if statement.name in (".type", ".global", ".globl", ".local"):
            return "symbol_relocation"
        if "expected integer" in error or "expression" in error or "data value out of range" in error:
            return "expression"
        return "directive"
    if "unsupported instruction" in error or "unmeasured packet" in error:
        return "instruction"
    return "other"


def _entry(error: str, statement: Statement | None = None, fallback: int | None = None) -> dict[str, object]:
    return {"line": _line(error, fallback), "category": _category(error, statement), "reason": error}


def _statements(source: str) -> tuple[list[Statement], list[dict[str, object]], bool]:
    lines = source.splitlines(keepends=True)
    errors: list[dict[str, object]] = []
    removed: set[int] = set()
    while True:
        try:
            return parse("".join(lines)), errors, True
        except AssemblyError as error:
            message = str(error)
            line = _line(message)
            if line is None or not 1 <= line <= len(lines) or line in removed:
                errors.append(_entry(message, fallback=max(1, len(lines))))
                return [], errors, False
            errors.append(_entry(message))
            removed.add(line)
            lines[line - 1] = "\n"


def diagnose(source: str) -> dict[str, object]:
    """Collect independent statement failures, using approximate state after rejected packets."""
    statements, errors, complete = _statements(source)
    assembler = _Assembler()
    for statement in statements:
        line = statement.operations[0].line if isinstance(statement, Packet) else statement.line
        if assembler.ended:
            errors.append(_entry(f"line {line}: content after .end"))
        if isinstance(statement, Packet):
            try:
                encode_packet_with_fixups(statement)
            except AssemblyError as error:
                rejected = []
                for op in statement.operations:
                    try:
                        encode_packet_with_fixups(Packet((op,)))
                    except AssemblyError as op_error:
                        entry = _entry(str(op_error), statement, op.line)
                        entry.update(mnemonic=op.mnemonic, operand_shape=operand_shape(op))
                        rejected.append(entry)
                if not rejected:
                    entry = _entry(str(error), statement, line)
                    entry.update(
                        mnemonic=" || ".join(op.mnemonic for op in statement.operations),
                        operand_shape=" || ".join(operand_shape(op) for op in statement.operations),
                    )
                    rejected.append(entry)
                errors.extend(rejected)
                try:
                    assembler.packet(Packet((Instruction("NOP", (), line),)))
                except AssemblyError as state_error:
                    errors.append(_entry(str(state_error), fallback=line))
                continue
        try:
            if isinstance(statement, Label):
                assembler.label(statement)
            elif isinstance(statement, Directive):
                assembler.directive(statement)
            else:
                assembler.packet(statement)
        except AssemblyError as error:
            errors.append(_entry(str(error), statement, line))

    while True:
        try:
            assembler.resolve_packets()
            break
        except AssemblyError as error:
            message = str(error)
            line = _line(message)
            errors.append(_entry(message))
            removed = False
            for section in assembler.sections:
                for index, event in enumerate(section.events):
                    if isinstance(event, Directive) and event.line == line and "delay window" in message:
                        section.events.pop(index)
                        removed = True
                        break
                    if isinstance(event, _PendingPacket) and event.packet.operations[0].line == line:
                        section.events.pop(index)
                        removed = True
                        break
                if removed:
                    break
            if not removed:
                complete = False
                break

    while True:
        try:
            assembler.resolve_sizes()
            break
        except AssemblyError as error:
            message = str(error)
            line = _line(message)
            errors.append({"line": line, "category": "expression", "reason": message})
            failed = [symbol for symbol in assembler.symbols.values()
                      if symbol.size_expr is not None and symbol.size_expr[3] == line]
            if not failed:
                complete = False
                break
            for symbol in failed:
                symbol.size_expr = None

    while True:
        try:
            assembler.build()
            break
        except AssemblyError as error:
            message = str(error)
            line = _line(message)
            errors.append(_entry(message))
            removed = False
            for section in assembler.sections:
                for index, (_, _, fixup_line) in enumerate(section.relocations):
                    if fixup_line == line:
                        section.relocations.pop(index)
                        removed = True
                        break
                if removed:
                    break
            if not removed:
                complete = False
                break

    errors.sort(key=lambda item: (item["line"] if item["line"] is not None else 0,
                                  str(item.get("mnemonic", "")), str(item["reason"])))
    return {"complete": complete, "note": _DIAGNOSTIC_NOTE, "rejections": errors}


def _first_rejection(source: str, error: AssemblyError) -> dict[str, object]:
    message = str(error)
    line = _line(message)
    try:
        statements = parse(source)
    except AssemblyError:
        statements = []
    matches = [item for item in statements if
               (any(op.line == line for op in item.operations) if isinstance(item, Packet) else item.line == line)]
    statement = next((item for item in matches if not isinstance(item, Label)), matches[0] if matches else None)
    return _entry(message, statement)


def _counts(counter: Counter[str]) -> list[dict[str, object]]:
    return [{"category": key, "count": value} for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def report(paths: list[Path], *, diagnostic: bool = False) -> dict[str, object]:
    """Compare each distinct assembly with its adjacent cached vendor object."""
    files = sorted({file.resolve() for path in paths for file in path.rglob("*.s")})
    records = []
    statuses: Counter[str] = Counter()
    first_rejections: Counter[str] = Counter()
    diagnostic_categories: Counter[str] = Counter()
    shapes: Counter[tuple[str, str]] = Counter()
    for file in files:
        record: dict[str, object] = {"path": str(file), "vendor_object": str(file.with_suffix(".o"))}
        try:
            source = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            record.update(status="unreadable_source", error=str(error))
            statuses["unreadable_source"] += 1
            records.append(record)
            continue
        try:
            native = assemble(source)
        except AssemblyError as error:
            native = None
            first = _first_rejection(source, error)
            record["first_rejection"] = first
            first_rejections[str(first["category"])] += 1
        if diagnostic:
            diagnostics = diagnose(source)
            record["diagnostics"] = diagnostics
            for entry in diagnostics["rejections"]:
                diagnostic_categories[entry["category"]] += 1
                if entry["category"] == "instruction":
                    shapes[(entry["mnemonic"], entry["operand_shape"])] += 1
        try:
            vendor = file.with_suffix(".o").read_bytes()
        except FileNotFoundError:
            record["status"] = "missing_reference"
        except OSError as error:
            record.update(status="unreadable_reference", error=str(error))
        else:
            try:
                Elf32.parse(vendor)
            except ElfError as error:
                record.update(status="invalid_reference", error=str(error))
            else:
                if native is None:
                    record["status"] = "rejected"
                else:
                    try:
                        differences = compare_sections(vendor, native)
                    except ElfError as error:
                        record.update(status="invalid_native", error=str(error))
                    else:
                        record["section_differences"] = differences
                        record["status"] = "exact" if native == vendor else "different"
        statuses[str(record["status"])] += 1
        records.append(record)
    for status in ("exact", "different", "rejected"):
        statuses.setdefault(status, 0)
    if diagnostic:
        for category in ("instruction", "directive", "expression", "symbol_relocation", "delay_window_directive", "other"):
            diagnostic_categories.setdefault(category, 0)
    return {
        "files": records,
        "summary": {
            "files": len(records),
            "statuses": _counts(statuses),
            "first_rejections": _counts(first_rejections),
            "diagnostic_categories": _counts(diagnostic_categories),
            "instruction_shapes": [
                {"mnemonic": mnemonic, "operand_shape": shape, "count": count}
                for (mnemonic, shape), count in sorted(shapes.items(), key=lambda item: (-item[1], item[0]))
            ],
        },
        "diagnostic": diagnostic,
    }


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_reports(result: dict[str, object], output: Path) -> None:
    """Write JSON and a compact Markdown inventory without writing object bytes."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary = result["summary"]
    lines = ["# Corpus object parity", "", f"Files: {summary['files']}", "",
             "| Status | Files |", "| --- | ---: |"]
    lines.extend(f"| {row['category']} | {row['count']} |" for row in summary["statuses"])
    lines.extend(["", "## First rejections", "", "| Category | Files |", "| --- | ---: |"])
    lines.extend(f"| {row['category']} | {row['count']} |" for row in summary["first_rejections"])
    if result["diagnostic"]:
        lines.extend(["", "## Diagnostic rejections", "", _DIAGNOSTIC_NOTE, "",
                      "| Category | Rejections |", "| --- | ---: |"])
        lines.extend(f"| {row['category']} | {row['count']} |" for row in summary["diagnostic_categories"])
        lines.extend(["", "### Top instruction forms", "", "| Mnemonic | Operand shape | Rejections |",
                      "| --- | --- | ---: |"])
        lines.extend(f"| {_markdown(row['mnemonic'])} | {_markdown(row['operand_shape'])} | {row['count']} |"
                     for row in summary["instruction_shapes"][:20])
    lines.extend(["", "## Files", "", "| Source | Status | First rejection |", "| --- | --- | --- |"])
    for record in result["files"]:
        first = record.get("first_rejection")
        detail = f"line {first['line']}: {first['category']}" if first else ""
        lines.append(f"| {_markdown(record['path'])} | {record['status']} | {detail} |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Analyze cached pairs and write reports under the corpus cache by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="*", default=_DEFAULT_CORPORA)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    for path in args.paths:
        if not path.is_dir():
            parser.error(f"corpus directory does not exist: {path}")
    result = report(args.paths, diagnostic=args.diagnostic)
    write_reports(result, args.output)
    for record in result["files"]:
        first = record.get("first_rejection")
        detail = f" line {first['line']}: {first['category']} ({first['reason']})" if first else ""
        print(f"{record['path']}: {record['status']}{detail}")
    print(f"reports: {args.output / 'report.json'}, {args.output / 'summary.md'}")
    if not result["files"] or any(
        record["status"] in {"unreadable_source", "missing_reference", "unreadable_reference", "invalid_reference", "invalid_native"}
        or (args.diagnostic and not record["diagnostics"]["complete"])
        for record in result["files"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
