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

    def operation(unit: str, registers: tuple[str, str, str] | None = None, *, store_packet: bool = False) -> str:
        if unit == "BRU":
            return "BRU.BRA external_target"
        if registers is None:
            base = _UNITS.index(unit.split(".")[0]) * 4
            registers = tuple(f"i{base + rng.randrange(4)}" for _ in range(3))
        if unit in ("LSU0.LDO32", "LSU1.STO32"):
            mnemonic = "LSU0.LDO.32" if unit == "LSU0.LDO32" else "LSU1.STO.32"
            return f"{mnemonic} {registers[0]} {registers[1]} {rng.randrange(-16384, 16384)}"
        if unit == "CMU.CMZ16":
            return f"CMU.CMZ.I32 {registers[0]}"
        if unit == "CMU":
            mnemonic = "CMU.CP.32" if store_packet else rng.choice(("CMU.CP.32", "CMU.CMII.I32", "CMU.CMII.U32"))
            return f"{mnemonic} {registers[0]} {registers[1]}"
        if unit == "LSU0" and rng.randrange(3):
            mnemonic = rng.choice(("LSU0.LD.32", "LSU0.CP.32"))
            return f"{mnemonic} {registers[0]} {registers[1]}"
        if unit in ("LSU0", "LSU1"):
            return f"{unit}.LDIL {registers[0]} {rng.randrange(65536)}"
        if unit == "SAU":
            if rng.randrange(2):
                return f"SAU.ADD.F32 {registers[0]} {registers[1]} {registers[2]}"
            return f"SAU.ADD.i32 {registers[0]} {registers[1]} {rng.randrange(32)}"
        if unit == "IAU.ADD24":
            if rng.randrange(4) == 0:
                return f"IAU.INCS {registers[0]} {rng.randrange(-8192, 8192)}"
            if rng.randrange(3) == 0:
                return f"IAU.SHL {registers[0]} {registers[1]} {rng.randrange(32)}"
            right = registers[2] if rng.randrange(2) else str(rng.randrange(256))
            return f"IAU.ADD {registers[0]} {registers[1]} {right}"
        if unit == "IAU":
            mnemonic = rng.choice(("IAU.XOR", "IAU.AND", "IAU.OR", "IAU.LMULL"))
            return f"{mnemonic} {registers[0]} {registers[1]} {registers[2]}"
        condition = rng.choice(("EQ", "NEQ", "LT", "LTE", "GT", "GTE"))
        if unit == "PEU.PCCX12":
            return f"PEU.PCCX {condition} {rng.randrange(64)}"
        return "PEU.PC1C " + condition

    packets = ["NOP", *(f"NOP {n}" for n in range(1, 65))]
    for register in range(32):
        for unit in (*_UNITS, "LSU0.LDO32", "LSU1.STO32", "IAU.ADD24", "CMU.CMZ16", "PEU.PCCX12"):
            packets.append(operation(unit, (f"i{register}", f"i{31 - register}", f"i{(register + 11) % 32}")))
    packets.extend(("LSU0.LDIL i31 65535", "LSU1.LDIL i0 0", "SAU.ADD.i32 i0 i31 31"))
    packets.extend(f"LSU0.LDO.32 i31 i0 {value}" for value in (-16384, -1, 0, 1, 16383))
    packets.extend(f"IAU.ADD i{r} i{31-r} i{(r+11)%32}" for r in range(32))
    packets.extend(f"IAU.ADD i{r} i{31-r} {value}" for r in range(32) for value in (0, 255))
    packets.extend(f"PEU.PCCX {condition} {n}"
                   for condition in ("EQ", "NEQ", "LT", "LTE", "GT", "GTE") for n in range(64))
    shapes = [tuple(key.split(",")) for key in _PREFIXES]
    shapes.extend(rng.choices(shapes, k=count))
    for shape in shapes:
        order = list(shape)
        rng.shuffle(order)
        packets.append("\n || ".join(operation(unit, store_packet="LSU1.STO32" in shape) for unit in order))
    for key in _PREFIXES:
        shape = key.split(",")
        store_packet = "LSU1.STO32" in shape
        if "SAU" in shape:
            packets.append("\n || ".join("SAU.ADD.F32 i12 i13 i14" if unit == "SAU"
                                          else operation(unit, store_packet=store_packet) for unit in shape))
        if "LSU0" in shape:
            for mnemonic in ("LSU0.LD.32", "LSU0.CP.32"):
                packets.append("\n || ".join(f"{mnemonic} i4 i5" if unit == "LSU0"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
        if "IAU" in shape:
            for mnemonic in ("IAU.AND", "IAU.OR", "IAU.LMULL"):
                packets.append("\n || ".join(f"{mnemonic} i16 i17 i18" if unit == "IAU"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
        if "IAU.ADD24" in shape:
            packets.append("\n || ".join(f"IAU.SHL i16 i17 {rng.randrange(32)}" if unit == "IAU.ADD24"
                                          else operation(unit, store_packet=store_packet) for unit in shape))
            packets.append("\n || ".join("IAU.INCS i16 -2345" if unit == "IAU.ADD24"
                                          else operation(unit, store_packet=store_packet) for unit in shape))
        if "CMU" in shape and not store_packet:
            for mnemonic in ("CMU.CMII.I32", "CMU.CMII.U32"):
                packets.append("\n || ".join(f"{mnemonic} i0 i1" if unit == "CMU"
                                              else operation(unit) for unit in shape))
    for mnemonic in ("IAU.AND", "IAU.OR", "IAU.LMULL", "SAU.ADD.F32"):
        for position in range(3):
            for register in range(32):
                operands = ["i0"] * 3
                operands[position] = f"i{register}"
                packets.append(mnemonic + " " + " ".join(operands))
    for position in range(2):
        for register in range(32):
            operands = ["i0", "i0", "0"]
            operands[position] = f"i{register}"
            packets.append("IAU.SHL " + " ".join(operands))
    packets.extend(f"IAU.SHL i0 i0 {n}" for n in range(32))
    for mnemonic in ("CMU.CMII.I32", "CMU.CMII.U32"):
        for position in range(2):
            for register in range(32):
                operands = ["i0", "i0"]
                operands[position] = f"i{register}"
                packets.append(mnemonic + " " + " ".join(operands))
    for position in range(2):
        for register in range(32):
            operands = ["i0", "i0", "0"]
            operands[position] = f"i{register}"
            packets.append("LSU1.STO.32 " + " ".join(operands))
    packets.extend(f"LSU1.STO.32 i31 i0 {value}" for value in (-16384, -1, 0, 1, 16383))
    for mnemonic in ("LSU0.LD.32", "LSU0.CP.32"):
        for position in range(2):
            for register in range(32):
                operands = ["i0", "i0"]
                operands[position] = f"i{register}"
                packets.append(mnemonic + " " + " ".join(operands))
    packets.extend(f"IAU.INCS i{r} 0" for r in range(32))
    packets.extend(f"IAU.INCS i0 {value}" for value in
                   (0, -1, 8191, -8192, *(1 << bit for bit in range(13)),
                    *(-(1 << bit) for bit in range(14))))
    delay_operations = (
        "NOP", "NOP 1", "NOP 2", "NOP 4", "NOP 6", "NOP 16", "NOP 17", "NOP 32",
        "LSU0.LDIL i4 1", "CMU.CMZ.I32 i0", "IAU.ADD i16 i17 231",
        "IAU.XOR i16 i17 i18 || PEU.PCCX NEQ 63",
    )
    branches = ("BRU.BRA external_target", "IAU.XOR i5 i6 i7 || BRU.BRA external_target")
    for branch in branches:
        packets.extend(f"{branch}\n NOP {n}" for n in range(1, 33))
        packets.extend(branch + "\n " + "\n ".join([op] * n)
                       for op in delay_operations for n in range(1, 8))
        packets.extend(branch + "\n " + "\n ".join(rng.choices(delay_operations, k=rng.randrange(1, 10)))
                       for _ in range(count))
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
        if not statements or any(not isinstance(statement, Packet) for statement in statements):
            raise AssertionError("generated source is not a packet sequence")
        sequence = [statement for statement in statements if isinstance(statement, Packet)]
        actual = b""
        fixups = []
        for position, packet in enumerate(sequence):
            data, packet_fixups = encode_packet_with_fixups(packet, following=sequence[position + 1:])
            fixups.extend(Fixup(f.symbol, f.addend, f.bit_offset + len(actual) * 8, f.bit_width, f.kind)
                          for f in packet_fixups)
            actual += data
        name = f".text.case_{index}"
        expected = image.section(name).data
        expected_fixups = _vendor_fixups(image, name)
        if actual != expected or tuple(fixups) != expected_fixups:
            failures.append({"index": index, "source": source_packet, "vendor": expected.hex(), "native": actual.hex(),
                             "vendor_fixups": repr(expected_fixups), "native_fixups": repr(fixups)})
    report = {"seed": seed, "random_packets": count, "random_delay_sequences": 2 * count,
              "total": len(packets), "failures": failures}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise AssertionError(f"{len(failures)}/{len(packets)} packet mismatches; first: {failures[0]}")
    print(f"packet differential: PASS ({len(packets)} cases, seed={seed}, {len(_PREFIXES)} prefix shapes, bytes and fixups)")


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
