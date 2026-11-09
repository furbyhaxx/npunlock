"""Bounded ELF32 little-endian object inspection for differential assembly tests."""

from __future__ import annotations

import struct
from dataclasses import dataclass


class ElfError(ValueError):
    """Input is not a bounded ELF32 little-endian SHAVE image."""


@dataclass(frozen=True)
class Section:
    """Section attributes and bytes, independent of file offsets."""

    name: str
    kind: int
    flags: int
    address: int
    size: int
    link: int
    info: int
    alignment: int
    entry_size: int
    data: bytes


@dataclass(frozen=True)
class Elf32:
    """SHAVE object or executable section layout."""

    kind: int
    entry: int
    flags: int
    sections: tuple[Section, ...]

    def section(self, name: str) -> Section:
        """Find a named section, raising KeyError if absent."""
        for section in self.sections:
            if section.name == name:
                return section
        raise KeyError(name)

    @classmethod
    def parse(cls, data: bytes) -> Elf32:
        """Read a valid ELF32 LE EM_SPARC section table with explicit bounds checks."""

        def span(offset: int, size: int) -> bytes:
            if offset > len(data) or size > len(data) - offset:
                raise ElfError(f"ELF range [{offset}, {offset + size}) exceeds {len(data)} bytes")
            return data[offset : offset + size]

        if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
            raise ElfError("expected ELF32 little-endian version 1")
        kind, machine, version = struct.unpack_from("<HHI", data, 16)
        if kind not in (1, 2) or machine != 2 or version != 1:
            raise ElfError("expected SHAVE ET_REL/ET_EXEC with EM_SPARC identity")
        entry, _, shoff = struct.unpack_from("<III", data, 24)
        shsize, count, names_index = struct.unpack_from("<HHH", data, 46)
        if shsize != 40 or count == 0 or names_index >= count:
            raise ElfError("unsupported ELF section table")
        table = span(shoff, count * shsize)
        headers = tuple(struct.iter_unpack("<10I", table))
        names_header = headers[names_index]
        if names_header[1] != 3:
            raise ElfError("section names are not a string table")
        names = span(names_header[4], names_header[5])
        sections: list[Section] = []
        for name, section_kind, flags, address, offset, size, link, info, alignment, entry_size in headers:
            if name >= len(names):
                raise ElfError("section name outside the string table")
            end = names.find(b"\0", name)
            if end < 0:
                raise ElfError("unterminated section name")
            try:
                decoded = names[name:end].decode("ascii")
            except UnicodeDecodeError as error:
                raise ElfError("non-ASCII section name") from error
            body = b"" if section_kind == 8 else span(offset, size)
            sections.append(
                Section(decoded, section_kind, flags, address, size, link, info, alignment, entry_size, body)
            )
        flags = struct.unpack_from("<I", data, 36)[0]
        return cls(kind, entry, flags, tuple(sections))


def compare_sections(expected: bytes, actual: bytes) -> list[str]:
    """Report every changed section attribute or payload, ignoring only file offsets."""
    left = Elf32.parse(expected)
    right = Elf32.parse(actual)
    differences = []
    if expected[:16] != actual[:16]:
        differences.append("ELF identification")
    if (left.kind, left.entry, left.flags) != (right.kind, right.entry, right.flags):
        differences.append("ELF kind/entry/flags")
    if [s.name for s in left.sections] != [s.name for s in right.sections]:
        differences.append("section order/names")
    for section in left.sections:
        try:
            other = right.section(section.name)
        except KeyError:
            differences.append(f"{section.name}: missing section")
            continue
        if section != other:
            fields = [name for name in Section.__dataclass_fields__ if getattr(section, name) != getattr(other, name)]
            differences.append(f"{section.name}: {', '.join(fields)}")
    return differences
