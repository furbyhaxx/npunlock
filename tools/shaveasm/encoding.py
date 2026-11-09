"""Fail-closed packet encoder for the independently measured scalar prefix classes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import AssemblyError, Instruction, Packet

_ORDER = ("CMU", "LSU0", "LSU1", "SAU", "IAU", "PEU")
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
}
_PREDICATES = {"EQ": 1, "NEQ": 14, "LT": 4, "LTE": 5, "GT": 2, "GTE": 3}


@dataclass(frozen=True)
class _Operation:
    unit: str
    value: int
    bits: int


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


def encode_packet(packet: Packet) -> bytes:
    """Pack measured scalar forms; reject every unmeasured class or unsupported packet."""
    if not packet.operations:
        raise AssemblyError("empty packet")
    first = packet.operations[0]
    if first.mnemonic in ("NOP", "BRU.NOP"):
        if len(packet.operations) != 1:
            raise AssemblyError(f"line {first.line}: NOP cannot share this packet")
        if not first.operands:
            return b"\x07"
        if first.mnemonic != "NOP" or len(first.operands) != 1:
            raise AssemblyError(f"line {first.line}: unsupported NOP form")
        count = _immediate(first.operands[0], 16, first.line)
        if count == 0:
            raise AssemblyError(f"line {first.line}: NOP count must be positive")
        full, remaining = divmod(count, 16)
        return b"\xf0" * full + (bytes([(remaining - 1) << 4]) if remaining else b"")
    operations = [_operation(instruction) for instruction in packet.operations]
    if len({op.unit for op in operations}) != len(operations):
        raise AssemblyError(f"line {first.line}: repeated functional unit in packet")
    operations.sort(key=lambda op: _ORDER.index(op.unit))
    key = ",".join(op.unit for op in operations)
    if key not in _PREFIXES:
        raise AssemblyError(f"line {first.line}: unmeasured packet class {key}")
    bits, value = _PREFIXES[key]
    for operation in operations:
        value |= operation.value << bits
        bits += operation.bits
    if bits > 128:
        raise AssemblyError(f"line {first.line}: packet exceeds 128 bits")
    return value.to_bytes((bits + 7) // 8, "little")
