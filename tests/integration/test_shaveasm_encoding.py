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

    def test_signed_compare_register_order_differs_from_copy_destination_order(self) -> None:
        self.assertEqual(encode("CMU.CMII.I32 i31 i0"), bytes.fromhex("81f00101"))
        self.assertEqual(encode("CMU.CMII.I32 i0 i31"), bytes.fromhex("81003e01"))
        with self.assertRaises(AssemblyError):
            encode("CMU.CMII.I32 i0 1")

    def test_immediate_shift_uses_the_twenty_four_bit_add_class(self) -> None:
        self.assertEqual(encode("IAU.SHL i0 i0 0"), bytes.fromhex("c60c0080"))
        self.assertEqual(encode("IAU.SHL i31 i31 31"), bytes.fromhex("c6ecff8f"))
        for source in ("IAU.SHL i0 i1 -1", "IAU.SHL i0 i1 32", "IAU.SHL i0 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_and_shares_the_measured_twenty_bit_xor_class(self) -> None:
        self.assertEqual(encode("IAU.AND i5 i5 i5"), bytes.fromhex("86b09402"))
        self.assertEqual(encode("IAU.AND i5 i5 i5 || PEU.PC1C EQ"), bytes.fromhex("adb094b201"))
        with self.assertRaises(AssemblyError):
            encode("IAU.AND i0 i1 3")

    def test_pccx_has_twelve_payload_bits_and_its_own_neq_selector(self) -> None:
        self.assertEqual(encode("PEU.PCCX NEQ 63"), bytes.fromhex("c5d90f"))
        self.assertEqual(encode("PEU.PCCX EQ 0"), bytes.fromhex("c50500"))
        self.assertEqual(encode("IAU.XOR i16 i17 i18 || PEU.PCCX NEQ 63"),
                         bytes.fromhex("ed324299fd"))
        for source in ("PEU.PCCX EQ 64", "PEU.PCCX EQ -1", "PEU.PCCX BAD 0",
                       "PEU.PCCX EQ 0 || PEU.PC1C EQ"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_compare_zero_uses_a_sixteen_bit_payload(self) -> None:
        self.assertEqual(encode("CMU.CMZ.I32 i0"), bytes.fromhex("410000"))
        self.assertEqual(encode("CMU.CMZ.I32 i31"), bytes.fromhex("41f001"))
        self.assertEqual(encode("CMU.CMZ.I32 i1 || LSU0.LDIL i4 1"),
                         bytes.fromhex("941000220100"))
        for source in ("CMU.CMZ.I32 i32", "CMU.CMZ.I32 i1 i2",
                       "CMU.CMZ.I32 i1 || CMU.CP.32 i2 i3"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_add_register_and_unsigned_immediate_forms(self) -> None:
        self.assertEqual(encode("IAU.ADD i0 i0 i0"), bytes.fromhex("c6000000"))
        self.assertEqual(encode("IAU.ADD i31 i31 i31"), bytes.fromhex("c6e0ff0f"))
        self.assertEqual(encode("IAU.ADD i31 i31 255"), bytes.fromhex("c6e0ffff"))
        self.assertEqual(encode("LSU0.LDO.32 i4 i5 -3 || IAU.ADD i0 i0 0"),
                         bytes.fromhex("fa424afbff000080"))
        for source in ("IAU.ADD i0 i0 -1", "IAU.ADD i0 i0 256", "IAU.ADD i0 i0 i32",
                       "IAU.ADD i1 i2 i3 || IAU.XOR i4 i5 i6"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_signed_load_offset_uses_a_distinct_header_class(self) -> None:
        self.assertEqual(encode("LSU0.LDO.32 i0 i0 -3"), bytes.fromhex("c20240fbff"))
        self.assertEqual(encode("LSU0.LDO.32 i31 i31 16383"), bytes.fromhex("c2f27fff7f"))
        self.assertEqual(encode("LSU0.LDO.32 i4 i5 -3 || IAU.XOR i16 i17 i18"),
                         bytes.fromhex("ba424afbff324209"))
        for source in ("LSU0.LDO.32 i0 i0 -16385", "LSU0.LDO.32 i0 i0 16384",
                       "LSU0.LDO.32 i1 i2 0 || LSU0.LDIL i4 1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

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

    def test_branch_delay_span_ends_at_six_issue_slots(self) -> None:
        cases = [
            ("NOP 5", 0), ("NOP 6", 1), ("NOP 16", 1), ("NOP 17", 1),
            ("\n".join(["NOP"] * 6), 6),
            ("\n".join(["LSU0.LDIL i4 1"] * 6), 24),
            ("NOP 4\nLSU0.LDIL i4 1\nNOP", 6),
        ]
        branch = parse("BRU.BRA target")[0]
        for following, span in cases:
            with self.subTest(following=following):
                data, fixups = encode_packet_with_fixups(branch, following=parse(following))
                self.assertEqual(data, bytes((0xc7, 1, 0, span)))
                self.assertEqual(fixups, (Fixup("target", 0, 8, 16, "R_SHAVE_PCREL16"),))
        mixed = parse("IAU.XOR i5 i6 i7 || BRU.BRA target")[0]
        data, fixups = encode_packet_with_fixups(mixed, following=parse("NOP 6"))
        self.assertEqual(data, bytes.fromhex("ae38d29443001000"))
        self.assertEqual(fixups[0].bit_offset, 36)
        with self.assertRaisesRegex(AssemblyError, "control transfer"):
            encode_packet_with_fixups(branch, following=parse("BRU.BRA other\nNOP 6"))

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
