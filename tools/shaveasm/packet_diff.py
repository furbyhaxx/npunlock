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

_UNITS = ("CMU", "LSU0", "LSU1", "SAU", "IAU", "BRU", "PEU", "VAU")


def generate_packets(seed: int, count: int) -> list[str]:
    """Generate conflict-free packets from scalar instruction families seen in GELU."""
    rng = random.Random(seed)

    def operation(unit: str, registers: tuple[str, str, str] | None = None, *, store_packet: bool = False) -> str:
        if unit in ("VAU", "VAU.OR20"):
            mnemonic = "VAU.OR" if unit == "VAU.OR20" else "VAU.MUL.F32"
            return mnemonic + " " + " ".join(f"v{rng.randrange(32)}" for _ in range(3))
        if unit == "BRU":
            return "BRU.BRA external_target"
        if unit == "BRU.JMP16":
            register = registers[0] if registers is not None else f"i{rng.randrange(32)}"
            return f"BRU.JMP {register}"
        if registers is None:
            base = _UNITS.index(unit.split(".")[0]) * 4
            registers = tuple(f"i{base + rng.randrange(4)}" for _ in range(3))
        if unit == "LSU0.LDO32" and rng.randrange(2):
            destination = registers[0] if not store_packet and rng.randrange(2) else f"v{rng.randrange(4, 8)}.{rng.randrange(2)}"
            return f"LSU0.LDO.64 {destination} {registers[1]} {rng.randrange(-16384, 16384)}"
        if unit == "LSU1.STO32" and rng.randrange(2):
            mnemonic = rng.choice(("LSU1.LDO.64", "LSU1.STO.64"))
            return f"{mnemonic} v{rng.randrange(8, 12)}.{rng.randrange(2)} {registers[1]} {rng.randrange(-16384, 16384)}"
        if unit in ("LSU0.LDO32", "LSU1.STO32"):
            mnemonic = (rng.choice(("LSU0.LDO.32", "LSU0.STO.32")) if unit == "LSU0.LDO32"
                        else rng.choice(("LSU1.STO.32", "LSU1.LDO.32")))
            return f"{mnemonic} {registers[0]} {registers[1]} {rng.randrange(-16384, 16384)}"
        if unit == "LSU1.STI20":
            return f"LSU1.STI.16.F32.F16 {registers[0]} {registers[1]}"
        if unit == "LSU0.LD20":
            return f"LSU0.LD.32.F16.F32 {registers[0]} {registers[1]}"
        if unit == "CMU.CMPI28":
            return f"CMU.CMPI {registers[0]} {rng.randrange(65536)}"
        if unit == "CMU.CMZ16":
            return f"CMU.CMZ.I32 {registers[0]}"
        if unit == "CMU" and rng.randrange(4) == 0:
            return f"CMU.CP.32 {registers[0]} v{rng.randrange(32)}.{rng.randrange(4)}"
        if unit == "CMU":
            mnemonic = "CMU.CP.32" if store_packet else rng.choice(("CMU.CP.32", "CMU.CMII.I32", "CMU.CMII.U32", "CMU.CMII.F32"))
            return f"{mnemonic} {registers[0]} {registers[1]}"
        if unit == "LSU0" and rng.randrange(4) == 0:
            return f"LSU0.LD.16 {registers[0]}.{rng.randrange(4)} {registers[1]}"
        if unit == "LSU1" and rng.randrange(4) == 0:
            return f"LSU1.CP.32 {registers[0]} {registers[1]}"
        if unit in ("LSU0", "LSU1") and rng.randrange(3) == 0:
            immediate = "external_target" if rng.randrange(2) else str(rng.randrange(65536))
            return f"{unit}.LDIH {registers[0]} {immediate}"
        if unit == "LSU0" and rng.randrange(3):
            mnemonic = rng.choice(("LSU0.LD.32", "LSU0.CP.32", "LSU0.ST.32"))
            return f"{mnemonic} {registers[0]} {registers[1]}"
        if unit in ("LSU0", "LSU1"):
            immediate = "external_target" if unit == "LSU1" and rng.randrange(2) else str(rng.randrange(65536))
            return f"{unit}.LDIL {registers[0]} {immediate}"
        if unit == "SAU.AND20":
            return f"SAU.AND {registers[0]} {registers[1]} {registers[2]}"
        if unit == "SAU":
            if rng.randrange(2):
                mnemonic = rng.choice(("SAU.ADD.F32", "SAU.SUB.F32", "SAU.MUL.I32", "SAU.MUL.F32"))
                return f"{mnemonic} {registers[0]} {registers[1]} {registers[2]}"
            mnemonic = rng.choice(("SAU.ADD.I32", "SAU.SHL.X32", "SAU.SHR.U32"))
            right = registers[2] if rng.randrange(2) else str(rng.randrange(32))
            return f"{mnemonic} {registers[0]} {registers[1]} {right}"
        if unit == "IAU.ADD24":
            if rng.randrange(4) == 0:
                return f"IAU.INCS {registers[0]} {rng.randrange(-8192, 8192)}"
            if rng.randrange(3) == 0:
                mnemonic = rng.choice(("IAU.SHL", "IAU.SHR.U32"))
                right = registers[2] if rng.randrange(2) else str(rng.randrange(32))
                return f"{mnemonic} {registers[0]} {registers[1]} {right}"
            mnemonic = rng.choice(("IAU.ADD", "IAU.SUB", "IAU.MUL"))
            immediate = rng.randrange(-128, 128) if mnemonic == "IAU.MUL" else rng.randrange(256)
            right = registers[2] if rng.randrange(2) else str(immediate)
            return f"{mnemonic} {registers[0]} {registers[1]} {right}"
        if unit == "IAU":
            mnemonic = rng.choice(("IAU.XOR", "IAU.AND", "IAU.OR", "IAU.LMULL", "IAU.LMULH", "IAU.ADDCI", "IAU.SUBCI"))
            return f"{mnemonic} {registers[0]} {registers[1]} {registers[2]}"
        condition = rng.choice(("EQ", "NEQ", "LT", "LTE", "GT", "GTE"))
        if unit == "PEU.PCCX12":
            return f"PEU.PCCX {condition} {rng.randrange(64)}"
        return "PEU.PC1C " + condition

    packets = []
    for position in range(3):
        for register in range(32):
            operands = ["v0"] * 3
            operands[position] = f"v{register}"
            for mnemonic in ("VAU.MUL.F32", "VAU.ADD.F32", "VAU.SUB.F32", "VAU.OR"):
                packets.append(mnemonic + " " + " ".join(operands))
    packets.extend(["NOP", *(f"NOP {n}" for n in range(1, 65))])
    for register in range(32):
        for unit in (*_UNITS, "LSU0.LDO32", "LSU1.STO32", "IAU.ADD24", "CMU.CMZ16", "PEU.PCCX12", "BRU.JMP16", "LSU0.LD20", "LSU1.STI20"):
            packets.append(operation(unit, (f"i{register}", f"i{31 - register}", f"i{(register + 11) % 32}")))
    packets.extend(f"{mnemonic} i{r} i{31-r} {literal}"
                   for mnemonic in ("SAU.ADD.F32", "SAU.MUL.F32") for r in range(32)
                   for literal in ("0.5", "1.0", "2.0", "3.0", "-0.5", "-1.0", "-2.0", "-3.0", "+1.0"))
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
        packets.append("\n || ".join(operation(unit, store_packet=bool({"LSU1.STO32", "LSU1.STI20"} & set(shape))) for unit in order))
    for key in _PREFIXES:
        shape = key.split(",")
        if "VAU" in shape:
            for mnemonic in ("VAU.ADD.F32", "VAU.SUB.F32"):
                packets.append("\n || ".join(f"{mnemonic} v3 v4 v5" if unit == "VAU"
                                              else operation(unit, store_packet=bool({"LSU1.STO32", "LSU1.STI20"} & set(shape)))
                                              for unit in shape))
        store_packet = bool({"LSU1.STO32", "LSU1.STI20"} & set(shape))
        if "LSU0.LDO32" in shape:
            for source in ("i4", "v4.0", "v4.1"):
                if source == "i4" and "LSU1.STI20" in shape:
                    continue
                packets.append("\n || ".join(f"LSU0.STO.64 {source} i5 -3" if unit == "LSU0.LDO32"
                                              else "LSU1.LD.32 i8 i9" if unit == "LSU1"
                                              else "LSU1.LDO.32 i8 i9 -3" if unit == "LSU1.STO32"
                                              else operation(unit, store_packet=True) for unit in shape))
            for destination in ("i4", "v4.0", "v4.1"):
                packets.append("\n || ".join(f"LSU0.LDO.64 {destination} i5 -3" if unit == "LSU0.LDO32"
                                              else "LSU1.STO.32 i8 i9 -3" if unit == "LSU1.STO32"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            packets.append("\n || ".join("LSU0.STO.32 i4 i5 -3" if unit == "LSU0.LDO32"
                                          else operation(unit, store_packet=store_packet) for unit in shape))
        if "LSU1.STO32" in shape:
            for source in ("i8", "v8.0", "v8.1"):
                packets.append("\n || ".join(f"LSU1.STO.64 {source} i9 -3" if unit == "LSU1.STO32"
                                              else "LSU0.LD.32 i4 i5" if unit == "LSU0"
                                              else "LSU0.LDO.32 i4 i5 -3" if unit == "LSU0.LDO32"
                                              else operation(unit, store_packet=True) for unit in shape))
            for destination in ("i8", "v8.0", "v8.1"):
                if destination == "i8" and "LSU0.LD20" in shape:
                    continue
                packets.append("\n || ".join(f"LSU1.LDO.64 {destination} i9 -3" if unit == "LSU1.STO32"
                                              else "LSU0.CP.32 i4 i5" if unit == "LSU0"
                                              else "LSU0.STO.32 i4 i5 -3" if unit == "LSU0.LDO32"
                                              else operation(unit, store_packet=True) for unit in shape))
            packets.append("\n || ".join("LSU1.LDO.32 i8 i9 -3" if unit == "LSU1.STO32"
                                          else operation(unit, store_packet=True) for unit in shape))
        if "LSU1.STI20" in shape:
            packets.append("\n || ".join("LSU1.LD.32.F16.F32 i8 i9" if unit == "LSU1.STI20"
                                          else "LSU0.LDO.32 i4 i5 -3" if unit == "LSU0.LDO32"
                                          else operation(unit, store_packet=True) for unit in shape))
        if "BRU.JMP16" in shape:
            packets.append("\n || ".join("BRU.SWP i30" if unit == "BRU.JMP16"
                                          else operation(unit, store_packet=store_packet) for unit in shape))
        if "SAU.AND20" in shape:
            packets.append("\n || ".join("SAU.XOR i12 i13 i14" if unit == "SAU.AND20"
                                          else operation(unit, store_packet=store_packet) for unit in shape))
        if "SAU" in shape:
            for mnemonic in ("SAU.ADD.F32", "SAU.MUL.F32"):
                packets.append("\n || ".join(f"{mnemonic} i12 i13 " + rng.choice(("0.5", "1.0", "3.0", "-1.0")) if unit == "SAU"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            for mnemonic in ("SAU.ADD.I32", "SAU.SHL.X32", "SAU.SHR.U32", "SAU.SHR.U16"):
                packets.append("\n || ".join(f"{mnemonic} i12 i13 i14" if unit == "SAU"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            for mnemonic in ("SAU.ADD.F32", "SAU.SUB.F32", "SAU.MUL.I32", "SAU.MUL.F32", "SAU.DIV.F32", "SAU.SHL.X32", "SAU.SHR.U32", "SAU.SHR.U16"):
                right = str(rng.randrange(32)) if mnemonic in ("SAU.SHL.X32", "SAU.SHR.U32", "SAU.SHR.U16") else "i14"
                packets.append("\n || ".join(f"{mnemonic} i12 i13 {right}" if unit == "SAU"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
        if "LSU0" in shape:
            for destination in ("i4", "v4.0", "v4.1"):
                packets.append("\n || ".join(f"LSU0.LD.64 {destination} i5" if unit == "LSU0"
                                              else "LSU1.STO.32 i8 i9 -3" if unit == "LSU1.STO32"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            for lane in range(4):
                packets.append("\n || ".join(f"LSU0.LD.16 i4.{lane} i5" if unit == "LSU0"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            for immediate in ("43210", "external_target"):
                packets.append("\n || ".join(f"LSU0.LDIH i4 {immediate}" if unit == "LSU0"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            for mnemonic in ("LSU0.LD.32", "LSU0.CP.32", "LSU0.ST.32"):
                packets.append("\n || ".join(f"{mnemonic} i4 i5" if unit == "LSU0"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
        if "IAU" in shape:
            for mnemonic in ("IAU.AND", "IAU.OR", "IAU.LMULL", "IAU.LMULH", "IAU.ADDCI", "IAU.SUBCI"):
                packets.append("\n || ".join(f"{mnemonic} i16 i17 i18" if unit == "IAU"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
        if "IAU.ADD24" in shape:
            for mnemonic in ("IAU.SHL", "IAU.SHR.U32"):
                packets.append("\n || ".join(f"{mnemonic} i16 i17 i18" if unit == "IAU.ADD24"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            for mnemonic in ("IAU.SHL", "IAU.SHR.U32"):
                packets.append("\n || ".join(f"{mnemonic} i16 i17 {rng.randrange(32)}" if unit == "IAU.ADD24"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
            packets.append("\n || ".join("IAU.INCS i16 -2345" if unit == "IAU.ADD24"
                                          else operation(unit, store_packet=store_packet) for unit in shape))
            for mnemonic, values in (("IAU.SUB", ("i18", "255")), ("IAU.MUL", ("i18", "-123"))):
                for right in values:
                    packets.append("\n || ".join(f"{mnemonic} i16 i17 {right}" if unit == "IAU.ADD24"
                                                  else operation(unit, store_packet=store_packet) for unit in shape))
        if "CMU" in shape:
            for lane in range(4):
                packets.append("\n || ".join(f"CMU.CP.32 i0 v31.{lane}" if unit == "CMU"
                                              else operation(unit, store_packet=store_packet) for unit in shape))
        if "CMU" in shape and not store_packet:
            for mnemonic in ("CMU.CMII.I32", "CMU.CMII.U32", "CMU.CMII.F32", "CMU.CMII.I8"):
                packets.append("\n || ".join(f"{mnemonic} i0 i1" if unit == "CMU"
                                              else operation(unit) for unit in shape))
    for key in _PREFIXES:
        shape = key.split(",")
        if "LSU1" in shape:
            for lane in range(4):
                packets.append("\n || ".join(f"LSU1.STI.16 i8.{lane} i9" if unit == "LSU1"
                                              else operation(unit, store_packet=True) for unit in shape))
            for source in ("i8", "v8.0", "v8.1"):
                packets.append("\n || ".join(f"LSU1.ST.64 {source} i9" if unit == "LSU1"
                                              else "LSU0.LD.32 i4 i5" if unit == "LSU0"
                                              else "LSU0.LDO.32 i4 i5 -3" if unit == "LSU0.LDO32"
                                              else operation(unit, store_packet=True) for unit in shape))
            for destination in ("i8", "v8.0", "v8.1"):
                if destination == "i8" and "LSU0.LD20" in shape:
                    continue
                packets.append("\n || ".join(f"LSU1.LD.64 {destination} i9" if unit == "LSU1"
                                              else "LSU0.CP.32 i4 i5" if unit == "LSU0"
                                              else "LSU0.STO.32 i4 i5 -3" if unit == "LSU0.LDO32"
                                              else operation(unit, store_packet=True) for unit in shape))
            packets.append("\n || ".join("LSU1.CP.32 i8 i9" if unit == "LSU1"
                                          else operation(unit, store_packet="LSU1.STO32" in shape) for unit in shape))
            packets.append("\n || ".join("LSU1.LDIL i8 external_target" if unit == "LSU1"
                                          else operation(unit, store_packet="LSU1.STO32" in shape) for unit in shape))
            for immediate in ("43210", "external_target"):
                packets.append("\n || ".join(f"LSU1.LDIH i8 {immediate}" if unit == "LSU1"
                                              else operation(unit, store_packet="LSU1.STO32" in shape) for unit in shape))
            for mnemonic in ("LSU1.STI.32", "LSU1.LD.32", "LSU1.ST.32"):
                packets.append("\n || ".join(f"{mnemonic} i8 i9" if unit == "LSU1"
                                              else operation(unit, store_packet=True) for unit in shape))
    for position in range(2):
        for register in range(32):
            operands = ["i0", "i0"]
            operands[position] = f"i{register}"
            for mnemonic in ("LSU1.STI.32", "LSU1.LD.32", "LSU1.ST.32", "LSU1.CP.32", "LSU1.STI.16.F32.F16", "LSU1.LD.32.F16.F32"):
                packets.append(mnemonic + " " + " ".join(operands))
    for mnemonic in ("IAU.AND", "IAU.OR", "IAU.LMULL", "IAU.LMULH", "IAU.ADDCI", "IAU.SUBCI",
                     "SAU.ADD.F32", "SAU.ADD.I32", "SAU.SHL.X32", "SAU.SUB.F32", "SAU.MUL.I32", "SAU.MUL.F32", "SAU.DIV.F32", "SAU.AND", "SAU.XOR", "IAU.SHL", "IAU.SHR.U32", "SAU.SHR.U32", "SAU.SHR.U16"):
        for position in range(3):
            for register in range(32):
                operands = ["i0"] * 3
                operands[position] = f"i{register}"
                packets.append(mnemonic + " " + " ".join(operands))
    for position in range(2):
        for register in range(32):
            operands = ["i0", "i0", "0"]
            operands[position] = f"i{register}"
            for mnemonic in ("IAU.SHL", "IAU.SHR.U32", "SAU.SHL.X32", "SAU.SHR.U32", "SAU.SHR.U16"):
                packets.append(mnemonic + " " + " ".join(operands))
    packets.extend(f"{mnemonic} i0 i0 {n}"
                   for mnemonic in ("IAU.SHL", "IAU.SHR.U32", "SAU.SHL.X32", "SAU.SHR.U32", "SAU.SHR.U16") for n in range(32))
    for mnemonic in ("CMU.CMII.I32", "CMU.CMII.U32", "CMU.CMII.F32", "CMU.CMII.I8"):
        for position in range(2):
            for register in range(32):
                operands = ["i0", "i0"]
                operands[position] = f"i{register}"
                packets.append(mnemonic + " " + " ".join(operands))
    for position in range(2):
        for register in range(32):
            operands = ["i0", "i0", "0"]
            operands[position] = f"i{register}"
            for mnemonic in ("LSU0.STO.32", "LSU1.STO.32"):
                packets.append(mnemonic + " " + " ".join(operands))
    packets.extend(f"LSU0.STO.32 i0 i0 {value}" for value in
                   (0, -1, 16383, -16384, *(1 << bit for bit in range(14)),
                    *(-(1 << bit) for bit in range(15))))
    packets.extend(f"LSU1.STO.32 i31 i0 {value}" for value in (-16384, -1, 0, 1, 16383))
    packets.extend(f"LSU1.STI.16 i{register}.{lane} i0"
                   for register in range(32) for lane in range(4))
    packets.extend(f"LSU1.STI.16 i0.0 i{register}" for register in range(32))
    packets.extend(f"LSU1.ST.64 i{register} i0" for register in range(32))
    packets.extend(f"LSU1.ST.64 v{register}.{lane} i0"
                   for register in range(32) for lane in range(2))
    packets.extend(f"LSU1.ST.64 i0 i{register}" for register in range(32))
    packets.extend(f"LSU1.LD.64 i{register} i0" for register in range(32))
    packets.extend(f"LSU1.LD.64 v{register}.{lane} i0"
                   for register in range(32) for lane in range(2))
    packets.extend(f"LSU1.LD.64 i0 i{register}" for register in range(32))
    packets.extend(f"LSU0.LD.64 i{register} i0" for register in range(32))
    packets.extend(f"LSU0.LD.64 v{register}.{lane} i0"
                   for register in range(32) for lane in range(2))
    packets.extend(f"LSU0.LD.64 i0 i{register}" for register in range(32))
    packets.extend(f"LSU0.STO.64 i{register} i0 0" for register in range(32))
    packets.extend(f"LSU0.STO.64 v{register}.{lane} i0 0"
                   for register in range(32) for lane in range(16))
    packets.extend(f"LSU0.STO.64 i0 i{register} 0" for register in range(32))
    packets.extend(f"LSU0.STO.64 i0 i0 {value}" for value in
                   (0, -1, 16383, -16384, *(1 << bit for bit in range(14)),
                    *(-(1 << bit) for bit in range(15))))
    packets.extend(f"LSU1.STO.64 i{register} i0 0" for register in range(32))
    packets.extend(f"LSU1.STO.64 v{register}.{lane} i0 0"
                   for register in range(32) for lane in range(16))
    packets.extend(f"LSU1.STO.64 i0 i{register} 0" for register in range(32))
    packets.extend(f"LSU1.STO.64 i0 i0 {value}" for value in
                   (0, -1, 16383, -16384, *(1 << bit for bit in range(14)),
                    *(-(1 << bit) for bit in range(15))))
    packets.extend(f"LSU1.LDO.64 i{register} i0 0" for register in range(32))
    packets.extend(f"LSU1.LDO.64 v{register}.{lane} i0 0"
                   for register in range(32) for lane in range(16))
    packets.extend(f"LSU1.LDO.64 i0 i{register} 0" for register in range(32))
    packets.extend(f"LSU1.LDO.64 i0 i0 {value}" for value in
                   (0, -1, 16383, -16384, *(1 << bit for bit in range(14)),
                    *(-(1 << bit) for bit in range(15))))
    packets.extend(f"LSU0.LDO.64 i{register} i0 0" for register in range(32))
    packets.extend(f"LSU0.LDO.64 v{register}.{lane} i0 0"
                   for register in range(32) for lane in range(16))
    packets.extend(f"LSU0.LDO.64 i0 i{register} 0" for register in range(32))
    packets.extend(f"LSU0.LDO.64 i0 i0 {value}" for value in
                   (0, -1, 16383, -16384, *(1 << bit for bit in range(14)),
                    *(-(1 << bit) for bit in range(15))))
    packets.extend(f"LSU0.LD.16 i{register}.{lane} i0"
                   for register in range(32) for lane in range(4))
    packets.extend(f"LSU0.LD.16 i0.0 i{register}" for register in range(32))
    for mnemonic in ("LSU0.LD.32", "LSU0.CP.32", "LSU0.ST.32", "LSU0.LD.32.F16.F32"):
        for position in range(2):
            for register in range(32):
                operands = ["i0", "i0"]
                operands[position] = f"i{register}"
                packets.append(mnemonic + " " + " ".join(operands))
    for position in range(2):
        for register in range(32):
            operands = ["i0", "i0", "0"]
            operands[position] = f"i{register}"
            packets.append("LSU1.LDO.32 " + " ".join(operands))
    packets.extend(f"LSU1.LDO.32 i0 i0 {value}" for value in
                   (0, -1, 16383, -16384, *(1 << bit for bit in range(14)),
                    *(-(1 << bit) for bit in range(15))))
    for unit in ("LSU0", "LSU1"):
        packets.extend(f"{unit}.LDIH i{r} {immediate}" for r in range(32)
                       for immediate in ("0", "external_target"))
        packets.extend(f"{unit}.LDIH i0 {value}" for value in (0, 65535, *(1 << bit for bit in range(16))))
    for position in range(3):
        for register in range(32):
            operands = ["i0"] * 3
            operands[position] = f"i{register}"
            for mnemonic in ("IAU.SUB", "IAU.MUL"):
                packets.append(mnemonic + " " + " ".join(operands))
    packets.extend(f"IAU.SUB i0 i0 {value}" for value in (0, 255, *(1 << bit for bit in range(8))))
    packets.extend(f"IAU.MUL i0 i0 {value}" for value in
                   (0, -1, -128, 127, *(1 << bit for bit in range(7)), *(-(1 << bit) for bit in range(8))))
    packets.extend(f"IAU.INCS i{r} 0" for r in range(32))
    packets.extend(f"IAU.INCS i0 {value}" for value in
                   (0, -1, 8191, -8192, *(1 << bit for bit in range(13)),
                    *(-(1 << bit) for bit in range(14))))
    packets.extend(f"BRU.SWP i{r}" for r in range(32))
    packets.extend(f"LSU1.LDIL i{r} external_target" for r in range(32))
    packets.extend(f"CMU.CP.32 i{r} v0.0" for r in range(32))
    packets.extend(f"CMU.CP.32 i0 v{r}.{lane}" for r in range(32) for lane in range(4))
    packets.extend(f"CMU.CMPI i{r} 0" for r in range(32))
    packets.extend(f"CMU.CMPI i0 {value}" for value in (0, 65535, *(1 << bit for bit in range(16))))
    delay_operations = (
        "NOP", "NOP 1", "NOP 2", "NOP 4", "NOP 6", "NOP 16", "NOP 17", "NOP 32",
        "LSU0.LDIL i4 1", "CMU.CMZ.I32 i0", "IAU.ADD i16 i17 231",
        "IAU.XOR i16 i17 i18 || PEU.PCCX NEQ 63",
    )
    branches = ("BRU.BRA external_target", "IAU.XOR i5 i6 i7 || BRU.BRA external_target",
                "BRU.JMP i30", "IAU.XOR i5 i6 i7 || BRU.JMP i30",
                "BRU.SWP i30", "IAU.XOR i5 i6 i7 || BRU.SWP i30")
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
            kind = {200: "R_SHAVE_LO16", 201: "R_SHAVE_LO16_AT4",
                    202: "R_SHAVE_HI16", 203: "R_SHAVE_HI16_AT4",
                    209: "R_SHAVE_PCREL16", 210: "R_SHAVE_PCREL16_AT4"}[info & 255]
            result.append(Fixup(symbol, addend, offset * 8 + (4 if kind.endswith("_AT4") else 0), 16, kind))
    # Vendor relocation rows are not ordered by field position.
    return tuple(sorted(result, key=lambda fixup: fixup.bit_offset))


def verify_packets(oracle: Oracle, output: Path, seed: int, count: int) -> None:
    """Retain oracle fixtures outside git and compare every generated packet byte-for-byte."""
    output = output.resolve()
    if not output.is_relative_to(Path("/mnt/cache/build-shave")):
        raise ValueError("vendor fixtures must remain under /mnt/cache/build-shave")
    output.mkdir(parents=True, exist_ok=True)
    packets = generate_packets(seed, count)
    failures = []
    # Each case can add code, relocation and symbol sections to the bounded ELF32 object.
    for start in range(0, len(packets), 30000):
        # The vendor hazard analyzer carries write-back state across .code switches.
        # Reuse the gap section to stay below ELF32's section-count limit.
        source = (
            "\n".join(
                f".code .text.gap\n NOP 16\n.code .text.case_{index}\ncase_{index}:\n {packet}"
                for index, packet in enumerate(packets[start:start + 30000], start)
            )
            + "\n.end\n"
        )
        (output / f"packets-{start // 30000}.s").write_text(source)
        data = oracle.assemble(source)
        (output / f"packets-{start // 30000}.o").write_bytes(data)
        image = Elf32.parse(data)
        for index, source_packet in enumerate(packets[start:start + 30000], start):
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
    report = {"seed": seed, "random_packets": count, "random_delay_sequences": 6 * count,
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
