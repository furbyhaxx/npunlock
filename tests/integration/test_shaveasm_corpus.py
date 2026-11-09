from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.shaveasm.corpus import discover
from tools.shaveasm.corpus_parity import diagnose, report as parity_report, write_reports
from tools.shaveasm.coverage import report
from tools.shaveasm.elf import Elf32, ElfError, compare_sections
from tools.shaveasm.objwriter import assemble


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
                "NOP\nCMU.UNMEASURED i1 || IAU.ADD i2 i3 -1\n"
                "CMU.UNMEASURED i2 || IAU.ADD i4 i5 -2\n"
                "LSU0.LDIL i0 1 || IAU.UNMEASURED i1 i2 i3\n"
            )
            result = report([root, root])
            self.assertEqual((result["packets"], result["accepted_packets"]), (4, 1))
            rows = {(r["mnemonic"], r["operand_shape"]): r for r in result["rejected_shapes"]}
            self.assertEqual(rows[("CMU.UNMEASURED", "ireg")]["unsupported_packets"], 2)
            self.assertEqual(rows[("IAU.ADD", "ireg ireg negative")]["rejected_packets"], 2)
            self.assertEqual(rows[("LSU0.LDIL", "ireg immediate")]["unsupported_packets"], 0)
            self.assertEqual(result["parse_errors"], [])

    def test_coverage_identifies_packets_requiring_fixups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "authored.s").write_text("NOP\nBRU.BRA target\n")
            result = report([root])
            self.assertEqual((result["packets"], result["accepted_packets"]), (2, 2))
            self.assertEqual(result["relocatable_packets"], 1)
            self.assertEqual(result["rejected_shapes"], [])

    def test_parity_reports_exact_difference_and_first_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = ".code .text.test\nNOP\n"
            for name in ("exact", "different", "rejected", "missing"):
                (root / f"{name}.s").write_text(source)
            obj = assemble(source)
            (root / "exact.o").write_bytes(obj)
            changed = bytearray(obj)
            struct.pack_into("<I", changed, 28, 1)
            (root / "different.o").write_bytes(changed)
            (root / "rejected.s").write_text(".code .text.test\nIAU.UNMEASURED i1\n")
            (root / "rejected.o").write_bytes(obj)
            result = parity_report([root, root], diagnostic=True)
            files = {Path(row["path"]).stem: row for row in result["files"]}
            self.assertEqual({name: row["status"] for name, row in files.items()}, {
                "exact": "exact", "different": "different", "rejected": "rejected", "missing": "missing_reference"
            })
            self.assertEqual(files["different"]["section_differences"], [])
            self.assertEqual(files["rejected"]["first_rejection"]["line"], 2)
            self.assertEqual(files["rejected"]["first_rejection"]["category"], "instruction")
            self.assertEqual(result["summary"]["files"], 4)
            output = root / "report"
            write_reports(result, output)
            self.assertEqual(json.loads((output / "report.json").read_text()), result)
            self.assertIn("| exact | 1 |", (output / "summary.md").read_text())

    def test_diagnostics_continue_across_categories_and_packets(self) -> None:
        source = (
            ".code code\n"
            "IAU.UNMEASURED i1 || LSU0.UNKNOWN i2 4\n"
            "IAU.UNMEASURED i3\n"
            "BRU.BRA target\n"
            "IAU.UNMEASURED i4\n"
            ".byte 1\n"
            ".align 4\n"
            "NOP 6\n"
            "target:\n"
            ".data data\n"
            ".unknown 1\n"
            ".word 1 + 2\n"
            ".type data, @unsupported\n"
            ".word .Lmissing\n"
            ".word .Lmissing2\n"
            ".size bad, missing + 1\n"
            ".size bad2, missing + 2\n"
        )
        result = diagnose(source)
        self.assertTrue(result["complete"])
        errors = result["rejections"]
        self.assertEqual([(e["line"], e["mnemonic"], e["operand_shape"]) for e in errors
                          if e["category"] == "instruction"], [
            (2, "IAU.UNMEASURED", "ireg"), (2, "LSU0.UNKNOWN", "ireg immediate"),
            (3, "IAU.UNMEASURED", "ireg"), (5, "IAU.UNMEASURED", "ireg"),
        ])
        self.assertEqual([e["line"] for e in errors if e["category"] == "delay_window_directive"], [6, 7])
        self.assertEqual([e["line"] for e in errors if e["category"] == "directive"], [11])
        self.assertEqual([e["line"] for e in errors if e["category"] == "expression"], [12, 16, 17])
        self.assertEqual([e["line"] for e in errors if e["category"] == "symbol_relocation"], [13, 14, 15])

    def test_first_rejection_classification_preserves_statement_context(self) -> None:
        cases = {
            "instruction": ".code c\nlabel: IAU.ADD i1 i2 invalid\n",
            "directive": ".data d\n.unknown 1\n",
            "expression": ".data d\n.word 1+2\n",
            "symbol_relocation": ".data d\n.type item, @unknown\n",
            "delay_window_directive": ".code c\nBRU.BRA target\n.byte 0\n",
            "other": ".data d\nNOP\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = assemble(".code c\nNOP\n")
            for category, source in cases.items():
                (root / f"{category}.s").write_text(source)
                (root / f"{category}.o").write_bytes(reference)
            result = parity_report([root])
            for item in result["files"]:
                with self.subTest(path=item["path"]):
                    self.assertEqual(item["status"], "rejected")
                    self.assertEqual(item["first_rejection"]["category"], Path(item["path"]).stem)

    def test_diagnostics_recover_from_parse_errors_without_losing_later_lines(self) -> None:
        result = diagnose(".code code\nINVALID-OP i0\n.unknown 1\n")
        self.assertTrue(result["complete"])
        self.assertEqual([(e["line"], e["category"]) for e in result["rejections"]],
                         [(2, "other"), (3, "directive")])
        incomplete = diagnose('.code code\n.ascii "unterminated')
        self.assertFalse(incomplete["complete"])
        self.assertEqual(incomplete["rejections"][0]["category"], "other")

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
