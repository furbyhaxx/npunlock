from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tools.shaveasm.corpus import discover
from tools.shaveasm.coverage import report
from tools.shaveasm.elf import Elf32, ElfError, compare_sections


def authored_object(payload: bytes) -> bytes:
    names = b"\0.text\0.shstrtab\0"
    offset = 52 + len(payload)
    table = offset + len(names)
    ident = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    header = struct.pack("<16sHHIIIIIHHHHHH", ident, 1, 2, 1, 0, 0, table, 0, 52, 0, 0, 40, 3, 2)
    sections = b"\0" * 40
    sections += struct.pack("<10I", 1, 1, 6, 0, 52, len(payload), 0, 0, 1, 0)
    sections += struct.pack("<10I", 7, 3, 0, 0, offset, len(names), 0, 0, 1, 0)
    return header + payload + names + sections


class CorpusTests(unittest.TestCase):
    def test_coverage_counts_shapes_once_per_rejected_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "authored.s").write_text(
                "NOP\nCMU.CMZ.I32 i1 || IAU.ADD i2 i3 -1\n"
                "CMU.CMZ.I32 i2 || IAU.ADD i4 i5 -2\n"
                "LSU0.LDIL i0 1 || IAU.UNMEASURED i1 i2 i3\n"
            )
            result = report([root, root])
            self.assertEqual((result["packets"], result["accepted_packets"]), (4, 1))
            rows = {(r["mnemonic"], r["operand_shape"]): r for r in result["rejected_shapes"]}
            self.assertEqual(rows[("CMU.CMZ.I32", "ireg")]["unsupported_packets"], 2)
            self.assertEqual(rows[("IAU.ADD", "ireg ireg negative")]["rejected_packets"], 2)
            self.assertEqual(rows[("LSU0.LDIL", "ireg immediate")]["unsupported_packets"], 0)
            self.assertEqual(result["parse_errors"], [])

    def test_capture_discovery_rejects_entry_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "examples").mkdir()
            (root / "examples/literal.py").write_text('source = b"void controlled_act(unsigned p) { return; }"\n')
            (root / "examples/generator.py").write_text('lines = ["void controlled_act(unsigned p) {"]\n')
            sources, dynamic = discover(root)
            self.assertEqual(len(sources), 1)
            self.assertEqual(dynamic, ["examples/generator.py:1 (entry fragment assembled by application)"])

    def test_section_comparison_detects_payload_changes(self) -> None:
        left, right = authored_object(b"\x07"), authored_object(b"\x00")
        self.assertEqual(Elf32.parse(left).section(".text").data, b"\x07")
        self.assertEqual(compare_sections(left, left), [])
        self.assertEqual(compare_sections(left, right), [".text: data"])

    def test_section_comparison_also_checks_elf_flags(self) -> None:
        left = authored_object(b"\x07")
        right = bytearray(left)
        struct.pack_into("<I", right, 36, 2)
        self.assertEqual(compare_sections(left, bytes(right)), ["ELF kind/entry/flags"])

    def test_invalid_elf_offsets_fail_before_slicing(self) -> None:
        data = bytearray(authored_object(b"\x07"))
        struct.pack_into("<I", data, 32, 0xFFFFFFF0)
        with self.assertRaisesRegex(ElfError, "exceeds"):
            Elf32.parse(bytes(data))


if __name__ == "__main__":
    unittest.main()
