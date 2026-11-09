"""Symbolic relocation fields in native SHAVE packets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fixup:
    """A vendor relocation kind and its packet-relative, least-significant-bit field."""

    symbol: str
    addend: int
    bit_offset: int
    bit_width: int
    kind: str
