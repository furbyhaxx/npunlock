"""Differential-test independently generated scalar packets against moviAsm."""

from __future__ import annotations

import argparse
import json
import random
from itertools import combinations
from pathlib import Path

from .elf import Elf32
from .encoding import encode_packet
from .oracle import Oracle
from .parser import Packet, parse

_UNITS = ("CMU", "LSU0", "LSU1", "SAU", "IAU", "PEU")


def generate_packets(seed: int, count: int) -> list[str]:
    """Generate conflict-free packets from scalar instruction families seen in GELU."""
    rng = random.Random(seed)

    def operation(unit: str, registers: tuple[str, str, str] | None = None) -> str:
        if registers is None:
            base = _UNITS.index(unit) * 4
            registers = tuple(f"i{base + rng.randrange(4)}" for _ in range(3))
        if unit == "CMU":
            return f"CMU.CP.32 {registers[0]} {registers[1]}"
        if unit in ("LSU0", "LSU1"):
            return f"{unit}.LDIL {registers[0]} {rng.randrange(65536)}"
        if unit == "SAU":
            return f"SAU.ADD.i32 {registers[0]} {registers[1]} {rng.randrange(32)}"
        if unit == "IAU":
            return f"IAU.XOR {registers[0]} {registers[1]} {registers[2]}"
        return "PEU.PC1C " + rng.choice(("EQ", "NEQ", "LT", "LTE", "GT", "GTE"))

    packets = ["NOP", *(f"NOP {n}" for n in range(1, 65))]
    for register in range(32):
        for unit in _UNITS:
            packets.append(operation(unit, (f"i{register}", f"i{31 - register}", f"i{(register + 11) % 32}")))
    packets.extend(("LSU0.LDIL i31 65535", "LSU1.LDIL i0 0", "SAU.ADD.i32 i0 i31 31"))
    shapes = [shape for size in range(1, 5) for shape in combinations(_UNITS, size)]
    shapes.extend(tuple(rng.sample(_UNITS, rng.randrange(1, 5))) for _ in range(count))
    for shape in shapes:
        order = list(shape)
        rng.shuffle(order)
        packets.append("\n || ".join(operation(unit) for unit in order))
    return packets


def verify_packets(oracle: Oracle, output: Path, seed: int, count: int) -> None:
    """Retain oracle fixtures outside git and compare every generated packet byte-for-byte."""
    output = output.resolve()
    if not output.is_relative_to(Path("/mnt/cache/build-shave")):
        raise ValueError("vendor fixtures must remain under /mnt/cache/build-shave")
    output.mkdir(parents=True, exist_ok=True)
    packets = generate_packets(seed, count)
    # The vendor hazard analyzer carries write-back state across .code switches.
    source = (
        "\n".join(
            f".code .text.gap_{index}\n NOP 16\n.code .text.case_{index}\ncase_{index}:\n {packet}"
            for index, packet in enumerate(packets)
        )
        + "\n.end\n"
    )
    (output / "packets.s").write_text(source)
    data = oracle.assemble(source)
    (output / "packets.o").write_bytes(data)
    image = Elf32.parse(data)
    failures = []
    for index, source_packet in enumerate(packets):
        statements = parse(source_packet)
        if len(statements) != 1 or not isinstance(statements[0], Packet):
            raise AssertionError("generated source is not a single packet")
        actual = encode_packet(statements[0])
        expected = image.section(f".text.case_{index}").data
        if actual != expected:
            failures.append({"index": index, "source": source_packet, "vendor": expected.hex(), "native": actual.hex()})
    report = {"seed": seed, "random_packets": count, "total": len(packets), "failures": failures}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise AssertionError(f"{len(failures)}/{len(packets)} packet mismatches; first: {failures[0]}")
    print(f"packet differential: PASS ({len(packets)} packets, seed={seed}, 56 scalar prefix shapes)")


def main() -> None:
    """Run the developer-only Wine oracle differential gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-dir", type=Path, required=True)
    parser.add_argument("--movitools-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=3720)
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    if not 0 <= args.count <= 10000:
        parser.error("--count must be in 0..10000")
    verify_packets(Oracle(args.native_dir, args.movitools_dir), args.output, args.seed, args.count)


if __name__ == "__main__":
    main()
