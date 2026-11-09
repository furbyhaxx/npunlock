"""Fail-closed packet encoder for the independently measured scalar prefix classes."""

from __future__ import annotations

import re
from collections.abc import Sequence
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
    "LSU0.LDO32": (8, 0xC2),
    "CMU,LSU0.LDO32": (8, 0xE4),
    "LSU0.LDO32,LSU1": (8, 0xB9),
    "LSU0.LDO32,SAU": (16, 0xF03E),
    "LSU0.LDO32,IAU": (8, 0xBA),
    "LSU0.LDO32,BRU": (16, 0xC3CE),
    "LSU0.LDO32,PEU": (8, 0xBB),
    "CMU,LSU0.LDO32,LSU1": (16, 0xB80E),
    "CMU,LSU0.LDO32,SAU": (16, 0xF83E),
    "CMU,LSU0.LDO32,IAU": (16, 0xB82E),
    "CMU,LSU0.LDO32,BRU": (24, 0x30380F),
    "CMU,LSU0.LDO32,PEU": (16, 0xB81E),
    "LSU0.LDO32,LSU1,SAU": (16, 0xEC8E),
    "LSU0.LDO32,LSU1,IAU": (16, 0xAC5E),
    "LSU0.LDO32,LSU1,BRU": (16, 0xCBCE),
    "LSU0.LDO32,LSU1,PEU": (16, 0xAC7E),
    "LSU0.LDO32,SAU,IAU": (16, 0xBC9E),
    "LSU0.LDO32,SAU,BRU": (24, 0x33300F),
    "LSU0.LDO32,SAU,PEU": (16, 0x8FEE),
    "LSU0.LDO32,IAU,BRU": (16, 0xE3CE),
    "LSU0.LDO32,IAU,PEU": (16, 0xA3DE),
    "LSU0.LDO32,BRU,PEU": (24, 0xB0300F),
    "CMU,LSU0.LDO32,LSU1,SAU": (16, 0xEE8E),
    "CMU,LSU0.LDO32,LSU1,IAU": (16, 0xAE6E),
    "CMU,LSU0.LDO32,LSU1,BRU": (24, 0x30B80F),
    "CMU,LSU0.LDO32,LSU1,PEU": (16, 0xAE7E),
    "CMU,LSU0.LDO32,SAU,IAU": (16, 0xBE9E),
    "CMU,LSU0.LDO32,SAU,BRU": (24, 0x33380F),
    "CMU,LSU0.LDO32,SAU,PEU": (24, 0x83380F),
    "CMU,LSU0.LDO32,IAU,BRU": (24, 0x38380F),
    "CMU,LSU0.LDO32,IAU,PEU": (24, 0x88380F),
    "CMU,LSU0.LDO32,BRU,PEU": (24, 0xB0380F),
    "LSU0.LDO32,LSU1,SAU,IAU": (16, 0xBBBE),
    "LSU0.LDO32,LSU1,SAU,BRU": (24, 0x33B00F),
    "LSU0.LDO32,LSU1,SAU,PEU": (24, 0x83B00F),
    "LSU0.LDO32,LSU1,IAU,BRU": (16, 0xEBCE),
    "LSU0.LDO32,LSU1,IAU,PEU": (16, 0xABDE),
    "LSU0.LDO32,LSU1,BRU,PEU": (24, 0xB0B00F),
    "LSU0.LDO32,SAU,IAU,BRU": (24, 0x3B300F),
    "LSU0.LDO32,SAU,IAU,PEU": (16, 0xAFEE),
    "LSU0.LDO32,SAU,BRU,PEU": (24, 0xB3300F),
    "LSU0.LDO32,IAU,BRU,PEU": (24, 0xB8300F),
    "IAU.ADD24": (8, 0xC6),
    "CMU,IAU.ADD24": (8, 0xE6),
    "LSU0,IAU.ADD24": (8, 0xEA),
    "LSU0.LDO32,IAU.ADD24": (8, 0xFA),
    "LSU1,IAU.ADD24": (16, 0xE05E),
    "SAU,IAU.ADD24": (8, 0xFC),
    "IAU.ADD24,BRU": (16, 0x3CAE),
    "IAU.ADD24,PEU": (8, 0xBD),
    "CMU,LSU0,IAU.ADD24": (16, 0xE82E),
    "CMU,LSU0.LDO32,IAU.ADD24": (16, 0xF82E),
    "CMU,LSU1,IAU.ADD24": (16, 0xE26E),
    "CMU,SAU,IAU.ADD24": (16, 0xF84E),
    "CMU,IAU.ADD24,BRU": (16, 0x3EAE),
    "CMU,IAU.ADD24,PEU": (16, 0x8EAE),
    "LSU0,LSU1,IAU.ADD24": (16, 0xE85E),
    "LSU0,SAU,IAU.ADD24": (16, 0xF89E),
    "LSU0,IAU.ADD24,BRU": (16, 0xF2CE),
    "LSU0,IAU.ADD24,PEU": (16, 0xB2DE),
    "LSU0.LDO32,LSU1,IAU.ADD24": (16, 0xEC5E),
    "LSU0.LDO32,SAU,IAU.ADD24": (16, 0xFC9E),
    "LSU0.LDO32,IAU.ADD24,BRU": (16, 0xF3CE),
    "LSU0.LDO32,IAU.ADD24,PEU": (16, 0xB3DE),
    "LSU1,SAU,IAU.ADD24": (16, 0xF8BE),
    "LSU1,IAU.ADD24,BRU": (16, 0xF8CE),
    "LSU1,IAU.ADD24,PEU": (16, 0xB8DE),
    "SAU,IAU.ADD24,BRU": (24, 0x3F000F),
    "SAU,IAU.ADD24,PEU": (16, 0xBCEE),
    "IAU.ADD24,BRU,PEU": (16, 0xBCAE),
    "CMU,LSU0,LSU1,IAU.ADD24": (16, 0xEA6E),
    "CMU,LSU0,SAU,IAU.ADD24": (16, 0xFA9E),
    "CMU,LSU0,IAU.ADD24,BRU": (24, 0x3C280F),
    "CMU,LSU0,IAU.ADD24,PEU": (24, 0x8C280F),
    "CMU,LSU0.LDO32,LSU1,IAU.ADD24": (16, 0xEE6E),
    "CMU,LSU0.LDO32,SAU,IAU.ADD24": (16, 0xFE9E),
    "CMU,LSU0.LDO32,IAU.ADD24,BRU": (24, 0x3C380F),
    "CMU,LSU0.LDO32,IAU.ADD24,PEU": (24, 0x8C380F),
    "CMU,LSU1,SAU,IAU.ADD24": (24, 0xF880F),
    "CMU,LSU1,IAU.ADD24,BRU": (24, 0x3C880F),
    "CMU,LSU1,IAU.ADD24,PEU": (24, 0x8C880F),
    "CMU,SAU,IAU.ADD24,BRU": (24, 0x3F080F),
    "CMU,SAU,IAU.ADD24,PEU": (24, 0x8F080F),
    "CMU,IAU.ADD24,BRU,PEU": (16, 0xBEAE),
    "LSU0,LSU1,SAU,IAU.ADD24": (16, 0xFABE),
    "LSU0,LSU1,IAU.ADD24,BRU": (16, 0xFACE),
    "LSU0,LSU1,IAU.ADD24,PEU": (16, 0xBADE),
    "LSU0,SAU,IAU.ADD24,BRU": (24, 0x3F200F),
    "LSU0,SAU,IAU.ADD24,PEU": (16, 0xBEEE),
    "LSU0,IAU.ADD24,BRU,PEU": (24, 0xBC200F),
    "LSU0.LDO32,LSU1,SAU,IAU.ADD24": (16, 0xFBBE),
    "LSU0.LDO32,LSU1,IAU.ADD24,BRU": (16, 0xFBCE),
    "LSU0.LDO32,LSU1,IAU.ADD24,PEU": (16, 0xBBDE),
    "LSU0.LDO32,SAU,IAU.ADD24,BRU": (24, 0x3F300F),
    "LSU0.LDO32,SAU,IAU.ADD24,PEU": (16, 0xBFEE),
    "LSU0.LDO32,IAU.ADD24,BRU,PEU": (24, 0xBC300F),
    "LSU1,SAU,IAU.ADD24,BRU": (24, 0x3F800F),
    "LSU1,SAU,IAU.ADD24,PEU": (24, 0x8F800F),
    "LSU1,IAU.ADD24,BRU,PEU": (24, 0xBC800F),
    "SAU,IAU.ADD24,BRU,PEU": (24, 0xBF000F),
    "CMU,LSU0,LSU1,IAU.ADD24,PEU": (24, 0x8CA80F),
    "CMU,LSU0,SAU,IAU.ADD24,PEU": (24, 0x8F280F),
    "CMU,LSU0,IAU.ADD24,BRU,PEU": (24, 0xBC280F),
    "CMU,LSU1,SAU,IAU.ADD24,PEU": (24, 0x8F880F),
    "CMU,LSU1,IAU.ADD24,BRU,PEU": (24, 0xBC880F),
    "CMU,SAU,IAU.ADD24,BRU,PEU": (24, 0xBF080F),
    "LSU0,LSU1,SAU,IAU.ADD24,PEU": (24, 0x8FA00F),
    "LSU0,LSU1,IAU.ADD24,BRU,PEU": (24, 0xBCA00F),
    "LSU0,SAU,IAU.ADD24,BRU,PEU": (24, 0xBF200F),
    "LSU1,SAU,IAU.ADD24,BRU,PEU": (24, 0xBF800F),
    "CMU.CMZ16": (8, 0x41),
    "CMU.CMZ16,LSU0": (8, 0x94),
    "CMU.CMZ16,LSU1": (16, 0x840E),
    "CMU.CMZ16,SAU": (16, 0xC43E),
    "CMU.CMZ16,IAU": (8, 0x96),
    "CMU.CMZ16,PEU": (8, 0x98),
    "CMU.CMZ16,LSU0,LSU1": (16, 0xA40E),
    "CMU.CMZ16,LSU0,SAU": (16, 0xE43E),
    "CMU.CMZ16,LSU0,IAU": (16, 0xA42E),
    "CMU.CMZ16,LSU0,PEU": (16, 0xA41E),
    "CMU.CMZ16,LSU1,SAU": (16, 0xE18E),
    "CMU.CMZ16,LSU1,IAU": (16, 0xA16E),
    "CMU.CMZ16,LSU1,PEU": (16, 0xA17E),
    "CMU.CMZ16,SAU,IAU": (16, 0xB44E),
    "CMU.CMZ16,SAU,PEU": (24, 0x83040F),
    "CMU.CMZ16,IAU,PEU": (16, 0x89AE),
    "CMU.CMZ16,LSU0,LSU1,SAU": (16, 0xE98E),
    "CMU.CMZ16,LSU0,LSU1,IAU": (16, 0xA96E),
    "CMU.CMZ16,LSU0,LSU1,PEU": (16, 0xA97E),
    "CMU.CMZ16,LSU0,SAU,IAU": (16, 0xB99E),
    "CMU.CMZ16,LSU0,SAU,PEU": (24, 0x83240F),
    "CMU.CMZ16,LSU0,IAU,PEU": (24, 0x88240F),
    "CMU.CMZ16,LSU1,SAU,IAU": (24, 0xB840F),
    "CMU.CMZ16,LSU1,SAU,PEU": (24, 0x83840F),
    "CMU.CMZ16,LSU1,IAU,PEU": (24, 0x88840F),
    "CMU.CMZ16,SAU,IAU,PEU": (24, 0x8B040F),
    "CMU.CMZ16,LSU0,LSU1,SAU,PEU": (24, 0x83A40F),
    "CMU.CMZ16,LSU0,LSU1,IAU,PEU": (24, 0x88A40F),
    "CMU.CMZ16,LSU0,SAU,IAU,PEU": (24, 0x8B240F),
    "CMU.CMZ16,LSU1,SAU,IAU,PEU": (24, 0x8B840F),
    "CMU.CMZ16,BRU": (8, 0xD7),
    "CMU.CMZ16,LSU0,BRU": (24, 0x30240F),
    "CMU.CMZ16,LSU1,BRU": (24, 0x30840F),
    "CMU.CMZ16,SAU,BRU": (24, 0x33040F),
    "CMU.CMZ16,IAU,BRU": (16, 0x39AE),
    "CMU.CMZ16,BRU,PEU": (16, 0xB1AE),
    "CMU.CMZ16,LSU0,LSU1,BRU": (24, 0x30A40F),
    "CMU.CMZ16,LSU0,SAU,BRU": (24, 0x33240F),
    "CMU.CMZ16,LSU0,IAU,BRU": (24, 0x38240F),
    "CMU.CMZ16,LSU0,BRU,PEU": (24, 0xB0240F),
    "CMU.CMZ16,LSU1,SAU,BRU": (24, 0x33840F),
    "CMU.CMZ16,LSU1,IAU,BRU": (24, 0x38840F),
    "CMU.CMZ16,LSU1,BRU,PEU": (24, 0xB0840F),
    "CMU.CMZ16,SAU,IAU,BRU": (24, 0x3B040F),
    "CMU.CMZ16,SAU,BRU,PEU": (24, 0xB3040F),
    "CMU.CMZ16,IAU,BRU,PEU": (16, 0xB9AE),
    "CMU.CMZ16,LSU0,LSU1,BRU,PEU": (24, 0xB0A40F),
    "CMU.CMZ16,LSU0,SAU,BRU,PEU": (24, 0xB3240F),
    "CMU.CMZ16,LSU0,IAU,BRU,PEU": (24, 0xB8240F),
    "CMU.CMZ16,LSU1,SAU,BRU,PEU": (24, 0xB3840F),
    "CMU.CMZ16,LSU1,IAU,BRU,PEU": (24, 0xB8840F),
    "CMU.CMZ16,SAU,IAU,BRU,PEU": (24, 0xBB040F),
    "CMU.CMZ16,LSU0.LDO32": (8, 0xD4),
    "CMU.CMZ16,LSU0.LDO32,LSU1": (16, 0xB40E),
    "CMU.CMZ16,LSU0.LDO32,SAU": (16, 0xF43E),
    "CMU.CMZ16,LSU0.LDO32,IAU": (16, 0xB42E),
    "CMU.CMZ16,LSU0.LDO32,BRU": (24, 0x30340F),
    "CMU.CMZ16,LSU0.LDO32,PEU": (16, 0xB41E),
    "CMU.CMZ16,LSU0.LDO32,LSU1,SAU": (16, 0xED8E),
    "CMU.CMZ16,LSU0.LDO32,LSU1,IAU": (16, 0xAD6E),
    "CMU.CMZ16,LSU0.LDO32,LSU1,BRU": (24, 0x30B40F),
    "CMU.CMZ16,LSU0.LDO32,LSU1,PEU": (16, 0xAD7E),
    "CMU.CMZ16,LSU0.LDO32,SAU,IAU": (16, 0xBD9E),
    "CMU.CMZ16,LSU0.LDO32,SAU,BRU": (24, 0x33340F),
    "CMU.CMZ16,LSU0.LDO32,SAU,PEU": (24, 0x83340F),
    "CMU.CMZ16,LSU0.LDO32,IAU,BRU": (24, 0x38340F),
    "CMU.CMZ16,LSU0.LDO32,IAU,PEU": (24, 0x88340F),
    "CMU.CMZ16,LSU0.LDO32,BRU,PEU": (24, 0xB0340F),
    "CMU.CMZ16,LSU0.LDO32,LSU1,SAU,PEU": (24, 0x83B40F),
    "CMU.CMZ16,LSU0.LDO32,LSU1,IAU,PEU": (24, 0x88B40F),
    "CMU.CMZ16,LSU0.LDO32,LSU1,BRU,PEU": (24, 0xB0B40F),
    "CMU.CMZ16,LSU0.LDO32,SAU,IAU,PEU": (24, 0x8B340F),
    "CMU.CMZ16,LSU0.LDO32,SAU,BRU,PEU": (24, 0xB3340F),
    "CMU.CMZ16,LSU0.LDO32,IAU,BRU,PEU": (24, 0xB8340F),
    "CMU.CMZ16,IAU.ADD24": (8, 0xD6),
    "CMU.CMZ16,LSU0,IAU.ADD24": (16, 0xE42E),
    "CMU.CMZ16,LSU0.LDO32,IAU.ADD24": (16, 0xF42E),
    "CMU.CMZ16,LSU1,IAU.ADD24": (16, 0xE16E),
    "CMU.CMZ16,SAU,IAU.ADD24": (16, 0xF44E),
    "CMU.CMZ16,IAU.ADD24,BRU": (16, 0x3DAE),
    "CMU.CMZ16,IAU.ADD24,PEU": (16, 0x8DAE),
    "CMU.CMZ16,LSU0,LSU1,IAU.ADD24": (16, 0xE96E),
    "CMU.CMZ16,LSU0,SAU,IAU.ADD24": (16, 0xF99E),
    "CMU.CMZ16,LSU0,IAU.ADD24,BRU": (24, 0x3C240F),
    "CMU.CMZ16,LSU0,IAU.ADD24,PEU": (24, 0x8C240F),
    "CMU.CMZ16,LSU0.LDO32,LSU1,IAU.ADD24": (16, 0xED6E),
    "CMU.CMZ16,LSU0.LDO32,SAU,IAU.ADD24": (16, 0xFD9E),
    "CMU.CMZ16,LSU0.LDO32,IAU.ADD24,BRU": (24, 0x3C340F),
    "CMU.CMZ16,LSU0.LDO32,IAU.ADD24,PEU": (24, 0x8C340F),
    "CMU.CMZ16,LSU1,SAU,IAU.ADD24": (24, 0xF840F),
    "CMU.CMZ16,LSU1,IAU.ADD24,BRU": (24, 0x3C840F),
    "CMU.CMZ16,LSU1,IAU.ADD24,PEU": (24, 0x8C840F),
    "CMU.CMZ16,SAU,IAU.ADD24,BRU": (24, 0x3F040F),
    "CMU.CMZ16,SAU,IAU.ADD24,PEU": (24, 0x8F040F),
    "CMU.CMZ16,IAU.ADD24,BRU,PEU": (16, 0xBDAE),
    "CMU.CMZ16,LSU0,LSU1,IAU.ADD24,PEU": (24, 0x8CA40F),
    "CMU.CMZ16,LSU0,SAU,IAU.ADD24,PEU": (24, 0x8F240F),
    "CMU.CMZ16,LSU0,IAU.ADD24,BRU,PEU": (24, 0xBC240F),
    "CMU.CMZ16,LSU0.LDO32,LSU1,IAU.ADD24,PEU": (24, 0x8CB40F),
    "CMU.CMZ16,LSU0.LDO32,SAU,IAU.ADD24,PEU": (24, 0x8F340F),
    "CMU.CMZ16,LSU0.LDO32,IAU.ADD24,BRU,PEU": (24, 0xBC340F),
    "CMU.CMZ16,LSU1,SAU,IAU.ADD24,PEU": (24, 0x8F840F),
    "CMU.CMZ16,LSU1,IAU.ADD24,BRU,PEU": (24, 0xBC840F),
    "CMU.CMZ16,SAU,IAU.ADD24,BRU,PEU": (24, 0xBF040F),
    "PEU.PCCX12": (8, 0xC5),
    "CMU,PEU.PCCX12": (8, 0xE8),
    "LSU0,PEU.PCCX12": (8, 0xEB),
    "LSU1,PEU.PCCX12": (16, 0xE07E),
    "SAU,PEU.PCCX12": (16, 0xCCEE),
    "IAU,PEU.PCCX12": (8, 0xED),
    "CMU,LSU0,PEU.PCCX12": (16, 0xE81E),
    "CMU,LSU1,PEU.PCCX12": (16, 0xE27E),
    "CMU,SAU,PEU.PCCX12": (24, 0xC3080F),
    "CMU,IAU,PEU.PCCX12": (16, 0xCAAE),
    "LSU0,LSU1,PEU.PCCX12": (16, 0xE87E),
    "LSU0,SAU,PEU.PCCX12": (16, 0xCEEE),
    "LSU0,IAU,PEU.PCCX12": (16, 0xE2DE),
    "LSU1,SAU,PEU.PCCX12": (24, 0xC3800F),
    "LSU1,IAU,PEU.PCCX12": (16, 0xE8DE),
    "SAU,IAU,PEU.PCCX12": (16, 0xECEE),
    "CMU,LSU0,LSU1,PEU.PCCX12": (16, 0xEA7E),
    "CMU,LSU0,SAU,PEU.PCCX12": (24, 0xC3280F),
    "CMU,LSU0,IAU,PEU.PCCX12": (24, 0xC8280F),
    "CMU,LSU1,SAU,PEU.PCCX12": (24, 0xC3880F),
    "CMU,LSU1,IAU,PEU.PCCX12": (24, 0xC8880F),
    "CMU,SAU,IAU,PEU.PCCX12": (24, 0xCB080F),
    "LSU0,LSU1,SAU,PEU.PCCX12": (24, 0xC3A00F),
    "LSU0,LSU1,IAU,PEU.PCCX12": (16, 0xEADE),
    "LSU0,SAU,IAU,PEU.PCCX12": (16, 0xEEEE),
    "LSU1,SAU,IAU,PEU.PCCX12": (24, 0xCB800F),
    "CMU,LSU0,LSU1,IAU,PEU.PCCX12": (24, 0xC8A80F),
    "CMU,LSU0,SAU,IAU,PEU.PCCX12": (24, 0xCB280F),
    "CMU,LSU1,SAU,IAU,PEU.PCCX12": (24, 0xCB880F),
    "LSU0,LSU1,SAU,IAU,PEU.PCCX12": (24, 0xCBA00F),
    "BRU,PEU.PCCX12": (8, 0xF5),
    "CMU,BRU,PEU.PCCX12": (16, 0xF2AE),
    "LSU0,BRU,PEU.PCCX12": (24, 0xF0200F),
    "LSU1,BRU,PEU.PCCX12": (24, 0xF0800F),
    "SAU,BRU,PEU.PCCX12": (24, 0xF3000F),
    "IAU,BRU,PEU.PCCX12": (16, 0xF8AE),
    "CMU,LSU0,BRU,PEU.PCCX12": (24, 0xF0280F),
    "CMU,LSU1,BRU,PEU.PCCX12": (24, 0xF0880F),
    "CMU,SAU,BRU,PEU.PCCX12": (24, 0xF3080F),
    "CMU,IAU,BRU,PEU.PCCX12": (16, 0xFAAE),
    "LSU0,LSU1,BRU,PEU.PCCX12": (24, 0xF0A00F),
    "LSU0,SAU,BRU,PEU.PCCX12": (24, 0xF3200F),
    "LSU0,IAU,BRU,PEU.PCCX12": (24, 0xF8200F),
    "LSU1,SAU,BRU,PEU.PCCX12": (24, 0xF3800F),
    "LSU1,IAU,BRU,PEU.PCCX12": (24, 0xF8800F),
    "SAU,IAU,BRU,PEU.PCCX12": (24, 0xFB000F),
    "CMU,LSU0,IAU,BRU,PEU.PCCX12": (24, 0xF8280F),
    "CMU,LSU1,IAU,BRU,PEU.PCCX12": (24, 0xF8880F),
    "CMU,SAU,IAU,BRU,PEU.PCCX12": (24, 0xFB080F),
    "LSU0,LSU1,IAU,BRU,PEU.PCCX12": (24, 0xF8A00F),
    "LSU0,SAU,IAU,BRU,PEU.PCCX12": (24, 0xFB200F),
    "LSU1,SAU,IAU,BRU,PEU.PCCX12": (24, 0xFB800F),
    "LSU0.LDO32,PEU.PCCX12": (8, 0xFB),
    "CMU,LSU0.LDO32,PEU.PCCX12": (16, 0xF81E),
    "LSU0.LDO32,LSU1,PEU.PCCX12": (16, 0xEC7E),
    "LSU0.LDO32,SAU,PEU.PCCX12": (16, 0xCFEE),
    "LSU0.LDO32,IAU,PEU.PCCX12": (16, 0xE3DE),
    "LSU0.LDO32,BRU,PEU.PCCX12": (24, 0xF0300F),
    "CMU,LSU0.LDO32,LSU1,PEU.PCCX12": (16, 0xEE7E),
    "CMU,LSU0.LDO32,SAU,PEU.PCCX12": (24, 0xC3380F),
    "CMU,LSU0.LDO32,IAU,PEU.PCCX12": (24, 0xC8380F),
    "CMU,LSU0.LDO32,BRU,PEU.PCCX12": (24, 0xF0380F),
    "LSU0.LDO32,LSU1,SAU,PEU.PCCX12": (24, 0xC3B00F),
    "LSU0.LDO32,LSU1,IAU,PEU.PCCX12": (16, 0xEBDE),
    "LSU0.LDO32,LSU1,BRU,PEU.PCCX12": (24, 0xF0B00F),
    "LSU0.LDO32,SAU,IAU,PEU.PCCX12": (16, 0xEFEE),
    "LSU0.LDO32,SAU,BRU,PEU.PCCX12": (24, 0xF3300F),
    "LSU0.LDO32,IAU,BRU,PEU.PCCX12": (24, 0xF8300F),
    "IAU.ADD24,PEU.PCCX12": (8, 0xFD),
    "CMU,IAU.ADD24,PEU.PCCX12": (16, 0xCEAE),
    "LSU0,IAU.ADD24,PEU.PCCX12": (16, 0xF2DE),
    "LSU0.LDO32,IAU.ADD24,PEU.PCCX12": (16, 0xF3DE),
    "LSU1,IAU.ADD24,PEU.PCCX12": (16, 0xF8DE),
    "SAU,IAU.ADD24,PEU.PCCX12": (16, 0xFCEE),
    "IAU.ADD24,BRU,PEU.PCCX12": (16, 0xFCAE),
    "CMU,LSU0,IAU.ADD24,PEU.PCCX12": (24, 0xCC280F),
    "CMU,LSU0.LDO32,IAU.ADD24,PEU.PCCX12": (24, 0xCC380F),
    "CMU,LSU1,IAU.ADD24,PEU.PCCX12": (24, 0xCC880F),
    "CMU,SAU,IAU.ADD24,PEU.PCCX12": (24, 0xCF080F),
    "CMU,IAU.ADD24,BRU,PEU.PCCX12": (16, 0xFEAE),
    "LSU0,LSU1,IAU.ADD24,PEU.PCCX12": (16, 0xFADE),
    "LSU0,SAU,IAU.ADD24,PEU.PCCX12": (16, 0xFEEE),
    "LSU0,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFC200F),
    "LSU0.LDO32,LSU1,IAU.ADD24,PEU.PCCX12": (16, 0xFBDE),
    "LSU0.LDO32,SAU,IAU.ADD24,PEU.PCCX12": (16, 0xFFEE),
    "LSU0.LDO32,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFC300F),
    "LSU1,SAU,IAU.ADD24,PEU.PCCX12": (24, 0xCF800F),
    "LSU1,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFC800F),
    "SAU,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFF000F),
    "CMU.CMZ16,PEU.PCCX12": (8, 0xD8),
    "CMU.CMZ16,LSU0,PEU.PCCX12": (16, 0xE41E),
    "CMU.CMZ16,LSU1,PEU.PCCX12": (16, 0xE17E),
    "CMU.CMZ16,SAU,PEU.PCCX12": (24, 0xC3040F),
    "CMU.CMZ16,IAU,PEU.PCCX12": (16, 0xC9AE),
    "CMU.CMZ16,LSU0,LSU1,PEU.PCCX12": (16, 0xE97E),
    "CMU.CMZ16,LSU0,SAU,PEU.PCCX12": (24, 0xC3240F),
    "CMU.CMZ16,LSU0,IAU,PEU.PCCX12": (24, 0xC8240F),
    "CMU.CMZ16,LSU1,SAU,PEU.PCCX12": (24, 0xC3840F),
    "CMU.CMZ16,LSU1,IAU,PEU.PCCX12": (24, 0xC8840F),
    "CMU.CMZ16,SAU,IAU,PEU.PCCX12": (24, 0xCB040F),
    "CMU.CMZ16,LSU0,LSU1,SAU,PEU.PCCX12": (24, 0xC3A40F),
    "CMU.CMZ16,LSU0,LSU1,IAU,PEU.PCCX12": (24, 0xC8A40F),
    "CMU.CMZ16,LSU0,SAU,IAU,PEU.PCCX12": (24, 0xCB240F),
    "CMU.CMZ16,LSU1,SAU,IAU,PEU.PCCX12": (24, 0xCB840F),
    "CMU.CMZ16,BRU,PEU.PCCX12": (16, 0xF1AE),
    "CMU.CMZ16,LSU0,BRU,PEU.PCCX12": (24, 0xF0240F),
    "CMU.CMZ16,LSU1,BRU,PEU.PCCX12": (24, 0xF0840F),
    "CMU.CMZ16,SAU,BRU,PEU.PCCX12": (24, 0xF3040F),
    "CMU.CMZ16,IAU,BRU,PEU.PCCX12": (16, 0xF9AE),
    "CMU.CMZ16,LSU0,LSU1,BRU,PEU.PCCX12": (24, 0xF0A40F),
    "CMU.CMZ16,LSU0,SAU,BRU,PEU.PCCX12": (24, 0xF3240F),
    "CMU.CMZ16,LSU0,IAU,BRU,PEU.PCCX12": (24, 0xF8240F),
    "CMU.CMZ16,LSU1,SAU,BRU,PEU.PCCX12": (24, 0xF3840F),
    "CMU.CMZ16,LSU1,IAU,BRU,PEU.PCCX12": (24, 0xF8840F),
    "CMU.CMZ16,SAU,IAU,BRU,PEU.PCCX12": (24, 0xFB040F),
    "CMU.CMZ16,LSU0.LDO32,PEU.PCCX12": (16, 0xF41E),
    "CMU.CMZ16,LSU0.LDO32,LSU1,PEU.PCCX12": (16, 0xED7E),
    "CMU.CMZ16,LSU0.LDO32,SAU,PEU.PCCX12": (24, 0xC3340F),
    "CMU.CMZ16,LSU0.LDO32,IAU,PEU.PCCX12": (24, 0xC8340F),
    "CMU.CMZ16,LSU0.LDO32,BRU,PEU.PCCX12": (24, 0xF0340F),
    "CMU.CMZ16,LSU0.LDO32,LSU1,IAU,PEU.PCCX12": (24, 0xC8B40F),
    "CMU.CMZ16,LSU0.LDO32,SAU,IAU,PEU.PCCX12": (24, 0xCB340F),
    "CMU.CMZ16,LSU0.LDO32,IAU,BRU,PEU.PCCX12": (24, 0xF8340F),
    "CMU.CMZ16,IAU.ADD24,PEU.PCCX12": (16, 0xCDAE),
    "CMU.CMZ16,LSU0,IAU.ADD24,PEU.PCCX12": (24, 0xCC240F),
    "CMU.CMZ16,LSU0.LDO32,IAU.ADD24,PEU.PCCX12": (24, 0xCC340F),
    "CMU.CMZ16,LSU1,IAU.ADD24,PEU.PCCX12": (24, 0xCC840F),
    "CMU.CMZ16,SAU,IAU.ADD24,PEU.PCCX12": (24, 0xCF040F),
    "CMU.CMZ16,IAU.ADD24,BRU,PEU.PCCX12": (16, 0xFDAE),
    "CMU.CMZ16,LSU0,LSU1,IAU.ADD24,PEU.PCCX12": (24, 0xCCA40F),
    "CMU.CMZ16,LSU0,SAU,IAU.ADD24,PEU.PCCX12": (24, 0xCF240F),
    "CMU.CMZ16,LSU0,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFC240F),
    "CMU.CMZ16,LSU1,SAU,IAU.ADD24,PEU.PCCX12": (24, 0xCF840F),
    "CMU.CMZ16,LSU1,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFC840F),
    "CMU.CMZ16,SAU,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFF040F),
    "LSU1.STO32": (8, 0xC9),
    "CMU,LSU1.STO32": (16, 0xC80E),
    "LSU0,LSU1.STO32": (8, 0xE9),
    "LSU1.STO32,SAU": (16, 0xF08E),
    "LSU1.STO32,IAU": (16, 0xB05E),
    "LSU1.STO32,PEU": (16, 0xB07E),
    "CMU,LSU0,LSU1.STO32": (16, 0xE80E),
    "CMU,LSU1.STO32,SAU": (16, 0xF28E),
    "CMU,LSU1.STO32,IAU": (16, 0xB26E),
    "CMU,LSU1.STO32,PEU": (16, 0xB27E),
    "LSU0,LSU1.STO32,SAU": (16, 0xF88E),
    "LSU0,LSU1.STO32,IAU": (16, 0xB85E),
    "LSU0,LSU1.STO32,PEU": (16, 0xB87E),
    "LSU1.STO32,SAU,IAU": (16, 0xBCBE),
    "LSU1.STO32,SAU,PEU": (24, 0x83C00F),
    "LSU1.STO32,IAU,PEU": (16, 0xACDE),
    "CMU,LSU0,LSU1.STO32,SAU": (16, 0xFA8E),
    "CMU,LSU0,LSU1.STO32,IAU": (16, 0xBA6E),
    "CMU,LSU0,LSU1.STO32,PEU": (16, 0xBA7E),
    "CMU,LSU1.STO32,SAU,IAU": (24, 0xBC80F),
    "CMU,LSU1.STO32,SAU,PEU": (24, 0x83C80F),
    "CMU,LSU1.STO32,IAU,PEU": (24, 0x88C80F),
    "LSU0,LSU1.STO32,SAU,IAU": (16, 0xBEBE),
    "LSU0,LSU1.STO32,SAU,PEU": (24, 0x83E00F),
    "LSU0,LSU1.STO32,IAU,PEU": (16, 0xAEDE),
    "LSU1.STO32,SAU,IAU,PEU": (24, 0x8BC00F),
    "LSU1.STO32,BRU": (16, 0xCCCE),
    "CMU,LSU1.STO32,BRU": (24, 0x30C80F),
    "LSU0,LSU1.STO32,BRU": (16, 0xCECE),
    "LSU1.STO32,SAU,BRU": (24, 0x33C00F),
    "LSU1.STO32,IAU,BRU": (16, 0xECCE),
    "LSU1.STO32,BRU,PEU": (24, 0xB0C00F),
    "CMU,LSU0,LSU1.STO32,BRU": (24, 0x30E80F),
    "CMU,LSU1.STO32,SAU,BRU": (24, 0x33C80F),
    "CMU,LSU1.STO32,IAU,BRU": (24, 0x38C80F),
    "CMU,LSU1.STO32,BRU,PEU": (24, 0xB0C80F),
    "LSU0,LSU1.STO32,SAU,BRU": (24, 0x33E00F),
    "LSU0,LSU1.STO32,IAU,BRU": (16, 0xEECE),
    "LSU0,LSU1.STO32,BRU,PEU": (24, 0xB0E00F),
    "LSU1.STO32,SAU,IAU,BRU": (24, 0x3BC00F),
    "LSU1.STO32,SAU,BRU,PEU": (24, 0xB3C00F),
    "LSU1.STO32,IAU,BRU,PEU": (24, 0xB8C00F),
    "LSU0.LDO32,LSU1.STO32": (8, 0xF9),
    "CMU,LSU0.LDO32,LSU1.STO32": (16, 0xF80E),
    "LSU0.LDO32,LSU1.STO32,SAU": (16, 0xFC8E),
    "LSU0.LDO32,LSU1.STO32,IAU": (16, 0xBC5E),
    "LSU0.LDO32,LSU1.STO32,BRU": (16, 0xCFCE),
    "LSU0.LDO32,LSU1.STO32,PEU": (16, 0xBC7E),
    "CMU,LSU0.LDO32,LSU1.STO32,SAU": (16, 0xFE8E),
    "CMU,LSU0.LDO32,LSU1.STO32,IAU": (16, 0xBE6E),
    "CMU,LSU0.LDO32,LSU1.STO32,PEU": (16, 0xBE7E),
    "LSU0.LDO32,LSU1.STO32,SAU,IAU": (16, 0xBFBE),
    "LSU0.LDO32,LSU1.STO32,SAU,PEU": (24, 0x83F00F),
    "LSU0.LDO32,LSU1.STO32,IAU,BRU": (16, 0xEFCE),
    "LSU0.LDO32,LSU1.STO32,IAU,PEU": (16, 0xAFDE),
    "LSU0.LDO32,LSU1.STO32,BRU,PEU": (24, 0xB0F00F),
    "LSU1.STO32,IAU.ADD24": (16, 0xF05E),
    "CMU,LSU1.STO32,IAU.ADD24": (16, 0xF26E),
    "LSU0,LSU1.STO32,IAU.ADD24": (16, 0xF85E),
    "LSU0.LDO32,LSU1.STO32,IAU.ADD24": (16, 0xFC5E),
    "LSU1.STO32,SAU,IAU.ADD24": (16, 0xFCBE),
    "LSU1.STO32,IAU.ADD24,BRU": (16, 0xFCCE),
    "LSU1.STO32,IAU.ADD24,PEU": (16, 0xBCDE),
    "CMU,LSU0,LSU1.STO32,IAU.ADD24": (16, 0xFA6E),
    "CMU,LSU0.LDO32,LSU1.STO32,IAU.ADD24": (16, 0xFE6E),
    "CMU,LSU1.STO32,SAU,IAU.ADD24": (24, 0xFC80F),
    "CMU,LSU1.STO32,IAU.ADD24,BRU": (24, 0x3CC80F),
    "CMU,LSU1.STO32,IAU.ADD24,PEU": (24, 0x8CC80F),
    "LSU0,LSU1.STO32,SAU,IAU.ADD24": (16, 0xFEBE),
    "LSU0,LSU1.STO32,IAU.ADD24,BRU": (16, 0xFECE),
    "LSU0,LSU1.STO32,IAU.ADD24,PEU": (16, 0xBEDE),
    "LSU0.LDO32,LSU1.STO32,SAU,IAU.ADD24": (16, 0xFFBE),
    "LSU0.LDO32,LSU1.STO32,IAU.ADD24,BRU": (16, 0xFFCE),
    "LSU0.LDO32,LSU1.STO32,IAU.ADD24,PEU": (16, 0xBFDE),
    "LSU1.STO32,SAU,IAU.ADD24,BRU": (24, 0x3FC00F),
    "LSU1.STO32,SAU,IAU.ADD24,PEU": (24, 0x8FC00F),
    "LSU1.STO32,IAU.ADD24,BRU,PEU": (24, 0xBCC00F),
    "CMU.CMZ16,LSU1.STO32": (16, 0xC40E),
    "CMU.CMZ16,LSU0,LSU1.STO32": (16, 0xE40E),
    "CMU.CMZ16,LSU1.STO32,SAU": (16, 0xF18E),
    "CMU.CMZ16,LSU1.STO32,IAU": (16, 0xB16E),
    "CMU.CMZ16,LSU1.STO32,PEU": (16, 0xB17E),
    "CMU.CMZ16,LSU0,LSU1.STO32,SAU": (16, 0xF98E),
    "CMU.CMZ16,LSU0,LSU1.STO32,IAU": (16, 0xB96E),
    "CMU.CMZ16,LSU0,LSU1.STO32,PEU": (16, 0xB97E),
    "CMU.CMZ16,LSU1.STO32,SAU,IAU": (24, 0xBC40F),
    "CMU.CMZ16,LSU1.STO32,SAU,PEU": (24, 0x83C40F),
    "CMU.CMZ16,LSU1.STO32,IAU,PEU": (24, 0x88C40F),
    "CMU.CMZ16,LSU0,LSU1.STO32,SAU,PEU": (24, 0x83E40F),
    "CMU.CMZ16,LSU0,LSU1.STO32,IAU,PEU": (24, 0x88E40F),
    "CMU.CMZ16,LSU1.STO32,SAU,IAU,PEU": (24, 0x8BC40F),
    "CMU.CMZ16,LSU1.STO32,BRU": (24, 0x30C40F),
    "CMU.CMZ16,LSU0,LSU1.STO32,BRU": (24, 0x30E40F),
    "CMU.CMZ16,LSU1.STO32,SAU,BRU": (24, 0x33C40F),
    "CMU.CMZ16,LSU1.STO32,IAU,BRU": (24, 0x38C40F),
    "CMU.CMZ16,LSU1.STO32,BRU,PEU": (24, 0xB0C40F),
    "CMU.CMZ16,LSU0,LSU1.STO32,BRU,PEU": (24, 0xB0E40F),
    "CMU.CMZ16,LSU1.STO32,SAU,BRU,PEU": (24, 0xB3C40F),
    "CMU.CMZ16,LSU1.STO32,IAU,BRU,PEU": (24, 0xB8C40F),
    "CMU.CMZ16,LSU0.LDO32,LSU1.STO32": (16, 0xF40E),
    "CMU.CMZ16,LSU0.LDO32,LSU1.STO32,SAU": (16, 0xFD8E),
    "CMU.CMZ16,LSU0.LDO32,LSU1.STO32,IAU": (16, 0xBD6E),
    "CMU.CMZ16,LSU0.LDO32,LSU1.STO32,BRU": (24, 0x30F40F),
    "CMU.CMZ16,LSU0.LDO32,LSU1.STO32,PEU": (16, 0xBD7E),
    "CMU.CMZ16,LSU1.STO32,IAU.ADD24": (16, 0xF16E),
    "CMU.CMZ16,LSU0,LSU1.STO32,IAU.ADD24": (16, 0xF96E),
    "CMU.CMZ16,LSU0.LDO32,LSU1.STO32,IAU.ADD24": (16, 0xFD6E),
    "CMU.CMZ16,LSU1.STO32,SAU,IAU.ADD24": (24, 0xFC40F),
    "CMU.CMZ16,LSU1.STO32,IAU.ADD24,BRU": (24, 0x3CC40F),
    "CMU.CMZ16,LSU1.STO32,IAU.ADD24,PEU": (24, 0x8CC40F),
    "CMU.CMZ16,LSU0,LSU1.STO32,IAU.ADD24,PEU": (24, 0x8CE40F),
    "CMU.CMZ16,LSU1.STO32,SAU,IAU.ADD24,PEU": (24, 0x8FC40F),
    "CMU.CMZ16,LSU1.STO32,IAU.ADD24,BRU,PEU": (24, 0xBCC40F),
    "LSU1.STO32,PEU.PCCX12": (16, 0xF07E),
    "CMU,LSU1.STO32,PEU.PCCX12": (16, 0xF27E),
    "LSU0,LSU1.STO32,PEU.PCCX12": (16, 0xF87E),
    "LSU1.STO32,SAU,PEU.PCCX12": (24, 0xC3C00F),
    "LSU1.STO32,IAU,PEU.PCCX12": (16, 0xECDE),
    "CMU,LSU0,LSU1.STO32,PEU.PCCX12": (16, 0xFA7E),
    "CMU,LSU1.STO32,SAU,PEU.PCCX12": (24, 0xC3C80F),
    "CMU,LSU1.STO32,IAU,PEU.PCCX12": (24, 0xC8C80F),
    "LSU0,LSU1.STO32,SAU,PEU.PCCX12": (24, 0xC3E00F),
    "LSU0,LSU1.STO32,IAU,PEU.PCCX12": (16, 0xEEDE),
    "LSU1.STO32,SAU,IAU,PEU.PCCX12": (24, 0xCBC00F),
    "LSU1.STO32,BRU,PEU.PCCX12": (24, 0xF0C00F),
    "CMU,LSU1.STO32,BRU,PEU.PCCX12": (24, 0xF0C80F),
    "LSU0,LSU1.STO32,BRU,PEU.PCCX12": (24, 0xF0E00F),
    "LSU1.STO32,SAU,BRU,PEU.PCCX12": (24, 0xF3C00F),
    "LSU1.STO32,IAU,BRU,PEU.PCCX12": (24, 0xF8C00F),
    "LSU0.LDO32,LSU1.STO32,PEU.PCCX12": (16, 0xFC7E),
    "CMU,LSU0.LDO32,LSU1.STO32,PEU.PCCX12": (16, 0xFE7E),
    "LSU0.LDO32,LSU1.STO32,SAU,PEU.PCCX12": (24, 0xC3F00F),
    "LSU0.LDO32,LSU1.STO32,IAU,PEU.PCCX12": (16, 0xEFDE),
    "LSU0.LDO32,LSU1.STO32,BRU,PEU.PCCX12": (24, 0xF0F00F),
    "LSU1.STO32,IAU.ADD24,PEU.PCCX12": (16, 0xFCDE),
    "CMU,LSU1.STO32,IAU.ADD24,PEU.PCCX12": (24, 0xCCC80F),
    "LSU0,LSU1.STO32,IAU.ADD24,PEU.PCCX12": (16, 0xFEDE),
    "LSU0.LDO32,LSU1.STO32,IAU.ADD24,PEU.PCCX12": (16, 0xFFDE),
    "LSU1.STO32,SAU,IAU.ADD24,PEU.PCCX12": (24, 0xCFC00F),
    "LSU1.STO32,IAU.ADD24,BRU,PEU.PCCX12": (24, 0xFCC00F),
    "CMU.CMZ16,LSU1.STO32,PEU.PCCX12": (16, 0xF17E),
    "CMU.CMZ16,LSU0,LSU1.STO32,PEU.PCCX12": (16, 0xF97E),
    "CMU.CMZ16,LSU1.STO32,SAU,PEU.PCCX12": (24, 0xC3C40F),
    "CMU.CMZ16,LSU1.STO32,IAU,PEU.PCCX12": (24, 0xC8C40F),
    "CMU.CMZ16,LSU0,LSU1.STO32,IAU,PEU.PCCX12": (24, 0xC8E40F),
    "CMU.CMZ16,LSU1.STO32,SAU,IAU,PEU.PCCX12": (24, 0xCBC40F),
    "CMU.CMZ16,LSU1.STO32,BRU,PEU.PCCX12": (24, 0xF0C40F),
    "CMU.CMZ16,LSU1.STO32,IAU,BRU,PEU.PCCX12": (24, 0xF8C40F),
    "CMU.CMZ16,LSU0.LDO32,LSU1.STO32,PEU.PCCX12": (16, 0xFD7E),
    "CMU.CMZ16,LSU1.STO32,IAU.ADD24,PEU.PCCX12": (24, 0xCCC40F),
}
_PREDICATES = {"EQ": 1, "NEQ": 14, "LT": 4, "LTE": 5, "GT": 2, "GTE": 3}
_PCCX_PREDICATES = {**_PREDICATES, "NEQ": 6}


@dataclass(frozen=True)
class _Operation:
    unit: str
    value: int
    bits: int
    fixup: Fixup | None = None
    prefix_class: str | None = None


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


def _signed_immediate(text: str, bits: int, line: int) -> int:
    try:
        value = int(text, 0)
    except ValueError as error:
        raise AssemblyError(f"line {line}: expected signed {bits}-bit immediate, got {text!r}") from error
    if not -(1 << (bits - 1)) <= value < 1 << (bits - 1):
        raise AssemblyError(f"line {line}: {value} exceeds signed {bits}-bit immediate")
    return value & ((1 << bits) - 1)


def _operation(instruction: Instruction) -> _Operation:
    mnemonic, operands, line = instruction.mnemonic, instruction.operands, instruction.line
    unit = mnemonic.split(".")[0]
    if mnemonic == "BRU.BRA" and len(operands) == 1 and re.fullmatch(r"[A-Za-z_.$][A-Za-z_0-9.$]*", operands[0]):
        return _Operation(unit, 0, 24, Fixup(operands[0], 0, 0, 16, "R_SHAVE_PCREL16"))
    if mnemonic in ("LSU0.LDO.32", "LSU1.LDO.32", "LSU1.STO.32") and len(operands) == 3:
        register, base = (_register(op, line) for op in operands[:2])
        immediate = _signed_immediate(operands[2], 15, line)
        opcode, prefix_class = {
            "LSU0.LDO.32": (0x14002, "LSU0.LDO32"),
            "LSU1.STO.32": (0x14006, "LSU1.STO32"),
            "LSU1.LDO.32": (0x14002, "LSU1.STO32"),
        }[mnemonic]
        return _Operation(unit, opcode | register << 4 | base << 9 | immediate << 17, 32,
                          prefix_class=prefix_class)
    if mnemonic in ("LSU0.LD.32", "LSU0.CP.32") and len(operands) == 2:
        destination, source = (_register(op, line) for op in operands)
        opcode = {"LSU0.LD.32": 0x1000D, "LSU0.CP.32": 0x80007}[mnemonic]
        return _Operation(unit, opcode | destination << 4 | source << 9, 24)
    if mnemonic in ("LSU0.LDIL", "LSU1.LDIL") and len(operands) == 2:
        destination = _register(operands[0], line)
        immediate = _immediate(operands[1], 16, line)
        return _Operation(unit, 2 | destination << 3 | immediate << 8, 24)
    if mnemonic == "CMU.CMZ.I32" and len(operands) == 1:
        source = _register(operands[0], line)
        return _Operation(unit, source << 4, 16, prefix_class="CMU.CMZ16")
    if mnemonic in ("CMU.CMII.I32", "CMU.CMII.U32") and len(operands) == 2:
        left, right = (_register(op, line) for op in operands)
        signed = 0x10000 if mnemonic == "CMU.CMII.I32" else 0
        return _Operation(unit, signed | left << 4 | right << 9, 24)
    if mnemonic == "CMU.CP.32" and len(operands) == 2:
        destination, source = (_register(op, line) for op in operands)
        return _Operation(unit, 0x08000C | destination << 9 | source << 4, 24)
    if mnemonic == "IAU.INCS" and len(operands) == 2:
        register = _register(operands[0], line)
        immediate = _signed_immediate(operands[1], 14, line)
        return _Operation(unit, 3 | register << 5 | immediate << 10, 24,
                          prefix_class="IAU.ADD24")
    if mnemonic == "IAU.SHL" and len(operands) == 3:
        destination, source = (_register(op, line) for op in operands[:2])
        immediate = _immediate(operands[2], 5, line)
        return _Operation(unit, 0x80000C | destination << 10 | source << 5 | immediate << 15, 24,
                          prefix_class="IAU.ADD24")
    if mnemonic == "IAU.ADD" and len(operands) == 3:
        destination, left = (_register(op, line) for op in operands[:2])
        if re.fullmatch(r"[iI][0-9]+", operands[2]):
            right = _register(operands[2], line)
            selector = 0
        else:
            right = _immediate(operands[2], 8, line)
            selector = 1 << 23
        return _Operation(unit, selector | destination << 10 | left << 5 | right << 15, 24,
                          prefix_class="IAU.ADD24")
    if mnemonic in ("IAU.XOR", "IAU.AND", "IAU.OR", "IAU.LMULL") and len(operands) == 3:
        destination, left, right = (_register(op, line) for op in operands)
        opcode = {"IAU.XOR": 0x12, "IAU.AND": 0x10, "IAU.OR": 0x11, "IAU.LMULL": 0x04}[mnemonic]
        return _Operation(unit, opcode | destination << 10 | left << 5 | right << 15, 20)
    if mnemonic == "SAU.ADD.F32" and len(operands) == 3:
        destination, left, right = (_register(op, line) for op in operands)
        return _Operation(unit, 0x200000 | destination << 10 | left << 5 | right << 15, 24)
    if mnemonic == "SAU.ADD.I32" and len(operands) == 3:
        destination, source = (_register(op, line) for op in operands[:2])
        immediate = _immediate(operands[2], 5, line)
        return _Operation(unit, 0x100000 | destination << 10 | source << 5 | immediate << 15, 24)
    if mnemonic == "PEU.PCCX" and len(operands) == 2 and operands[0].upper() in _PCCX_PREDICATES:
        condition = _PCCX_PREDICATES[operands[0].upper()]
        immediate = _immediate(operands[1], 6, line)
        return _Operation(unit, 1 | condition << 2 | immediate << 6, 12, prefix_class="PEU.PCCX12")
    if mnemonic == "PEU.PC1C" and len(operands) == 1 and operands[0].upper() in _PREDICATES:
        return _Operation(unit, 0xB | _PREDICATES[operands[0].upper()] << 4, 8)
    raise AssemblyError(f"line {line}: unsupported instruction form {mnemonic} {' '.join(operands)}")


def _branch_delay_span(following: Sequence[Packet]) -> int:
    slots = size = 0
    for packet in following:
        if any(op.mnemonic.startswith("BRU.") and op.mnemonic != "BRU.NOP" for op in packet.operations):
            raise AssemblyError("unmeasured control transfer in branch delay slots")
        data, _ = encode_packet_with_fixups(packet)
        first = packet.operations[0]
        count = int(first.operands[0], 0) if first.mnemonic == "NOP" and first.operands else 1
        if slots + count >= 6:
            return size + (1 if first.mnemonic == "NOP" else len(data))
        slots += count
        size += len(data)
    return 0


def encode_packet_with_fixups(
    packet: Packet, *, following: Sequence[Packet] = ()
) -> tuple[bytes, tuple[Fixup, ...]]:
    """Pack measured forms; following must be the remaining packets in this code section."""
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
    mnemonics = {instruction.mnemonic for instruction in packet.operations}
    if mnemonics & {"LSU1.STO.32", "LSU1.LDO.32"} and mnemonics & {"CMU.CMII.I32", "CMU.CMII.U32"}:
        raise AssemblyError(f"line {first.line}: CMII and LSU1 offset operation conflict on scalar read port 6")
    operations = [_operation(instruction) for instruction in packet.operations]
    if len({op.unit for op in operations}) != len(operations):
        raise AssemblyError(f"line {first.line}: repeated functional unit in packet")
    operations.sort(key=lambda op: _ORDER.index(op.unit))
    key = ",".join(op.prefix_class or op.unit for op in operations)
    if key not in _PREFIXES:
        raise AssemblyError(f"line {first.line}: unmeasured packet class {key}")
    bits, value = _PREFIXES[key]
    fixups = []
    for operation in operations:
        if operation.fixup is not None:
            fixup = operation.fixup
            kind = fixup.kind + ("_AT4" if bits % 8 == 4 else "")
            fixups.append(Fixup(fixup.symbol, fixup.addend, bits, fixup.bit_width, kind))
            value |= ((bits // 8) | _branch_delay_span(following) << 16) << bits
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
