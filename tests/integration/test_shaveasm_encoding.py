from __future__ import annotations

import unittest

from tools.shaveasm.encoding import encode_packet, encode_packet_with_fixups
from tools.shaveasm.fixups import Fixup
from tools.shaveasm.parser import AssemblyError, Packet, parse


def encode(source: str) -> bytes:
    statement = parse(source)[0]
    if not isinstance(statement, Packet):
        raise TypeError("expected an authored instruction packet")
    return encode_packet(statement)


class EncodingTests(unittest.TestCase):
    def test_packet_prefix_replaces_individual_prefixes(self) -> None:
        self.assertEqual(encode("LSU0.LDIL i4 1 || IAU.XOR i5 i5 i5"), bytes.fromhex("aa220100b29402"))
        self.assertEqual(encode("IAU.XOR i5 i5 i5 || LSU0.LDIL i4 1"), bytes.fromhex("aa220100b29402"))

    def test_twenty_bit_payload_is_not_byte_padded_inside_packet(self) -> None:
        self.assertEqual(encode("IAU.XOR i5 i5 i5 || PEU.PC1C EQ"), bytes.fromhex("adb294b201"))

    def test_single_instruction_encodings_remain_distinct(self) -> None:
        self.assertEqual(encode("LSU0.LDIL i4 1"), bytes.fromhex("82220100"))
        self.assertEqual(encode("IAU.XOR i5 i5 i5"), bytes.fromhex("86b29402"))

    def test_nop_forms_preserve_explicit_count(self) -> None:
        self.assertEqual(encode("NOP"), b"\x07")
        self.assertEqual(encode("NOP 1"), b"\x00")
        self.assertEqual(encode("NOP 6"), b"\x50")
        self.assertEqual(encode("NOP 16"), b"\xf0")
        self.assertEqual(encode("NOP 17"), b"\xf0\x00")
        self.assertEqual(encode("NOP 32"), b"\xf0\xf0")

    def test_branch_fixup_tracks_canonical_bit_offset_and_relocation_kind(self) -> None:
        cases = [
            ("BRU.BRA target", "c7010000", 8, "R_SHAVE_PCREL16"),
            ("BRU.BRA target || LSU0.LDIL i4 1", "cec2220100050000", 40, "R_SHAVE_PCREL16"),
            ("BRU.BRA target || IAU.XOR i5 i6 i7", "ae38d29443000000", 36, "R_SHAVE_PCREL16_AT4"),
            ("PEU.PC1C EQ || BRU.BRA target", "b50100001b", 8, "R_SHAVE_PCREL16"),
        ]
        for source, expected, offset, kind in cases:
            with self.subTest(source=source):
                packet = parse(source)[0]
                data, fixups = encode_packet_with_fixups(packet)
                self.assertEqual(data, bytes.fromhex(expected))
                self.assertEqual(fixups, (Fixup("target", 0, offset, 16, kind),))

    def test_branch_unmeasured_targets_fail_closed(self) -> None:
        for source in ("BRU.BRA 4", "BRU.BRA target+2", "BRU.CALL target"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode_packet_with_fixups(parse(source)[0])

    def test_invalid_or_unmeasured_input_fails_closed(self) -> None:
        for source in [
            "LSU0.LDIL i4 65536",
            "LSU0.LDIL i32 1",
            "LSU0.LDIL i4 1 || LSU0.LDIL i5 2",
            "BRU.BRA target",
            "NOP 0",
            "NOP || IAU.XOR i5 i5 i5",
        ]:
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)


if __name__ == "__main__":
    unittest.main()
