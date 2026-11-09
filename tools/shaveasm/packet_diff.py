"""Differential-test independently generated scalar packets against moviAsm."""

from __future__ import annotations

import argparse
import json
import random
import struct
from pathlib import Path

from .elf import Elf32
from .encoding import _PREFIXES, encode_packet_with_fixups
from .fixups import Fixup
from .oracle import Oracle
from .parser import Packet, parse

_UNITS = ("CMU", "LSU0", "LSU1", "SAU", "IAU", "BRU", "PEU")


def generate_packets(seed: int, count: int) -> list[str]:
    """Generate conflict-free packets from scalar instruction families seen in GELU."""
    rng = random.Random(seed)

    def operation(unit: str, registers: tuple[str, str, str] | None = None) -> str:
        if unit == "BRU":
            return "BRU.BRA external_target"
        if registers is None:
            base = _UNITS.index(unit.split(".")[0]) * 4
            registers = tuple(f"i{base + rng.randrange(4)}" for _ in range(3))
        if unit == "LSU0.LDO32":
            return f"LSU0.LDO.32 {registers[0]} {registers[1]} {rng.randrange(-16384, 16384)}"
        if unit == "CMU.CMZ16":
            return f"CMU.CMZ.I32 {registers[0]}"
        if unit == "CMU":
            return f"CMU.CP.32 {registers[0]} {registers[1]}"
        if unit in ("LSU0", "LSU1"):
            return f"{unit}.LDIL {registers[0]} {rng.randrange(65536)}"
        if unit == "SAU":
            return f"SAU.ADD.i32 {registers[0]} {registers[1]} {rng.randrange(32)}"
        if unit == "IAU.ADD24":
            right = registers[2] if rng.randrange(2) else str(rng.randrange(256))
            return f"IAU.ADD {registers[0]} {registers[1]} {right}"
        if unit == "IAU":
            return f"IAU.XOR {registers[0]} {registers[1]} {registers[2]}"
        return "PEU.PC1C " + rng.choice(("EQ", "NEQ", "LT", "LTE", "GT", "GTE"))

    packets = ["NOP", *(f"NOP {n}" for n in range(1, 65))]
    for register in range(32):
        for unit in (*_UNITS, "LSU0.LDO32", "IAU.ADD24", "CMU.CMZ16"):
            packets.append(operation(unit, (f"i{register}", f"i{31 - register}", f"i{(register + 11) % 32}")))
    packets.extend(("LSU0.LDIL i31 65535", "LSU1.LDIL i0 0", "SAU.ADD.i32 i0 i31 31"))
    packets.extend(f"LSU0.LDO.32 i31 i0 {value}" for value in (-16384, -1, 0, 1, 16383))
    packets.extend(f"IAU.ADD i{r} i{31-r} i{(r+11)%32}" for r in range(32))
    packets.extend(f"IAU.ADD i{r} i{31-r} {value}" for r in range(32) for value in (0, 255))
    shapes = [tuple(key.split(",")) for key in _PREFIXES]
    shapes.extend(rng.choices(shapes, k=count))
    for shape in shapes:
        order = list(shape)
        rng.shuffle(order)
        packets.append("\n || ".join(operation(unit) for unit in order))
    return packets


def _vendor_fixups(image: Elf32, name: str) -> tuple[Fixup, ...]:
    sections = [section for section in image.sections if section.name == ".rela" + name]
    result = []
    for section in sections:
        symbols = image.sections[section.link]
        strings = image.sections[symbols.link].data
        for offset, info, addend in struct.iter_unpack("<IIi", section.data):
            symbol_offset = struct.unpack_from("<I", symbols.data, (info >> 8) * symbols.entry_size)[0]
            end = strings.index(b"\0", symbol_offset)
            symbol = strings[symbol_offset:end].decode()
            kind = {209: "R_SHAVE_PCREL16", 210: "R_SHAVE_PCREL16_AT4"}[info & 255]
            result.append(Fixup(symbol, addend, offset * 8 + (4 if info & 255 == 210 else 0), 16, kind))
    return tuple(result)


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
        actual, fixups = encode_packet_with_fixups(statements[0])
        name = f".text.case_{index}"
        expected = image.section(name).data
        expected_fixups = _vendor_fixups(image, name)
        if actual != expected or fixups != expected_fixups:
            failures.append({"index": index, "source": source_packet, "vendor": expected.hex(), "native": actual.hex(),
                             "vendor_fixups": repr(expected_fixups), "native_fixups": repr(fixups)})
    report = {"seed": seed, "random_packets": count, "total": len(packets), "failures": failures}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise AssertionError(f"{len(failures)}/{len(packets)} packet mismatches; first: {failures[0]}")
    print(f"packet differential: PASS ({len(packets)} packets, seed={seed}, {len(_PREFIXES)} prefix shapes, bytes and fixups)")


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
