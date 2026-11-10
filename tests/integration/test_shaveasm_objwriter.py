from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.shaveasm.elf import Elf32
from tools.shaveasm.objwriter import assemble
from tools.shaveasm.parser import AssemblyError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/npu3720"


def symbols(image: Elf32) -> dict[str, tuple[int, int, int, int]]:
    strings = image.section(".strtab").data
    result = {}
    for name, value, size, info, _, section in struct.iter_unpack("<IIIBBH", image.section(".symtab").data):
        if name:
            end = strings.index(b"\0", name)
            result[strings[name:end].decode()] = (value, size, info, section)
    return result


class ObjectWriterTests(unittest.TestCase):
    def test_text_packets_and_function_size(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-text.s").read_text()))
        text = image.section(".text.entry")
        self.assertEqual((image.kind, image.entry, image.flags), (1, 0, 0))
        self.assertEqual((text.kind, text.flags, text.alignment), (1, 6, 16))
        self.assertEqual(text.data[4:11], bytes.fromhex("aa220100b29402"))
        self.assertEqual(text.data[-1:], b"\x50")
        self.assertEqual(symbols(image)["entry"], (0, len(text.data) - 1, 0x12, 1))

    def test_data_and_external_relocations(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-data.s").read_text()))
        data = image.section(".rodata4.items")
        expected = struct.pack("<III2B H f", 0x12345678, 0, 0, 0x12, 0x34, 0xABCD, 1.25)
        self.assertEqual(data.data, expected + bytes.fromhex("563412563412") + b"A\n")
        self.assertEqual(symbols(image)["items"], (0, len(data.data), 0x11, 1))
        self.assertEqual(symbols(image)["external"], (0, 0, 0x10, 0))
        relas = list(struct.iter_unpack("<IIi", image.section(".rela.rodata4.items").data))
        self.assertEqual(relas, [(4, 3 << 8 | 208, 0), (8, 3 << 8 | 208, 4)])

    def test_local_and_section_symbols_relocations(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-local.s").read_text()))
        self.assertEqual(symbols(image)["local"], (0, 0, 0x02, 1))
        self.assertEqual(symbols(image)["work"], (1, 0, 0x12, 1))
        relas = list(struct.iter_unpack("<IIi", image.section(".rela.rodata4.table").data))
        self.assertEqual(relas, [(0, 1 << 8 | 208, 2), (4, 4 << 8 | 208, 0), (8, 2 << 8 | 208, 2)])

    def test_section_flags_alignment_and_global_order(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-section.s").read_text()))
        self.assertEqual(
            [s.name for s in image.sections],
            ["", ".text.alpha", ".const", ".data.beta", ".symtab", ".strtab", ".rela.data.beta", ".shstrtab"],
        )
        self.assertEqual(image.section(".text.alpha").data, b"\x07\0\0\0")
        self.assertEqual(image.section(".const").flags, 2)
        self.assertEqual(image.section(".strtab").data, b"\0beta\0alpha\0")

    def test_private_symbols_are_interleaved_with_sections(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-private.s").read_text()))
        self.assertEqual(symbols(image)["helper"], (0, 1, 0x02, 2))
        self.assertEqual(image.section(".symtab").info, 5)
        relas = list(struct.iter_unpack("<IIi", image.section(".rela.rodata4.ptrs").data))
        self.assertEqual(relas, [(0, 3 << 8 | 208, 4), (4, 5 << 8 | 208, 0), (8, 7 << 8 | 208, 0)])

    def test_local_symbol_order_follows_creation_across_sections(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-local-order.s").read_text()))
        strings = image.section(".strtab").data
        rows = []
        for name, _, _, info, _, section in struct.iter_unpack("<IIIBBH", image.section(".symtab").data):
            rows.append((strings[name:strings.index(b"\0", name)].decode(), info, section))
        self.assertEqual(rows, [
            ("", 0, 0), ("declared", 2, 2), ("", 3, 1), ("second", 2, 3), ("first", 2, 2),
            ("missing", 0, 0), ("", 3, 2), ("late", 2, 2), ("", 3, 3), ("", 3, 4),
            ("lastmissing", 0, 0), ("entry", 0x12, 1),
        ])
        self.assertEqual(image.section(".symtab").info, 10)
        self.assertEqual(list(struct.iter_unpack("<IIi", image.section(".rela.text.main").data)),
                         [(2, 3 << 8 | 202, 0), (6, 4 << 8 | 202, 0), (10, 5 << 8 | 202, 0)])
        self.assertEqual(list(struct.iter_unpack("<IIi", image.section(".rela.data.ptrs").data)), [
            (0, 3 << 8 | 208, 0), (4, 4 << 8 | 208, 0), (8, 7 << 8 | 208, 0),
            (12, 6 << 8 | 208, 3), (16, 10 << 8 | 208, 0),
        ])

    def test_private_symbol_created_before_implicit_sections(self) -> None:
        image = Elf32.parse(assemble(".type .Ih,@function\n.end\n"))
        entries = list(struct.iter_unpack("<IIIBBH", image.section(".symtab").data))
        self.assertEqual([(info, section) for _, _, _, info, _, section in entries],
                         [(0, 0), (2, 0), (3, 1), (3, 2), (3, 3)])
        self.assertEqual(image.section(".symtab").info, 5)

    def test_branch_fixups_include_the_following_issue_slots(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-branch.s").read_text()))
        self.assertEqual(image.section(".text.branch").data[:4], b"\xc7\x01\x00\x06")
        self.assertEqual(image.section(".text.mixed").data[:8], bytes.fromhex("ae38d29443001000"))
        branch_relas = list(struct.iter_unpack("<IIi", image.section(".rela.text.branch").data))
        mixed_relas = list(struct.iter_unpack("<IIi", image.section(".rela.text.mixed").data))
        self.assertEqual(branch_relas, [(1, 1 << 8 | 209, 10)])
        self.assertEqual(mixed_relas, [(4, 2 << 8 | 210, 9)])

    def test_data_and_alignment_in_branch_delay_window_fail_closed(self) -> None:
        for directive in (".align 1", ".byte 0", ".fill 0"):
            source = f".code .text.x\nBRU.BRA .Ltarget\nNOP 4\n{directive}\nNOP 2\n.Ltarget:\n"
            with self.subTest(directive=directive), self.assertRaisesRegex(AssemblyError, r"line 4.*branch.*line 2"):
                assemble(source)
        image = Elf32.parse(assemble(".code .text.x\nBRU.BRA .Ltarget\nNOP 6\n.align 4\n.Ltarget:\n"))
        self.assertEqual(image.section(".text.x").data[:4], b"\xc7\x01\x00\x01")

    def test_register_jump_delay_suffix_matches_vendor(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-jump.s").read_text()))
        self.assertEqual(image.section(".text.jump").data, bytes.fromhex("47f106308222010007"))
        self.assertEqual(image.section(".text.jumpmixed").data, bytes.fromhex("ae18d294131f0050"))

    def test_register_control_transfer_delay_window_rejects_directives(self) -> None:
        for branch in ("BRU.JMP i30", "IAU.XOR i5 i6 i7 || BRU.JMP i30",
                       "BRU.SWP i30", "IAU.XOR i5 i6 i7 || BRU.SWP i30"):
            for directive in (".align 1", ".byte 0", ".fill 0"):
                source = f".code x\n{branch}\nNOP 4\n{directive}\nNOP 2\n"
                with self.subTest(branch=branch, directive=directive), self.assertRaisesRegex(
                    AssemblyError, r"line 4.*branch.*line 2"
                ):
                    assemble(source)
            assemble(f".code x\n{branch}\nNOP 6\n.align 4\n")
            assemble(f".code x\n{branch}\n.code y\n.align 4\n")
        assemble(".code x\nBRU.NOP\n.align 4\n")

    def test_branch_suffix_stops_at_section_switch(self) -> None:
        image = Elf32.parse(assemble((FIXTURES / "shaveasm-object-switch.s").read_text()))
        self.assertEqual(image.section(".text.x").data[:4], b"\xc7\x01\x00\x00")
        self.assertEqual(image.section(".text.z").data[:4], b"\xc7\x01\x00\x01")
        repeated = ".code x\nBRU.BRA target\n.code x\nNOP 6\n"
        self.assertEqual(Elf32.parse(assemble(repeated)).section("x").data[:4], b"\xc7\x01\x00\x00")

    def test_branch_in_delay_window_reports_source_line(self) -> None:
        source = ".code x\nBRU.BRA first\nBRU.BRA second\nNOP 6\n"
        with self.assertRaisesRegex(AssemblyError, r"line 2.*control transfer"):
            assemble(source)

    def test_fill_defaults_truncation_and_width_limit(self) -> None:
        source = ".data d\n.fill 3\n.fill 2,2\n.fill 2,3,0x123456\n.fill 1,9,0x12345678\n"
        image = Elf32.parse(assemble(source))
        self.assertEqual(image.section("d").data, b"\0" * 7 + bytes.fromhex("5634125634127856341200000000"))
        with self.assertRaisesRegex(AssemblyError, "line 2.*fill"):
            assemble(".data d\n.fill 2,2,-2\n")

    def test_undefined_private_symbol_is_local(self) -> None:
        image = Elf32.parse(assemble(".data d\n.long .Imissing\n"))
        self.assertEqual(symbols(image)["missing"], (0, 0, 0, 0))
        self.assertEqual(image.section(".symtab").info, 2)
        self.assertEqual(list(struct.iter_unpack("<IIi", image.section(".relad").data)), [(0, 2 << 8 | 208, 0)])

    def test_unsupported_syntax_fails_closed_with_line(self) -> None:
        for source in [
            ".code .text\nBRU.CALL target\n",
            ".data stuff\n.byte 256\n",
            ".data stuff\n.unknown 1\n",
            ".data stuff\n.long left-right\n",
            '.data stuff\n.ascii "unterminated',
            ".data stuff\n/* unterminated",
        ]:
            with self.subTest(source=source), self.assertRaisesRegex(AssemblyError, r"line 2"):
                assemble(source)

    def test_cli_assembles_and_preserves_output_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.o"
            source = Path(directory) / "input.s"
            source.write_text(".code .text.test\nNOP\n")
            command = [sys.executable, "-m", "tools.shaveasm.asm", str(source), "-o", str(output)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Elf32.parse(output.read_bytes()).section(".text.test").data, b"\x07")
            output.write_bytes(b"unchanged")
            source.write_text(".code .text.test\nINVALID\n")
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("line 2", result.stderr)
            self.assertEqual(output.read_bytes(), b"unchanged")
            source.write_text('.code .text.test\n.ascii "unfinished')
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("line 2", result.stderr)
            self.assertEqual(output.read_bytes(), b"unchanged")


if __name__ == "__main__":
    unittest.main()
