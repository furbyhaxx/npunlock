"""Capture literal example and contrib C kernels through the vendor compile/assembly oracle."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .elf import Elf32
from .encoding import encode_packet
from .oracle import Oracle, OracleError
from .parser import AssemblyError, Packet, parse

_ENTRY = re.compile(rb"\bvoid\s+controlled_act\s*\(")


def discover(root: Path) -> tuple[dict[bytes, list[str]], list[str]]:
    """Find complete literal kernel sources without evaluating or importing application code."""
    sources: dict[bytes, list[str]] = {}
    dynamic = []
    for base in (root / "examples", root / "contrib"):
        for path in sorted(base.rglob("*.c")):
            data = path.read_bytes()
            if _ENTRY.search(data):
                sources.setdefault(data, []).append(str(path.relative_to(root)))
        for path in sorted(base.rglob("*.py")):
            tree = ast.parse(path.read_text())
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if isinstance(node, ast.JoinedStr):
                    fragments = "".join(str(part.value) for part in node.values if isinstance(part, ast.Constant))
                    if "controlled_act" in fragments:
                        dynamic.append(f"{path.relative_to(root)}:{node.lineno}")
                if not isinstance(node, ast.Constant) or not isinstance(node.value, (bytes, str)):
                    continue
                if isinstance(parents.get(node), ast.JoinedStr):
                    continue
                data = node.value.encode() if isinstance(node.value, str) else node.value
                entry = _ENTRY.search(data)
                if entry:
                    site = f"{path.relative_to(root)}:{node.lineno}"
                    if b"}" not in data[entry.end() :]:
                        dynamic.append(site + " (entry fragment assembled by application)")
                    else:
                        sources.setdefault(data, []).append(site)
    return sources, dynamic


def capture(oracle: Oracle, root: Path, output: Path) -> None:
    """Retain original oracle artifacts and a truthful native packet coverage inventory."""
    output = output.resolve()
    if not output.is_relative_to(Path("/mnt/cache/build-shave")):
        raise ValueError("vendor corpora must remain under /mnt/cache/build-shave")
    output.mkdir(parents=True, exist_ok=True)
    sources, dynamic = discover(root)
    header = (root / "include/npunlock/npu3720_kernel.h").read_bytes()
    records = []
    mnemonics: Counter[str] = Counter()
    for source, sites in sources.items():
        digest = hashlib.sha256(source).hexdigest()
        prefix = output / digest[:16]
        prefix.with_suffix(".c").write_bytes(source)
        record: dict[str, object] = {"source_sha256": digest, "sites": sites, "prefix": prefix.name}
        records.append(record)
        try:
            expanded = source.replace(b"#include <npunlock/npu3720_kernel.h>", header)
            assembly = oracle.compile(expanded)
            prefix.with_suffix(".s").write_text(assembly)
            obj = oracle.assemble(assembly)
            prefix.with_suffix(".o").write_bytes(obj)
            Elf32.parse(obj)
            record.update(status="captured", assembly_bytes=len(assembly.encode()), object_bytes=len(obj))
            packets = [statement for statement in parse(assembly) if isinstance(statement, Packet)]
            missing: Counter[str] = Counter()
            for packet in packets:
                mnemonics.update(instruction.mnemonic for instruction in packet.operations)
                try:
                    encode_packet(packet)
                except AssemblyError as error:
                    missing[str(error)] += 1
            record.update(
                packets=len(packets), supported_packets=len(packets) - sum(missing.values()), unsupported=dict(missing)
            )
        except (OracleError, AssemblyError) as error:
            record.update(status="failed", diagnostic=str(error))
        (output / "manifest.json").write_text(
            json.dumps(
                {"records": records, "dynamic_sources_not_evaluated": dynamic, "mnemonics": dict(mnemonics)}, indent=2
            )
            + "\n"
        )
    captured = sum(record["status"] == "captured" for record in records)
    print(
        f"corpus capture: {captured}/{len(records)} unique literal sources; {len(dynamic)} dynamic sources require explicit inputs"
    )
    print(
        f"native packet support: {sum(int(r.get('supported_packets', 0)) for r in records)}/{sum(int(r.get('packets', 0)) for r in records)}; {len(mnemonics)} mnemonics"
    )


def main() -> None:
    """Capture the corpus without running examples or NPU inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-dir", type=Path, required=True)
    parser.add_argument("--movitools-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    capture(Oracle(args.native_dir, args.movitools_dir), root, args.output)


if __name__ == "__main__":
    main()
