"""Assemble the measured SHAVE subset into a relocatable ELF32 object."""

from __future__ import annotations

import ast
import math
import re
import struct
from dataclasses import dataclass, field

from . import encoding
from .fixups import Fixup
from .parser import AssemblyError, Directive, Label, Packet, parse

_NAME = r"[A-Za-z_.$][A-Za-z_0-9.$]*"
_MAX_SECTION_SIZE = 64 * 1024 * 1024
_RELOCATIONS = {
    "R_SHAVE_LO16": (200, 16, 0),
    "R_SHAVE_LO16_AT4": (201, 16, 4),
    "R_SHAVE_HI16": (202, 16, 0),
    "R_SHAVE_HI16_AT4": (203, 16, 4),
    "R_SHAVE_PCREL14_AT2": (204, 14, 2),
    "R_SHAVE_PCREL14_AT6": (205, 14, 6),
    "R_SHAVE_WINDOW_AT3": (206, 16, 3),
    "R_SHAVE_WINDOW_AT7": (207, 16, 7),
    "R_SHAVE_ABS32": (208, 32, 0),
    "R_SHAVE_PCREL16": (209, 16, 0),
    "R_SHAVE_PCREL16_AT4": (210, 16, 4),
}


@dataclass(frozen=True)
class _PendingPacket:
    packet: Packet
    offset: int
    size: int
    fixups: tuple[Fixup, ...]


@dataclass
class _Section:
    name: str
    kind: int
    flags: int
    alignment: int
    data_section: bool = False
    data: bytearray = field(default_factory=bytearray)
    relocations: list[tuple[int, Fixup, int]] = field(default_factory=list)
    events: list[_PendingPacket | Directive | None] = field(default_factory=list)


@dataclass
class _Symbol:
    name: str
    binding: int = 1
    kind: int = 0
    section: int = 0
    value: int = 0
    size: int = 0
    defined: bool = False
    explicit: bool = False
    typed: bool = False
    size_expr: tuple[str, int, int, int] | None = None

    @property
    def temporary(self) -> bool:
        return self.name.startswith(".L")

    @property
    def private(self) -> bool:
        return self.name.startswith(".I")

    @property
    def output_name(self) -> str:
        return self.name[2:] if self.private else self.name


def _number(text: str, line: int) -> int:
    try:
        return int(text.strip(), 0)
    except ValueError as error:
        raise AssemblyError(f"line {line}: expected integer, got {text!r}") from error


def _name(text: str, line: int) -> str:
    text = text.strip()
    if not re.fullmatch(_NAME, text):
        raise AssemblyError(f"line {line}: invalid symbol or section name {text!r}")
    return text


def _string(text: str, line: int) -> bytes:
    if not re.fullmatch(r'"(?:[^"\\]|\\.)*"', text.strip()):
        raise AssemblyError(f"line {line}: expected one quoted string")
    try:
        value = ast.literal_eval(text.strip())
        return value.encode("ascii")
    except (ValueError, SyntaxError, UnicodeEncodeError) as error:
        raise AssemblyError(f"line {line}: invalid ASCII string") from error


class _Assembler:
    def __init__(self) -> None:
        self.sections: list[_Section] = []
        self.symbols: dict[str, _Symbol] = {}
        self.local_order: list[int | _Symbol] = []
        self.current = 0
        self.ended = False

    def symbol(self, name: str, line: int) -> _Symbol:
        name = _name(name, line)
        if name not in self.symbols:
            symbol = _Symbol(name, binding=0 if name.startswith((".I", ".L")) else 1)
            self.symbols[name] = symbol
            if symbol.private:
                self.local_order.append(symbol)
        return self.symbols[name]

    def section(self, line: int) -> _Section:
        if not self.current:
            raise AssemblyError(f"line {line}: no current section")
        return self.sections[self.current - 1]

    def select_section(self, name: str, kind: int, flags: int, alignment: int, data_section: bool, line: int) -> None:
        name = _name(name, line)
        for index, section in enumerate(self.sections, 1):
            if section.name == name:
                if (section.kind, section.flags, section.data_section) != (kind, flags, data_section):
                    raise AssemblyError(f"line {line}: conflicting section definition {name}")
                self.current = index
                return
        self.sections.append(_Section(name, kind, flags, alignment, data_section))
        self.current = len(self.sections)
        self.local_order.append(self.current)

    def label(self, label: Label) -> None:
        section = self.section(label.line)
        symbol = self.symbol(label.name, label.line)
        if symbol.defined:
            raise AssemblyError(f"line {label.line}: duplicate symbol {label.name}")
        symbol.section, symbol.value, symbol.defined = self.current, len(section.data), True
        if section.data_section and not symbol.typed and not symbol.temporary:
            symbol.kind = 1

    def append(self, data: bytes, line: int) -> None:
        section = self.section(line)
        if len(section.data) + len(data) > _MAX_SECTION_SIZE:
            raise AssemblyError(f"line {line}: section size limit exceeded")
        if section.kind == 8 and any(data):
            raise AssemblyError(f"line {line}: initialized data in NOBITS section")
        section.data.extend(data)

    def fixup(self, section: _Section, offset: int, fixup: Fixup, line: int) -> None:
        relocation = _RELOCATIONS.get(fixup.kind)
        if relocation is None or (fixup.bit_width, fixup.bit_offset % 8) != relocation[1:]:
            raise AssemblyError(f"line {line}: unsupported relocation field {fixup.kind}")
        if fixup.bit_offset < 0 or fixup.bit_offset + fixup.bit_width > 8 * (len(section.data) - offset):
            raise AssemblyError(f"line {line}: relocation field outside its data")
        if not -(1 << 31) <= fixup.addend < 1 << 31:
            raise AssemblyError(f"line {line}: relocation addend is out of range")
        self.symbol(fixup.symbol, line)
        section.relocations.append((offset + fixup.bit_offset // 8, fixup, line))

    def packet(self, packet: Packet) -> None:
        line = packet.operations[0].line
        section = self.section(line)
        if not section.flags & 4 or section.kind != 1:
            raise AssemblyError(f"line {line}: instruction outside executable section")
        data, fixups = encoding.encode_packet_with_fixups(packet)
        offset = len(section.data)
        self.append(data, line)
        for fixup in fixups:
            self.fixup(section, offset, fixup, line)
        section.events.append(_PendingPacket(packet, offset, len(data), fixups))

    def resolve_packets(self) -> None:
        for section in self.sections:
            for index, event in enumerate(section.events):
                if not isinstance(event, _PendingPacket):
                    continue
                is_branch = encoding.is_control_transfer(event.packet)
                following = []
                slots = 0
                packet_line = event.packet.operations[0].line
                for later in section.events[index + 1 :]:
                    if later is None:
                        break
                    if isinstance(later, Directive):
                        if is_branch and slots < 6:
                            raise AssemblyError(
                                f"line {later.line}: data or alignment inside delay window "
                                f"of branch at line {packet_line}"
                            )
                        continue
                    following.append(later.packet)
                    if is_branch:
                        first = later.packet.operations[0]
                        slots += int(first.operands[0], 0) if first.mnemonic == "NOP" and first.operands else 1
                try:
                    data, fixups = encoding.encode_packet_with_fixups(event.packet, following=following)
                except AssemblyError as error:
                    if str(error).startswith("line "):
                        raise
                    raise AssemblyError(f"line {packet_line}: {error}") from error
                if len(data) != event.size or fixups != event.fixups:
                    raise AssemblyError(f"line {packet_line}: packet fixups changed with the delay window")
                section.data[event.offset : event.offset + event.size] = data

    def values(self, directive: Directive, width: int) -> None:
        section = self.section(directive.line)
        for value in directive.arguments.split(","):
            text = value.strip()
            if not text:
                raise AssemblyError(f"line {directive.line}: missing data value")
            reference = re.fullmatch(rf"({_NAME})(?:\s*\+\s*(0[xX][0-9a-fA-F]+|[0-9]+))?", text)
            if reference:
                if width != 4:
                    raise AssemblyError(f"line {directive.line}: symbolic data requires .long or .word")
                offset = len(section.data)
                self.append(b"\0" * 4, directive.line)
                addend = _number(reference[2], directive.line) if reference[2] else 0
                self.fixup(section, offset, Fixup(reference[1], addend, 0, 32, "R_SHAVE_ABS32"), directive.line)
                continue
            number = _number(text, directive.line)
            if not -(1 << (width * 8 - 1)) <= number < 1 << (width * 8):
                raise AssemblyError(f"line {directive.line}: data value out of range")
            self.append((number & ((1 << (width * 8)) - 1)).to_bytes(width, "little"), directive.line)

    def directive(self, directive: Directive) -> None:
        name, arguments, line = directive.name, directive.arguments.strip(), directive.line
        if name in (".align", ".byte", ".short", ".long", ".word", ".fill", ".float", ".ascii"):
            self.section(line).events.append(directive)
        if name in (".code", ".data"):
            if self.current:
                # A .code switch resets moviAsm's branch-delay window.
                self.section(line).events.append(None)
            self.select_section(arguments, 1, 6 if name == ".code" else 3, 1 if name == ".code" else 0,
                                name == ".data", line)
        elif name == ".section":
            match = re.fullmatch(rf'({_NAME})\s*,\s*"([awx]*)"\s*,\s*@?(progbits|nobits)', arguments, re.I)
            if match is None or len(set(match[2].lower())) != len(match[2]):
                raise AssemblyError(f"line {line}: unsupported .section declaration")
            flags = sum({"w": 1, "a": 2, "x": 4}[flag] for flag in match[2].lower())
            if self.current and self.section(line).name != match[1]:
                self.section(line).events.append(None)
            self.select_section(match[1], 1 if match[3].lower() == "progbits" else 8, flags, 0, False, line)
        elif name in (".global", ".globl", ".local"):
            for item in arguments.split(","):
                symbol = self.symbol(item, line)
                if symbol.temporary or symbol.private:
                    raise AssemblyError(f"line {line}: cannot declare binding of {symbol.name}")
                symbol.binding, symbol.explicit = (0 if name == ".local" else 1), True
        elif name == ".type":
            match = re.fullmatch(rf"({_NAME})\s*,\s*[@%](function|object|notype)", arguments, re.I)
            if match is None:
                raise AssemblyError(f"line {line}: unsupported .type declaration")
            symbol = self.symbol(match[1], line)
            symbol.kind, symbol.typed = {"notype": 0, "object": 1, "function": 2}[match[2].lower()], True
        elif name == ".size":
            match = re.fullmatch(rf"({_NAME})\s*,\s*(.+)", arguments)
            if match is None:
                raise AssemblyError(f"line {line}: invalid .size declaration")
            symbol = self.symbol(match[1], line)
            section = self.section(line)
            symbol.size_expr = (match[2], self.current, len(section.data), line)
        elif name == ".align":
            section = self.section(line)
            alignment = _number(arguments, line)
            if alignment < 1 or alignment > 1 << 20 or alignment & (alignment - 1):
                raise AssemblyError(f"line {line}: invalid alignment")
            self.append(b"\0" * (-len(section.data) % alignment), line)
            section.alignment = max(section.alignment, alignment)
        elif name in (".byte", ".short", ".long", ".word"):
            self.values(directive, {".byte": 1, ".short": 2, ".long": 4, ".word": 4}[name])
        elif name == ".fill":
            parts = arguments.split(",")
            if not 1 <= len(parts) <= 3:
                raise AssemblyError(f"line {line}: invalid .fill declaration")
            repeat = _number(parts[0], line)
            width = _number(parts[1], line) if len(parts) > 1 else 1
            value = _number(parts[2], line) if len(parts) > 2 else 0
            if repeat < 0 or width < 0 or not 0 <= value < 1 << 32:
                raise AssemblyError(f"line {line}: unsupported .fill value")
            width = min(width, 8)
            section = self.section(line)
            if repeat * width > _MAX_SECTION_SIZE - len(section.data):
                raise AssemblyError(f"line {line}: section size limit exceeded")
            pattern = value.to_bytes(4, "little")[:width].ljust(width, b"\0")
            self.append(pattern * repeat, line)
        elif name == ".float":
            for item in arguments.split(","):
                try:
                    number = float(item.strip())
                    if not math.isfinite(number):
                        raise ValueError("non-finite float")
                    data = struct.pack("<f", number)
                except (ValueError, OverflowError) as error:
                    raise AssemblyError(f"line {line}: invalid float {item!r}") from error
                self.append(data, line)
        elif name == ".ascii":
            self.append(_string(arguments, line), line)
            # moviAsm resets the section alignment after .ascii.
            self.section(line).alignment = 1
        elif name == ".file":
            _string(arguments, line)
        elif name in (".nowarn", ".nowarnend", ".end") and not arguments:
            self.ended = name == ".end"
        else:
            raise AssemblyError(f"line {line}: unsupported directive {name}")

    def resolve_sizes(self) -> None:
        for symbol in self.symbols.values():
            if symbol.size_expr is None:
                continue
            expression, section, offset, line = symbol.size_expr
            match = re.fullmatch(rf"(\.|{_NAME})\s*-\s*({_NAME})", expression.strip())
            if match:
                right = self.symbols.get(match[2])
                left = None if match[1] == "." else self.symbols.get(match[1])
                if right is None or not right.defined or (match[1] != "." and (left is None or not left.defined)):
                    raise AssemblyError(f"line {line}: unresolved .size expression")
                left_section, left_value = (section, offset) if left is None else (left.section, left.value)
                if left_section != right.section:
                    raise AssemblyError(f"line {line}: .size symbols are in different sections")
                size = left_value - right.value
            else:
                size = _number(expression, line)
            if not 0 <= size < 1 << 32:
                raise AssemblyError(f"line {line}: invalid symbol size")
            symbol.size = size

    def build(self) -> bytes:
        self.resolve_packets()
        self.resolve_sizes()
        if not self.sections:
            self.sections.extend((_Section(".text", 1, 6, 1), _Section(".data", 1, 3, 1), _Section(".bss", 8, 3, 1)))
            self.local_order.extend(range(1, len(self.sections) + 1))
        named = [symbol for symbol in self.symbols.values() if not symbol.temporary]
        explicit = sorted((s for s in named if s.explicit), key=lambda s: s.name, reverse=True)
        ordered = explicit + [s for s in named if not s.explicit]
        strings = bytearray(b"\0")
        name_offsets: dict[str, int] = {}
        for symbol in ordered:
            if symbol.output_name not in name_offsets:
                name_offsets[symbol.output_name] = len(strings)
                strings.extend(symbol.output_name.encode("ascii") + b"\0")
        locals_ = [s for s in explicit if not s.binding]
        globals_ = [s for s in ordered if s.binding]
        entries: list[tuple[int, int, int, int, int, int]] = [(0, 0, 0, 0, 0, 0)]
        indexes: dict[str, int] = {}
        section_indexes: dict[int, int] = {}

        def add(symbol: _Symbol) -> None:
            indexes[symbol.name] = len(entries)
            entries.append((name_offsets[symbol.output_name], symbol.value, symbol.size,
                            symbol.binding << 4 | symbol.kind, 0, symbol.section))

        for symbol in locals_:
            add(symbol)
        first_global = len(entries)
        for item in self.local_order:
            if isinstance(item, int):
                section_indexes[item] = len(entries)
                entries.append((0, 0, 0, 3, 0, item))
                first_global = len(entries)
            else:
                add(item)
                # moviAsm's sh_info excludes only trailing undefined locals.
                if item.defined:
                    first_global = len(entries)
        for symbol in globals_:
            add(symbol)
        symtab = b"".join(struct.pack("<IIIBBH", *entry) for entry in entries)
        symtab_index = len(self.sections) + 1
        strtab_index = symtab_index + 1
        rows: list[tuple[str, int, int, int, int, int, int, bytes, int]] = []
        for section in self.sections:
            rows.append((section.name, section.kind, section.flags, 0, 0, section.alignment, 0,
                         bytes(section.data) if section.kind != 8 else b"", len(section.data)))
        rows.extend(((".symtab", 2, 0, strtab_index, first_global, 8, 16, symtab, len(symtab)),
                     (".strtab", 3, 0, 0, 0, 8, 0, bytes(strings), len(strings))))
        for index, section in enumerate(self.sections, 1):
            if not section.relocations:
                continue
            relas = bytearray()
            for offset, fixup, line in sorted(section.relocations, key=lambda item: item[0]):
                symbol = self.symbols[fixup.symbol]
                addend = fixup.addend
                if symbol.temporary:
                    if not symbol.defined:
                        raise AssemblyError(f"line {line}: undefined local label {symbol.name}")
                    symbol_index = section_indexes[symbol.section]
                    addend += symbol.value
                else:
                    symbol_index = indexes[symbol.name]
                if not -(1 << 31) <= addend < 1 << 31:
                    raise AssemblyError(f"line {line}: relocation addend is out of range")
                relas.extend(struct.pack("<IIi", offset, symbol_index << 8 | _RELOCATIONS[fixup.kind][0], addend))
            rows.append((".rela" + section.name, 4, 0, symtab_index, index, 4, 12, bytes(relas), len(relas)))
        names = bytearray(b"\0")
        names_offsets = []
        for row in [*rows, (".shstrtab",)]:
            names_offsets.append(len(names))
            names.extend(row[0].encode("ascii") + b"\0")
        rows.append((".shstrtab", 3, 0, 0, 0, 8, 0, bytes(names), len(names)))
        body = bytearray()
        headers = bytearray(40)
        for name_offset, (_, kind, flags, link, info, alignment, entry_size, data, size) in zip(names_offsets, rows):
            offset = 52 + len(body)
            body.extend(data)
            headers.extend(
                struct.pack("<10I", name_offset, kind, flags, 0, offset, size, link, info, alignment, entry_size)
            )
        ident = b"\x7fELF\x01\x01\x01" + b"\0" * 9
        header = struct.pack("<16sHHIIIIIHHHHHH", ident, 1, 2, 1, 0, 0, 52 + len(body), 0,
                             52, 0, 0, 40, len(rows) + 1, len(rows))
        return header + body + headers


def assemble(source: str) -> bytes:
    """Assemble supported vendor syntax, raising AssemblyError for unmeasured forms."""
    assembler = _Assembler()
    try:
        statements = parse(source)
    except AssemblyError as error:
        if str(error) in ("unterminated block comment", "unterminated quoted string"):
            line = max(1, len(source.splitlines()) + int(source.endswith(("\n", "\r"))))
            raise AssemblyError(f"line {line}: {error}") from error
        raise
    for statement in statements:
        if assembler.ended:
            line = statement.operations[0].line if isinstance(statement, Packet) else statement.line
            raise AssemblyError(f"line {line}: content after .end")
        if isinstance(statement, Label):
            assembler.label(statement)
        elif isinstance(statement, Directive):
            assembler.directive(statement)
        else:
            assembler.packet(statement)
    return assembler.build()
