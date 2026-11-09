"""Fail-closed packet encoder for the independently measured scalar prefix classes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .fixups import Fixup
from .parser import AssemblyError, Instruction, Packet

_ORDER = ("CMU", "LSU0", "LSU1", "SAU", "IAU", "BRU", "PEU")
_PREFIXES = {
    "CMU": (8, 0x81),
    "LSU0": (8, 0x82),
    "LSU1": (8, 0x89),
    "SAU": (8, 0x3C),
    "IAU": (8, 0x86),
    "PEU": (8, 0x85),
    "CMU,LSU0": (8, 0xA4),
    "CMU,LSU1": (16, 0x880E),
    "CMU,SAU": (16, 0xC83E),
    "CMU,IAU": (8, 0xA6),
    "CMU,PEU": (8, 0xA8),
    "LSU0,LSU1": (8, 0xA9),
    "LSU0,SAU": (16, 0xE03E),
    "LSU0,IAU": (8, 0xAA),
    "LSU0,PEU": (8, 0xAB),
    "LSU1,SAU": (16, 0xE08E),
    "LSU1,IAU": (16, 0xA05E),
    "LSU1,PEU": (16, 0xA07E),
    "SAU,IAU": (8, 0xBC),
    "SAU,PEU": (16, 0x8CEE),
    "IAU,PEU": (8, 0xAD),
    "CMU,LSU0,LSU1": (16, 0xA80E),
    "CMU,LSU0,SAU": (16, 0xE83E),
    "CMU,LSU0,IAU": (16, 0xA82E),
    "CMU,LSU0,PEU": (16, 0xA81E),
    "CMU,LSU1,SAU": (16, 0xE28E),
    "CMU,LSU1,IAU": (16, 0xA26E),
    "CMU,LSU1,PEU": (16, 0xA27E),
    "CMU,SAU,IAU": (16, 0xB84E),
    "CMU,SAU,PEU": (24, 0x83080F),
    "CMU,IAU,PEU": (16, 0x8AAE),
    "LSU0,LSU1,SAU": (16, 0xE88E),
    "LSU0,LSU1,IAU": (16, 0xA85E),
    "LSU0,LSU1,PEU": (16, 0xA87E),
    "LSU0,SAU,IAU": (16, 0xB89E),
    "LSU0,SAU,PEU": (16, 0x8EEE),
    "LSU0,IAU,PEU": (16, 0xA2DE),
    "LSU1,SAU,IAU": (16, 0xB8BE),
    "LSU1,SAU,PEU": (24, 0x83800F),
    "LSU1,IAU,PEU": (16, 0xA8DE),
    "SAU,IAU,PEU": (16, 0xACEE),
    "CMU,LSU0,LSU1,SAU": (16, 0xEA8E),
    "CMU,LSU0,LSU1,IAU": (16, 0xAA6E),
    "CMU,LSU0,LSU1,PEU": (16, 0xAA7E),
    "CMU,LSU0,SAU,IAU": (16, 0xBA9E),
    "CMU,LSU0,SAU,PEU": (24, 0x83280F),
    "CMU,LSU0,IAU,PEU": (24, 0x88280F),
    "CMU,LSU1,SAU,IAU": (24, 0x0B880F),
    "CMU,LSU1,SAU,PEU": (24, 0x83880F),
    "CMU,LSU1,IAU,PEU": (24, 0x88880F),
    "CMU,SAU,IAU,PEU": (24, 0x8B080F),
    "LSU0,LSU1,SAU,IAU": (16, 0xBABE),
    "LSU0,LSU1,SAU,PEU": (24, 0x83A00F),
    "LSU0,LSU1,IAU,PEU": (16, 0xAADE),
    "LSU0,SAU,IAU,PEU": (16, 0xAEEE),
    "LSU1,SAU,IAU,PEU": (24, 0x8B800F),
    "BRU": (8, 0xC7),
    "CMU,BRU": (8, 0xE7),
    "LSU0,BRU": (16, 0xC2CE),
    "LSU1,BRU": (16, 0xC8CE),
    "SAU,BRU": (24, 0x33000F),
    "IAU,BRU": (16, 0x38AE),
    "BRU,PEU": (8, 0xB5),
    "CMU,LSU0,BRU": (24, 0x30280F),
    "CMU,LSU1,BRU": (24, 0x30880F),
    "CMU,SAU,BRU": (24, 0x33080F),
    "CMU,IAU,BRU": (16, 0x3AAE),
    "CMU,BRU,PEU": (16, 0xB2AE),
    "LSU0,LSU1,BRU": (16, 0xCACE),
    "LSU0,SAU,BRU": (24, 0x33200F),
    "LSU0,IAU,BRU": (16, 0xE2CE),
    "LSU0,BRU,PEU": (24, 0xB0200F),
    "LSU1,SAU,BRU": (24, 0x33800F),
    "LSU1,IAU,BRU": (16, 0xE8CE),
    "LSU1,BRU,PEU": (24, 0xB0800F),
    "SAU,IAU,BRU": (24, 0x3B000F),
    "SAU,BRU,PEU": (24, 0xB3000F),
    "IAU,BRU,PEU": (16, 0xB8AE),
    "CMU,LSU0,LSU1,BRU": (24, 0x30A80F),
    "CMU,LSU0,SAU,BRU": (24, 0x33280F),
    "CMU,LSU0,IAU,BRU": (24, 0x38280F),
    "CMU,LSU0,BRU,PEU": (24, 0xB0280F),
    "CMU,LSU1,SAU,BRU": (24, 0x33880F),
    "CMU,LSU1,IAU,BRU": (24, 0x38880F),
    "CMU,LSU1,BRU,PEU": (24, 0xB0880F),
    "CMU,SAU,IAU,BRU": (24, 0x3B080F),
    "CMU,SAU,BRU,PEU": (24, 0xB3080F),
    "CMU,IAU,BRU,PEU": (16, 0xBAAE),
    "LSU0,LSU1,SAU,BRU": (24, 0x33A00F),
    "LSU0,LSU1,IAU,BRU": (16, 0xEACE),
    "LSU0,LSU1,BRU,PEU": (24, 0xB0A00F),
    "LSU0,SAU,IAU,BRU": (24, 0x3B200F),
    "LSU0,SAU,BRU,PEU": (24, 0xB3200F),
    "LSU0,IAU,BRU,PEU": (24, 0xB8200F),
    "LSU1,SAU,IAU,BRU": (24, 0x3B800F),
    "LSU1,SAU,BRU,PEU": (24, 0xB3800F),
    "LSU1,IAU,BRU,PEU": (24, 0xB8800F),
    "SAU,IAU,BRU,PEU": (24, 0xBB000F),
    "CMU,LSU0,LSU1,BRU,PEU": (24, 0xB0A80F),
    "CMU,LSU0,SAU,BRU,PEU": (24, 0xB3280F),
    "CMU,LSU0,IAU,BRU,PEU": (24, 0xB8280F),
    "CMU,LSU1,SAU,BRU,PEU": (24, 0xB3880F),
    "CMU,LSU1,IAU,BRU,PEU": (24, 0xB8880F),
    "CMU,SAU,IAU,BRU,PEU": (24, 0xBB080F),
    "LSU0,LSU1,SAU,BRU,PEU": (24, 0xB3A00F),
    "LSU0,LSU1,IAU,BRU,PEU": (24, 0xB8A00F),
    "LSU0,SAU,IAU,BRU,PEU": (24, 0xBB200F),
    "LSU1,SAU,IAU,BRU,PEU": (24, 0xBB800F),
}
_PREDICATES = {"EQ": 1, "NEQ": 14, "LT": 4, "LTE": 5, "GT": 2, "GTE": 3}


@dataclass(frozen=True)
class _Operation:
    unit: str
    value: int
    bits: int
    fixup: Fixup | None = None


def _register(text: str, line: int) -> int:
    match = re.fullmatch(r"[iI]([0-9]+)", text)
    if match is None or not 0 <= int(match[1]) < 32:
        raise AssemblyError(f"line {line}: invalid scalar register {text!r}")
    return int(match[1])


def _immediate(text: str, bits: int, line: int) -> int:
    try:
        value = int(text, 0)
    except ValueError as error:
        raise AssemblyError(f"line {line}: expected unsigned {bits}-bit immediate, got {text!r}") from error
    if not 0 <= value < 1 << bits:
        raise AssemblyError(f"line {line}: {value} exceeds unsigned {bits}-bit immediate")
    return value


def _operation(instruction: Instruction) -> _Operation:
    mnemonic, operands, line = instruction.mnemonic, instruction.operands, instruction.line
    unit = mnemonic.split(".")[0]
    if mnemonic == "BRU.BRA" and len(operands) == 1 and re.fullmatch(r"[A-Za-z_.$][A-Za-z_0-9.$]*", operands[0]):
        return _Operation(unit, 0, 24, Fixup(operands[0], 0, 0, 16, "R_SHAVE_PCREL16"))
    if mnemonic in ("LSU0.LDIL", "LSU1.LDIL") and len(operands) == 2:
        destination = _register(operands[0], line)
        immediate = _immediate(operands[1], 16, line)
        return _Operation(unit, 2 | destination << 3 | immediate << 8, 24)
    if mnemonic == "CMU.CP.32" and len(operands) == 2:
        destination, source = (_register(op, line) for op in operands)
        return _Operation(unit, 0x08000C | destination << 9 | source << 4, 24)
    if mnemonic == "IAU.XOR" and len(operands) == 3:
        destination, left, right = (_register(op, line) for op in operands)
        return _Operation(unit, 0x12 | destination << 10 | left << 5 | right << 15, 20)
    if mnemonic == "SAU.ADD.I32" and len(operands) == 3:
        destination, source = (_register(op, line) for op in operands[:2])
        immediate = _immediate(operands[2], 5, line)
        return _Operation(unit, 0x100000 | destination << 10 | source << 5 | immediate << 15, 24)
    if mnemonic == "PEU.PC1C" and len(operands) == 1 and operands[0].upper() in _PREDICATES:
        return _Operation(unit, 0xB | _PREDICATES[operands[0].upper()] << 4, 8)
    raise AssemblyError(f"line {line}: unsupported instruction form {mnemonic} {' '.join(operands)}")


def encode_packet_with_fixups(packet: Packet) -> tuple[bytes, tuple[Fixup, ...]]:
    """Pack measured forms and retain symbolic relocation fields relative to this packet."""
    if not packet.operations:
        raise AssemblyError("empty packet")
    first = packet.operations[0]
    if first.mnemonic in ("NOP", "BRU.NOP"):
        if len(packet.operations) != 1:
            raise AssemblyError(f"line {first.line}: NOP cannot share this packet")
        if not first.operands:
            return b"\x07", ()
        if first.mnemonic != "NOP" or len(first.operands) != 1:
            raise AssemblyError(f"line {first.line}: unsupported NOP form")
        count = _immediate(first.operands[0], 16, first.line)
        if count == 0:
            raise AssemblyError(f"line {first.line}: NOP count must be positive")
        full, remaining = divmod(count, 16)
        return b"\xf0" * full + (bytes([(remaining - 1) << 4]) if remaining else b""), ()
    operations = [_operation(instruction) for instruction in packet.operations]
    if len({op.unit for op in operations}) != len(operations):
        raise AssemblyError(f"line {first.line}: repeated functional unit in packet")
    operations.sort(key=lambda op: _ORDER.index(op.unit))
    key = ",".join(op.unit for op in operations)
    if key not in _PREFIXES:
        raise AssemblyError(f"line {first.line}: unmeasured packet class {key}")
    bits, value = _PREFIXES[key]
    fixups = []
    for operation in operations:
        if operation.fixup is not None:
            fixup = operation.fixup
            kind = fixup.kind + ("_AT4" if bits % 8 == 4 else "")
            fixups.append(Fixup(fixup.symbol, fixup.addend, bits, fixup.bit_width, kind))
            value |= (bits // 8) << bits
        else:
            value |= operation.value << bits
        bits += operation.bits
    if bits > 128:
        raise AssemblyError(f"line {first.line}: packet exceeds 128 bits")
    return value.to_bytes((bits + 7) // 8, "little"), tuple(fixups)


def encode_packet(packet: Packet) -> bytes:
    """Pack resolved measured forms; reject packets requiring symbolic relocation."""
    data, fixups = encode_packet_with_fixups(packet)
    if fixups:
        raise AssemblyError(f"line {packet.operations[0].line}: packet requires symbolic fixups")
    return data
