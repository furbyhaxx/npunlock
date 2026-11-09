from __future__ import annotations

import unittest

from tools.shaveasm.parser import AssemblyError, Directive, Label, Packet, parse


class ParserTests(unittest.TestCase):
    def test_vendor_packet_continuations_preserve_all_operations(self) -> None:
        source = """/* generated header
*/
.code .text.probe
probe:
    LSU0.LDIL i4 1 // first unit
      || LSU1.LDIL i8 2
      || IAU.XOR i5 i5 i5
      || CMU.CP.32 i9 i9
    NOP 6
.end
"""
        items = parse(source)
        self.assertEqual(items[0], Directive(".code", ".text.probe", 3))
        self.assertEqual(items[1], Label("probe", 4))
        packet = items[2]
        self.assertIsInstance(packet, Packet)
        self.assertEqual([op.mnemonic for op in packet.operations], ["LSU0.LDIL", "LSU1.LDIL", "IAU.XOR", "CMU.CP.32"])
        self.assertEqual(packet.operations[0].operands, ("i4", "1"))
        self.assertEqual(packet.operations[-1].line, 8)
        self.assertEqual(items[3].operations[0].operands, ("6",))

    def test_comment_delimiters_inside_strings_are_not_comments(self) -> None:
        source = '.ascii "/* keep */ // keep ; keep" /* drop */\n.L0: BRU.JMP i30 ; drop\n'
        items = parse(source)
        self.assertEqual(items[0], Directive(".ascii", '"/* keep */ // keep ; keep"', 1))
        self.assertEqual(items[1], Label(".L0", 2))
        self.assertEqual(items[2].operations[0].operands, ("i30",))

    def test_inline_packet_and_commas(self) -> None:
        packet = parse("LSU0.LDIL i4, 1 || IAU.XOR i5,i5,i5\n")[0]
        self.assertEqual(len(packet.operations), 2)
        self.assertEqual(packet.operations[1].operands, ("i5", "i5", "i5"))

    def test_orphan_continuation_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssemblyError, "line 2.*continuation"):
            parse(".code .text\n || IAU.XOR i5 i5 i5\n")

    def test_unterminated_comment_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssemblyError, "unterminated block comment"):
            parse("/* unfinished")


if __name__ == "__main__":
    unittest.main()
