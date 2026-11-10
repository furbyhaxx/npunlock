"""Report native packet coverage from cached assembly without invoking vendor tools."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from .encoding import encode_packet_with_fixups
from .parser import AssemblyError, Instruction, Packet, parse


def operand_shape(instruction: Instruction) -> str:
    """Group operands by register bank, integer sign, predicate, or symbolic expression."""
    shapes = []
    for operand in instruction.operands:
        register = re.fullmatch(r"([iIvVbB])\d+(\.\d+)?", operand)
        if register:
            shapes.append(register[1].lower() + "reg" + ("_lane" if register[2] else ""))
        elif operand.upper() in {"EQ", "NEQ", "LT", "LTE", "GT", "GTE"}:
            shapes.append("condition")
        else:
            try:
                value = int(operand, 0)
            except ValueError:
                shapes.append("symbol")
            else:
                shapes.append("negative" if value < 0 else "immediate")
    return " ".join(shapes)


def report(paths: list[Path]) -> dict[str, object]:
    """Count each mnemonic/shape once per rejected packet, including co-issued forms."""
    files = sorted({file.resolve() for path in paths for file in path.rglob("*.s")})
    rejected: Counter[tuple[str, str]] = Counter()
    unsupported: Counter[tuple[str, str]] = Counter()
    mnemonics: set[str] = set()
    accepted_mnemonics: set[str] = set()
    packets = accepted = relocatable = 0
    errors = []
    for file in files:
        try:
            statements = parse(file.read_text())
        except AssemblyError as error:
            errors.append({"path": str(file), "error": str(error)})
            continue
        for packet in statements:
            if not isinstance(packet, Packet):
                continue
            packets += 1
            names = {op.mnemonic for op in packet.operations}
            mnemonics.update(names)
            try:
                _, fixups = encode_packet_with_fixups(packet)
            except AssemblyError:
                shapes = {(op.mnemonic, operand_shape(op)) for op in packet.operations}
                rejected.update(shapes)
                missing = set()
                for op in packet.operations:
                    try:
                        encode_packet_with_fixups(Packet((op,)))
                    except AssemblyError:
                        missing.add((op.mnemonic, operand_shape(op)))
                unsupported.update(missing)
            else:
                accepted += 1
                relocatable += bool(fixups)
                accepted_mnemonics.update(names)
    rows = [
        {"mnemonic": mnemonic, "operand_shape": shape, "rejected_packets": count,
         "unsupported_packets": unsupported[(mnemonic, shape)]}
        for (mnemonic, shape), count in sorted(rejected.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"files": len(files), "packets": packets, "accepted_packets": accepted,
            "relocatable_packets": relocatable,
            "mnemonics": len(mnemonics), "accepted_mnemonics": sorted(accepted_mnemonics),
            "rejected_shapes": rows, "parse_errors": errors}


def main() -> None:
    """Print a JSON coverage report for one or more cached corpus directories."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    result = report(args.paths)
    print(json.dumps(result, indent=2))
    if result["parse_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
