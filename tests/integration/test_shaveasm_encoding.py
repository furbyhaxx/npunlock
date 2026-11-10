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
    def test_sau_bitwise_or_shares_twenty_bit_logical_class(self) -> None:
        self.assertEqual(encode("SAU.OR i0 i0 i0"), bytes.fromhex("2c1b0000"))
        self.assertEqual(encode("SAU.OR i1 i2 i3"), bytes.fromhex("2c5b8401"))
        for source in ("i0 i0 1", "i32 i0 i0", "i0 i0 v0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode("SAU.OR " + source)

    def test_signed_byte_compare_uses_cmu_register_fields(self) -> None:
        self.assertEqual(encode("CMU.CMII.I8 i0 i0"), bytes.fromhex("81000005"))
        self.assertEqual(encode("CMU.CMII.I8 i1 i2"), bytes.fromhex("81100405"))
        for source in ("CMU.CMII.I8 i0 1", "CMU.CMII.I8 i32 i0", "CMU.CMII.I8 i0 v0",
                       "CMU.CMII.I8 i0 i1 || LSU1.ST.64 v8.0 i9",
                       "CMU.CMII.I8 i0 i1 || LSU1.LD.32.F16.F32 i8 i9"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_sau_float_divide_uses_scalar_registers(self) -> None:
        self.assertEqual(encode("SAU.DIV.F32 i0 i0 i0"), bytes.fromhex("3c060020"))
        self.assertEqual(encode("SAU.DIV.F32 i1 i2 i3"), bytes.fromhex("3c468421"))
        self.assertEqual(encode("SAU.DIV.F32 i31 i31 i31"), bytes.fromhex("3ce6ff2f"))
        for source in ("i0 i0 1.0", "i0 i0 3", "i32 i0 i0", "i0 i0 v0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode("SAU.DIV.F32 " + source)

    def test_lsu1_half_to_float_load_uses_twenty_bit_class(self) -> None:
        self.assertEqual(encode("LSU1.LD.32.F16.F32 i0 i0"), bytes.fromhex("49000000"))
        self.assertEqual(encode("LSU1.LD.32.F16.F32 i31 i31"), bytes.fromhex("49f03f00"))
        self.assertEqual(encode("LSU1.LD.32.F16.F32 i1 i2"), bytes.fromhex("49100400"))
        self.assertEqual(encode("LSU1.LD.32.F16.F32 i8 i9 || LSU0.LD.32.F16.F32 i4 i5"),
                         bytes.fromhex("59400a002801"))
        for source in ("LSU1.LD.32.F16.F32 i32 i0", "LSU1.LD.32.F16.F32 i0.0 i0",
                       "LSU1.LD.32.F16.F32 i8 i9 || CMU.CMII.I32 i0 i1",
                       "LSU1.LD.32.F16.F32 i8 i9 || LSU0.LDO.64 i4 i5 -3"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu1_postincrement_halfword_store_accepts_scalar_lanes(self) -> None:
        self.assertEqual(encode("LSU1.STI.16 i0.0 i0"), bytes.fromhex("89090082"))
        self.assertEqual(encode("LSU1.STI.16 i31.3 i31"), bytes.fromhex("89f9ff82"))
        self.assertEqual(encode("LSU1.STI.16 i1.2 i2"), bytes.fromhex("89198482"))
        for source in ("LSU1.STI.16 i0.4 i0", "LSU1.STI.16 i0 i0", "LSU1.STI.16 i32.0 i0",
                       "LSU1.STI.16 i8.0 i9 || CMU.CMII.I32 i0 i1",
                       "LSU1.STI.16 i8.0 i9 || LSU0.STO.64 i4 i5 -3"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu1_indirect_doubleword_store_uses_strict_vector_lanes(self) -> None:
        for operands, expected in (("i0 i0", "89098000"), ("i1 i2", "89198400"),
                                   ("i31 i31", "89f9bf00"), ("v31.1 i31", "89f9ff08")):
            with self.subTest(operands=operands):
                self.assertEqual(encode("LSU1.ST.64 " + operands), bytes.fromhex(expected))
        self.assertEqual(encode("LSU1.ST.64 v8.0 i9 || LSU0.CP.32 i4 i5"), bytes.fromhex("a9470a08899208"))
        for source in ("LSU1.ST.64 v0.2 i0", "LSU1.ST.64 i32 i0", "LSU1.ST.64 v32.0 i0",
                       "LSU1.ST.64 i8 i9 || CMU.CMII.I32 i0 i1",
                       "LSU1.ST.64 i8 i9 || LSU0.CP.32 i4 i5",
                       "LSU1.ST.64 i8 i9 || LSU0.STO.64 i4 i5 -3"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_sau_unsigned_halfword_shift_uses_register_or_five_bit_immediate(self) -> None:
        for source, expected in (("i0 i0 0", "3c120050"), ("i1 i2 3", "3c528451"),
                                 ("i31 i31 31", "3cf2ff5f"), ("i1 i2 i3", "3c528441")):
            with self.subTest(source=source):
                self.assertEqual(encode("SAU.SHR.U16 " + source), bytes.fromhex(expected))
        for source in ("i0 i0 -1", "i0 i0 32", "i0 i0 0.5", "i0 i0 i32", "v0 i0 1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode("SAU.SHR.U16 " + source)

    def test_sau_xor_can_share_the_corpus_immediate_iau_header(self) -> None:
        self.assertEqual(encode("CMU.CMII.I32 i0 i1 || LSU0.LDIL i4 1 || "
                                "SAU.XOR i12 i13 i14 || IAU.ADD i16 i17 3 || PEU.PCCX EQ 3"),
                         bytes.fromhex("0f28ce000201220100ba3107221c580c"))

    def test_vau_or_can_share_a_measured_136_bit_packet(self) -> None:
        self.assertEqual(encode("LSU0.CP.32 i4 i5 || LSU1.CP.32 i8 i9 || "
                                "CMU.CP.32 i1 i2 || VAU.OR v3 v4 v5 || IAU.OR i16 i17 i18"),
                         bytes.fromhex("0faa089b8cc2228070a480702881102394"))

    def test_iau_subtract_with_carry_uses_twenty_bit_iau_headers(self) -> None:
        self.assertEqual(encode("IAU.SUBCI i31 i30 i29"), bytes.fromhex("86c7ff0e"))
        self.assertEqual(encode("IAU.SUBCI i0 i0 i1"), bytes.fromhex("86078000"))
        for source in ("IAU.SUBCI i0 i0 1", "IAU.SUBCI i0 v0 i0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_sau_xor_reuses_twenty_bit_sau_headers(self) -> None:
        self.assertEqual(encode("SAU.XOR i31 i30 i29"), bytes.fromhex("2cdaff0e"))
        self.assertEqual(encode("SAU.XOR i0 i1 i0"), bytes.fromhex("2c3a0000"))
        for source in ("SAU.XOR i0 i0 1", "SAU.XOR i32 i0 i0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu0_indirect_store_uses_scalar_register_fields(self) -> None:
        self.assertEqual(encode("LSU0.ST.32 i31 i30"), bytes.fromhex("82f93d01"))
        self.assertEqual(encode("LSU0.ST.32 i0 i1"), bytes.fromhex("82090201"))
        for source in ("LSU0.ST.32 v0.0 i0", "LSU0.ST.32 i32 i0",
                       "LSU0.ST.32 i0 i32", "LSU0.ST.32 i4 i5 || LSU1.STO.64 i8 i9 0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_vau_or_has_a_twenty_bit_payload(self) -> None:
        self.assertEqual(encode("VAU.OR v31 v30 v29"), bytes.fromhex("23dbff0e"))
        self.assertEqual(encode("CMU.CP.32 i1 i2 || VAU.OR v3 v4 v5"),
                         bytes.fromhex("a19b8cc2228000"))
        with self.assertRaises(AssemblyError):
            encode("VAU.OR v0 v0 v0 || SAU.AND i0 i0 i0")

    def test_vau_subtraction_uses_vector_register_fields(self) -> None:
        self.assertEqual(encode("VAU.SUB.F32 v31 v30 v29"), bytes.fromhex("33c2ff2e"))
        self.assertEqual(encode("VAU.SUB.F32 v0 v0 v1"), bytes.fromhex("33028020"))

    def test_vau_addition_uses_vector_register_fields(self) -> None:
        self.assertEqual(encode("VAU.ADD.F32 v31 v30 v29"), bytes.fromhex("33c0ff2e"))
        self.assertEqual(encode("VAU.ADD.F32 v1 v0 v0"), bytes.fromhex("33000420"))

    def test_vau_multiply_packs_before_scalar_units(self) -> None:
        self.assertEqual(encode("VAU.MUL.F32 v31 v30 v29"), bytes.fromhex("33c4ff2e"))
        self.assertEqual(encode("CMU.CP.32 i1 i2 || VAU.MUL.F32 v3 v4 v5"),
                         bytes.fromhex("b1848c222c0208"))
        self.assertEqual(encode("VAU.MUL.F32 v3 v4 v5 || LSU1.LDIL i8 456"),
                         bytes.fromhex("0e83848c2242c801"))
        for source in ("VAU.MUL.F32 i0 v0 v0", "VAU.MUL.F32 v32 v0 v0",
                       "VAU.MUL.F32 v0 v0.0 v0", "VAU.MUL.F32 v0 v0 -1",
                       "VAU.MUL.F32 v0 v0 v0 || SAU.ADD.I32 i0 i0 1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu0_offset_doubleword_load_selects_scalar_pairs_and_vector_lanes(self) -> None:
        self.assertEqual(encode("LSU0.LDO.64 i1 i19 72"), bytes.fromhex("c212269100"))
        self.assertEqual(encode("LSU0.LDO.64 v9.1 i10 40"), bytes.fromhex("c292145000"))
        self.assertEqual(encode("LSU0.LDO.64 v0.0 i0 0"), bytes.fromhex("c202400000"))
        self.assertEqual(encode("LSU0.LDO.64 I31 i0 -1"), bytes.fromhex("c2f201ffff"))
        self.assertEqual(encode("LSU0.LDO.64 V0.15 i0 0"), bytes.fromhex("c202000000"))
        for source in ("LSU0.LDO.64 v32.0 i0 0", "LSU0.LDO.64 v0.16 i0 0",
                       "LSU0.LDO.64 v0 i0 0", "LSU0.LDO.64 i32 i0 0",
                       "LSU0.LDO.64 i0 i0 16384", "LSU0.LDO.64 i0 i0 -16385",
                       "LSU0.LDO.64 i4 i5 0 || LSU1.LDO.32 i8 i9 0",
                       "LSU0.LDO.64 i4 i5 0 || LSU1.LD.32 i8 i9"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu1_offset_doubleword_load_reuses_the_pair_and_lane_field(self) -> None:
        self.assertEqual(encode("LSU1.LDO.64 i31 i0 0"), bytes.fromhex("c9f2010100"))
        self.assertEqual(encode("LSU1.LDO.64 v0.0 i0 0"), bytes.fromhex("c902400000"))
        self.assertEqual(encode("LSU1.LDO.64 v31.15 i0 0"), bytes.fromhex("c9f2010000"))
        self.assertEqual(encode("LSU1.LDO.64 v8.0 i9 0 || LSU0.LD.32.F16.F32 i4 i5"),
                         bytes.fromhex("d9400a2028050000"))
        for other in ("LSU0.LD.32 i4 i5", "LSU0.LDO.32 i4 i5 0",
                      "LSU0.LD.16 i4.0 i5", "LSU0.LD.32.F16.F32 i4 i5",
                      "LSU0.LDO.64 i4 i5 0", "CMU.CMII.I32 i0 i1"):
            with self.subTest(other=other), self.assertRaises(AssemblyError):
                encode("LSU1.LDO.64 i8 i9 0 || " + other)

    def test_lsu1_postincrement_float_to_half_store_uses_twenty_bit_payload(self) -> None:
        self.assertEqual(encode("LSU1.STI.16.F32.F16 i4 i8"), bytes.fromhex("49441008"))
        self.assertEqual(encode("LSU1.STI.16.F32.F16 i31 i31"), bytes.fromhex("49f43f08"))
        for source in ("LSU1.STI.16.F32.F16 v4.0 i8", "LSU1.STI.16.F32.F16 i32 i8",
                       "LSU1.STI.16.F32.F16 i4 i32",
                       "LSU1.STI.16.F32.F16 i4 i8 || CMU.CMII.F32 i0 i1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu1_offset_doubleword_store_selects_the_shared_pair_and_lane_field(self) -> None:
        self.assertEqual(encode("LSU1.STO.64 i31 i0 0"), bytes.fromhex("c9f6010100"))
        self.assertEqual(encode("LSU1.STO.64 v0.0 i0 0"), bytes.fromhex("c906400000"))
        self.assertEqual(encode("LSU1.STO.64 v31.15 i0 0"), bytes.fromhex("c9f6010000"))
        self.assertEqual(encode("LSU1.STO.64 i8 i9 0 || LSU0.LDO.64 i4 i5 0"),
                         bytes.fromhex("f9420a010086120100"))
        for source in ("LSU1.STO.64 i8 i9 0 || LSU0.STO.32 i4 i5 0",
                       "LSU1.STO.64 i8 i9 0 || LSU0.CP.32 i4 i5",
                       "LSU1.STO.64 v8.0 i9 0 || CMU.CMII.I32 i0 i1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

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

    def test_cmu_copy_reads_a_vector_word_lane(self) -> None:
        self.assertEqual(encode("CMU.CP.32 i0 v0.0"), bytes.fromhex("810c0070"))
        self.assertEqual(encode("CMU.CP.32 i1 v0.0"), bytes.fromhex("810c0270"))
        self.assertEqual(encode("CMU.CP.32 i0 v1.0"), bytes.fromhex("811c0070"))
        self.assertEqual(encode("CMU.CP.32 i0 v0.1"), bytes.fromhex("810c4070"))
        self.assertEqual(encode("CMU.CP.32 I31 V31.3"), bytes.fromhex("81fcff70"))
        for source in ("CMU.CP.32 i0 v32.0", "CMU.CP.32 i0 v0.4",
                       "CMU.CP.32 i0 v0", "CMU.CP.32 i32 v0.0",
                       "CMU.CP.32 v0.0 i0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_sau_register_right_shift_clears_the_immediate_selector(self) -> None:
        self.assertEqual(encode("SAU.SHR.U32 i0 i0 i0"), bytes.fromhex("3c120000"))
        self.assertEqual(encode("SAU.SHR.U32 i1 i2 i3"), bytes.fromhex("3c528401"))
        self.assertEqual(encode("SAU.SHR.U32 i31 i31 i31"), bytes.fromhex("3cf2ff0f"))
        for source in ("SAU.SHR.U32 i0 i0 i32", "SAU.SHR.U32 i0 i0 v1",
                       "SAU.SHL.X32 i0 i0 i32"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_register_right_shift_uses_the_twenty_four_bit_iau_class(self) -> None:
        self.assertEqual(encode("IAU.SHR.U32 i0 i0 i0"), bytes.fromhex("c60e0000"))
        self.assertEqual(encode("IAU.SHR.U32 i1 i2 i3"), bytes.fromhex("c64e8401"))
        self.assertEqual(encode("IAU.SHR.U32 i31 i31 i31"), bytes.fromhex("c6eeff0f"))
        for source in ("IAU.SHR.U32 i0 i0 i32", "IAU.SHR.U32 i0 i0 v1",
                       "IAU.SHL i0 i0 i32"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu0_halfword_load_selects_one_of_four_scalar_lanes(self) -> None:
        self.assertEqual(encode("LSU0.LD.16 i0.0 i0"), bytes.fromhex("820d0002"))
        self.assertEqual(encode("LSU0.LD.16 i1.0 i2"), bytes.fromhex("821d0402"))
        self.assertEqual(encode("LSU0.LD.16 i0.1 i0"), bytes.fromhex("820d4002"))
        self.assertEqual(encode("LSU0.LD.16 i0.2 i0"), bytes.fromhex("820d8002"))
        self.assertEqual(encode("LSU0.LD.16 i0.3 i0"), bytes.fromhex("820dc002"))
        self.assertEqual(encode("LSU0.LD.16 i31.1 i31"), bytes.fromhex("82fd7f02"))
        for source in ("LSU0.LD.16 i0 i0", "LSU0.LD.16 i0.4 i0",
                       "LSU0.LD.16 i32.0 i0", "LSU0.LD.16 v0.0 i0",
                       "LSU0.LD.16 i0.0 i32", "LSU0.LD.16 i0.0 1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu0_half_load_converts_to_float_in_the_twenty_bit_class(self) -> None:
        self.assertEqual(encode("LSU0.LD.32.F16.F32 i0 i0"), bytes.fromhex("42000000"))
        self.assertEqual(encode("LSU0.LD.32.F16.F32 i1 i2"), bytes.fromhex("42100400"))
        self.assertEqual(encode("LSU0.LD.32.F16.F32 i31 i31"), bytes.fromhex("42f03f00"))
        for source in ("LSU0.LD.32.F16.F32 i32 i0", "LSU0.LD.32.F16.F32 i0 i32",
                       "LSU0.LD.32.F16.F32 i0.0 i0", "LSU0.LD.32.F16.F32 i0 1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu1_scalar_copy_can_share_a_packet_with_comparison(self) -> None:
        self.assertEqual(encode("LSU1.CP.32 i0 i0"), bytes.fromhex("89070008"))
        self.assertEqual(encode("LSU1.CP.32 i1 i2"), bytes.fromhex("89170408"))
        self.assertEqual(encode("LSU1.CP.32 i31 i31"), bytes.fromhex("89f73f08"))
        self.assertEqual(encode("CMU.CMII.F32 i0 i1 || LSU1.CP.32 i8 i9"),
                         bytes.fromhex("0e88000208871208"))
        for source in ("LSU1.CP.32 i32 i0", "LSU1.CP.32 i0 i32",
                       "LSU1.CP.32 i0 1", "LSU1.CP.32 v0.0 i0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_sau_register_left_shift_clears_the_immediate_selector(self) -> None:
        self.assertEqual(encode("SAU.SHL.X32 i0 i0 i0"), bytes.fromhex("3c110000"))
        self.assertEqual(encode("SAU.SHL.X32 i1 i2 i3"), bytes.fromhex("3c518401"))
        self.assertEqual(encode("SAU.SHL.X32 i31 i31 i31"), bytes.fromhex("3cf1ff0f"))
        with self.assertRaises(AssemblyError):
            encode("SAU.SHL.X32 i0 i0 v1")

    def test_sau_integer_add_accepts_a_register_right_operand(self) -> None:
        self.assertEqual(encode("SAU.ADD.I32 i0 i0 i0"), bytes.fromhex("3c000000"))
        self.assertEqual(encode("SAU.ADD.I32 i1 i2 i3"), bytes.fromhex("3c408401"))
        self.assertEqual(encode("SAU.ADD.I32 i31 i31 i31"), bytes.fromhex("3ce0ff0f"))
        for source in ("SAU.ADD.I32 i0 i0 i32", "SAU.ADD.I32 i0 i0 v1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu0_offset_store_shares_the_offset_load_class(self) -> None:
        self.assertEqual(encode("LSU0.STO.32 i0 i0 0"), bytes.fromhex("c206400100"))
        self.assertEqual(encode("LSU0.STO.32 i1 i2 -1"), bytes.fromhex("c21644ffff"))
        self.assertEqual(encode("LSU0.STO.32 i31 i31 -16384"), bytes.fromhex("c2f67f0180"))
        self.assertEqual(encode("LSU0.STO.32 i31 i31 16383"), bytes.fromhex("c2f67fff7f"))
        for source in ("LSU0.STO.32 i0 i0 -16385", "LSU0.STO.32 i0 i0 16384",
                       "LSU0.STO.32 i32 i0 0", "LSU0.STO.32 i0 i0 symbol"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_iau_multiply_uses_signed_eight_bit_immediates(self) -> None:
        self.assertEqual(encode("IAU.MUL i0 i0 i0"), bytes.fromhex("c6020000"))
        self.assertEqual(encode("IAU.MUL i0 i0 0"), bytes.fromhex("c6020080"))
        self.assertEqual(encode("IAU.MUL i1 i2 3"), bytes.fromhex("c6428481"))
        self.assertEqual(encode("IAU.MUL i0 i0 -1"), bytes.fromhex("c60280ff"))
        self.assertEqual(encode("IAU.MUL i0 i0 -128"), bytes.fromhex("c60200c0"))
        for source in ("IAU.MUL i0 i0 -129", "IAU.MUL i0 i0 128", "IAU.MUL i0 i0 i32"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_scalar_float_comparison_uses_its_type_selector(self) -> None:
        self.assertEqual(encode("CMU.CMII.F32 i0 i0"), bytes.fromhex("81000008"))
        self.assertEqual(encode("CMU.CMII.F32 i1 i2"), bytes.fromhex("81100408"))
        self.assertEqual(encode("CMU.CMII.F32 i31 i31"), bytes.fromhex("81f03f08"))
        for source in ("CMU.CMII.F32 i32 i0", "CMU.CMII.F32 i0 1.0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for mnemonic in ("LSU1.ST.32", "LSU1.LD.32", "LSU1.STI.32"):
            with self.subTest(mnemonic=mnemonic), self.assertRaisesRegex(AssemblyError, "read port 6"):
                encode(f"CMU.CMII.F32 i0 i1 || {mnemonic} i8 i9")
        for mnemonic in ("LSU1.STO.32", "LSU1.LDO.32"):
            with self.subTest(mnemonic=mnemonic), self.assertRaisesRegex(AssemblyError, "read port 6"):
                encode(f"CMU.CMII.F32 i0 i1 || {mnemonic} i8 i9 0")

    def test_scalar_float_subtraction_uses_the_sau_class(self) -> None:
        self.assertEqual(encode("SAU.SUB.F32 i0 i0 i0"), bytes.fromhex("3c020020"))
        self.assertEqual(encode("SAU.SUB.F32 i1 i2 i3"), bytes.fromhex("3c428421"))
        self.assertEqual(encode("SAU.SUB.F32 i31 i31 i31"), bytes.fromhex("3ce2ff2f"))
        for source in ("SAU.SUB.F32 i0 i0 1.0", "SAU.SUB.F32 i32 i0 i0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_register_left_shift_clears_the_immediate_selector(self) -> None:
        self.assertEqual(encode("IAU.SHL i0 i0 i0"), bytes.fromhex("c60c0000"))
        self.assertEqual(encode("IAU.SHL i1 i2 i3"), bytes.fromhex("c64c8401"))
        self.assertEqual(encode("IAU.SHL i31 i31 i31"), bytes.fromhex("c6ecff0f"))
        with self.assertRaises(AssemblyError):
            encode("IAU.SHL i0 i0 v1")

    def test_lsu1_indirect_load_uses_the_twenty_four_bit_class(self) -> None:
        self.assertEqual(encode("LSU1.LD.32 i0 i0"), bytes.fromhex("890d0001"))
        self.assertEqual(encode("LSU1.LD.32 i31 i31"), bytes.fromhex("89fd3f01"))
        self.assertEqual(encode("LSU1.LD.32 i1 i2"), bytes.fromhex("891d0401"))
        for source in ("LSU1.LD.32 i32 i0", "LSU1.LD.32 i0 i32",
                       "LSU1.LD.32 i0 1", "LSU1.LD.32 i0 i1 4"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for comparison in ("CMU.CMII.I32", "CMU.CMII.U32"):
            with self.subTest(comparison=comparison), self.assertRaisesRegex(AssemblyError, "read port 6"):
                encode(f"{comparison} i0 i1 || LSU1.LD.32 i8 i9")

    def test_lsu1_scalar_store_leaves_the_postincrement_selector_clear(self) -> None:
        self.assertEqual(encode("LSU1.ST.32 i0 i0"), bytes.fromhex("89090001"))
        self.assertEqual(encode("LSU1.ST.32 i31 i31"), bytes.fromhex("89f93f01"))
        self.assertEqual(encode("LSU1.ST.32 i1 i2"), bytes.fromhex("89190401"))
        for source in ("LSU1.ST.32 i32 i0", "LSU1.ST.32 i0 i32",
                       "LSU1.ST.32 i0 1", "LSU1.ST.32 i0 i1 4"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for comparison in ("CMU.CMII.I32", "CMU.CMII.U32"):
            with self.subTest(comparison=comparison), self.assertRaisesRegex(AssemblyError, "read port 6"):
                encode(f"{comparison} i0 i1 || LSU1.ST.32 i8 i9")

    def test_lsu1_postincrement_store_uses_the_twenty_four_bit_class(self) -> None:
        self.assertEqual(encode("LSU1.STI.32 i0 i0"), bytes.fromhex("89090081"))
        self.assertEqual(encode("LSU1.STI.32 i31 i31"), bytes.fromhex("89f93f81"))
        self.assertEqual(encode("LSU1.STI.32 i1 i2"), bytes.fromhex("89190481"))
        self.assertEqual(encode("CMU.CP.32 i0 i1 || LSU1.STI.32 i8 i9"),
                         bytes.fromhex("0e881c0008891281"))
        for source in ("LSU1.STI.32 i32 i0", "LSU1.STI.32 i0 i32",
                       "LSU1.STI.32 i0 1", "LSU1.STI.32 i0 i1 4"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for comparison in ("CMU.CMII.I32", "CMU.CMII.U32"):
            with self.subTest(comparison=comparison), self.assertRaisesRegex(AssemblyError, "read port 6"):
                encode(f"{comparison} i0 i1 || LSU1.STI.32 i8 i9")

    def test_unsigned_compare_has_no_signed_selector_bit(self) -> None:
        self.assertEqual(encode("CMU.CMII.U32 i31 i0"), bytes.fromhex("81f00100"))
        self.assertEqual(encode("CMU.CMII.U32 i0 i31"), bytes.fromhex("81003e00"))
        with self.assertRaisesRegex(AssemblyError, "read port 6"):
            encode("CMU.CMII.U32 i1 i2 || LSU1.STO.32 i8 i9 0")

    def test_subtraction_has_register_and_unsigned_immediate_forms(self) -> None:
        self.assertEqual(encode("IAU.SUB i0 i0 i0"), bytes.fromhex("c6010000"))
        self.assertEqual(encode("IAU.SUB i31 i31 i31"), bytes.fromhex("c6e1ff0f"))
        self.assertEqual(encode("IAU.SUB i0 i0 1"), bytes.fromhex("c6018080"))
        self.assertEqual(encode("IAU.SUB i31 i31 255"), bytes.fromhex("c6e1ffff"))
        for source in ("IAU.SUB i0 i0 -1", "IAU.SUB i0 i0 256", "IAU.SUB i32 i0 i0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_register_swap_uses_jump_headers_and_delay_windows(self) -> None:
        self.assertEqual(encode("BRU.SWP i0"), bytes.fromhex("470200"))
        self.assertEqual(encode("BRU.SWP i31"), bytes.fromhex("47fa00"))
        swap = parse("BRU.SWP i30")[0]
        data, fixups = encode_packet_with_fixups(swap, following=parse("NOP 6"))
        self.assertEqual(data, bytes.fromhex("47f201"))
        self.assertEqual(fixups, ())
        data, _ = encode_packet_with_fixups(swap, following=parse("\n".join(["NOP"] * 6)))
        self.assertEqual(data, bytes.fromhex("47f206"))
        for source in ("BRU.SWP target", "BRU.SWP 30", "BRU.SWP i32"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "control transfer"):
            encode_packet_with_fixups(swap, following=parse("BRU.SWP i0\nNOP 6"))

    def test_register_jump_has_a_sixteen_bit_payload_and_delay_span(self) -> None:
        self.assertEqual(encode("BRU.JMP i0"), bytes.fromhex("470100"))
        self.assertEqual(encode("BRU.JMP i31"), bytes.fromhex("47f900"))
        jump = parse("BRU.JMP i30")[0]
        data, fixups = encode_packet_with_fixups(jump, following=parse("NOP 6"))
        self.assertEqual(data, bytes.fromhex("47f101"))
        self.assertEqual(fixups, ())
        data, _ = encode_packet_with_fixups(jump, following=parse("\n".join(["NOP"] * 6)))
        self.assertEqual(data, bytes.fromhex("47f106"))
        for source in ("BRU.JMP target", "BRU.JMP 30", "BRU.JMP i32",
                       "BRU.JMP i0 || BRU.BRA target"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "control transfer"):
            encode_packet_with_fixups(jump, following=parse("BRU.JMP i0\nNOP 6"))

    def test_lsu1_symbolic_low_load_emits_byte_and_half_byte_fixups(self) -> None:
        data, fixups = encode_packet_with_fixups(parse("LSU1.LDIL i0 external_target")[0])
        self.assertEqual(data, bytes.fromhex("89020000"))
        self.assertEqual(fixups, (Fixup("external_target", 0, 16, 16, "R_SHAVE_LO16"),))
        packet = parse("CMU.CMPI i0 0 || LSU1.LDIL i31 external_target")[0]
        data, fixups = encode_packet_with_fixups(packet)
        self.assertEqual(data, bytes.fromhex("0e8c0a0000a00f0000"))
        self.assertEqual(fixups, (Fixup("external_target", 0, 52, 16, "R_SHAVE_LO16_AT4"),))
        for source in ("LSU1.LDIL i0 target+2", "LSU1.LDIL i0 -1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "symbolic fixups"):
            encode("LSU1.LDIL i0 external_target")

    def test_lsu1_high_immediate_load_and_fixup(self) -> None:
        self.assertEqual(encode("LSU1.LDIH i0 0"), bytes.fromhex("89030000"))
        self.assertEqual(encode("LSU1.LDIH i31 65535"), bytes.fromhex("89fbffff"))
        packet = parse("LSU1.LDIH i6 external_target")[0]
        data, fixups = encode_packet_with_fixups(packet)
        self.assertEqual(data, bytes.fromhex("89330000"))
        self.assertEqual(fixups, (Fixup("external_target", 0, 16, 16, "R_SHAVE_HI16"),))
        for source in ("LSU1.LDIH i0 65536", "LSU1.LDIH i0 -1",
                       "LSU1.LDIH i32 0", "LSU1.LDIH i0 target+2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_high_immediate_load_and_absolute_high_fixup(self) -> None:
        self.assertEqual(encode("LSU0.LDIH i0 0"), bytes.fromhex("82030000"))
        self.assertEqual(encode("LSU0.LDIH i31 65535"), bytes.fromhex("82fbffff"))
        packet = parse("LSU0.LDIH i4 external_target")[0]
        data, fixups = encode_packet_with_fixups(packet)
        self.assertEqual(data, bytes.fromhex("82230000"))
        self.assertEqual(fixups, (Fixup("external_target", 0, 16, 16, "R_SHAVE_HI16"),))
        packet = parse("BRU.BRA target || LSU0.LDIH i4 external_target")[0]
        data, fixups = encode_packet_with_fixups(packet)
        self.assertEqual(data, bytes.fromhex("cec2230000050000"))
        self.assertEqual(fixups, (Fixup("external_target", 0, 24, 16, "R_SHAVE_HI16"),
                                  Fixup("target", 0, 40, 16, "R_SHAVE_PCREL16")))
        for source in ("LSU0.LDIH i0 65536", "LSU0.LDIH i32 0",
                       "LSU0.LDIH i0 target+2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "symbolic fixups"):
            encode("LSU0.LDIH i4 external_target")

    def test_lsu1_signed_offset_load_uses_the_thirty_two_bit_lsu1_class(self) -> None:
        self.assertEqual(encode("LSU1.LDO.32 i0 i0 -16384"), bytes.fromhex("c902400180"))
        self.assertEqual(encode("LSU1.LDO.32 i31 i31 16383"), bytes.fromhex("c9f27fff7f"))
        self.assertEqual(encode("LSU1.LDO.32 i1 i2 -3"), bytes.fromhex("c91244fbff"))
        for source in ("LSU1.LDO.32 i0 i0 -16385", "LSU1.LDO.32 i0 i0 16384",
                       "LSU1.LDO.32 i0 i1 0 || LSU1.LDIL i2 1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for comparison in ("CMU.CMII.I32", "CMU.CMII.U32"):
            with self.subTest(comparison=comparison), self.assertRaisesRegex(AssemblyError, "read port 6"):
                encode(f"{comparison} i0 i1 || LSU1.LDO.32 i8 i9 0")

    def test_lsu0_scalar_copy_shares_the_twenty_four_bit_lsu0_class(self) -> None:
        self.assertEqual(encode("LSU0.CP.32 i0 i0"), bytes.fromhex("82070008"))
        self.assertEqual(encode("LSU0.CP.32 i31 i31"), bytes.fromhex("82f73f08"))
        self.assertEqual(encode("LSU0.CP.32 i1 i2"), bytes.fromhex("82170408"))
        for source in ("LSU0.CP.32 i0 symbol", "LSU0.CP.32 i0 i32",
                       "LSU0.CP.32 i0 i1 0", "LSU0.CP.64 i0 i1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_float_multiply_uses_measured_constant_mapping(self) -> None:
        self.assertEqual(encode("SAU.MUL.F32 i1 i2 3.0"), bytes.fromhex("3c448431"))
        self.assertEqual(encode("SAU.MUL.F32 i1 i2 0.5"), bytes.fromhex("3c440430"))
        for literal in ("0.0", "4.0", "0.50", "1.0e0"):
            with self.subTest(literal=literal), self.assertRaises(AssemblyError):
                encode(f"SAU.MUL.F32 i1 i2 {literal}")

    def test_float_multiply_uses_scalar_registers_in_the_sau_class(self) -> None:
        self.assertEqual(encode("SAU.MUL.F32 i0 i0 i0"), bytes.fromhex("3c040020"))
        self.assertEqual(encode("SAU.MUL.f32 i31 i31 i31"), bytes.fromhex("3ce4ff2f"))
        self.assertEqual(encode("SAU.MUL.F32 i1 i2 i3"), bytes.fromhex("3c448421"))
        for source in ("SAU.MUL.F32 i0 i1 0.25", "SAU.MUL.F32 i32 i0 i0",
                       "SAU.MUL.F32 i0 i0 i32", "SAU.MUL.F16 i0 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_float_add_uses_measured_constant_mapping(self) -> None:
        for literal, payload in (("0.5", "400430"), ("1.0", "408430"),
                                 ("2.0", "400431"), ("3.0", "408431"),
                                 ("-0.5", "400438"), ("-1.0", "408438"),
                                 ("-2.0", "400439"), ("-3.0", "408439"),
                                 ("+1.0", "408430")):
            with self.subTest(literal=literal):
                self.assertEqual(encode(f"SAU.ADD.F32 i1 i2 {literal}"), bytes.fromhex("3c" + payload))
        for literal in ("0.0", "4.0", "0.25", "1.5", "0.50", ".5", "1e0", "1.0e0", "nan", "inf"):
            with self.subTest(literal=literal), self.assertRaises(AssemblyError):
                encode(f"SAU.ADD.F32 i1 i2 {literal}")

    def test_float_add_uses_scalar_registers_in_the_sau_class(self) -> None:
        self.assertEqual(encode("SAU.ADD.F32 i0 i0 i0"), bytes.fromhex("3c000020"))
        self.assertEqual(encode("SAU.ADD.f32 i31 i31 i31"), bytes.fromhex("3ce0ff2f"))
        self.assertEqual(encode("SAU.ADD.F32 i1 i2 i3"), bytes.fromhex("3c408421"))
        for source in ("SAU.ADD.F32 i0 i1 3", "SAU.ADD.F32 i32 i0 i0",
                       "SAU.ADD.F16 i0 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_indirect_scalar_load_shares_the_twenty_four_bit_lsu0_class(self) -> None:
        self.assertEqual(encode("LSU0.LD.32 i0 i0"), bytes.fromhex("820d0001"))
        self.assertEqual(encode("LSU0.LD.32 i31 i31"), bytes.fromhex("82fd3f01"))
        self.assertEqual(encode("LSU0.LD.32 i1 i2"), bytes.fromhex("821d0401"))
        for source in ("LSU0.LD.32 i0 0", "LSU0.LD.32 i0 i32",
                       "LSU0.LD.32 i0 i1 0", "LSU0.LD.32.f32.f16 i0 i1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_incs_updates_a_register_with_a_signed_fourteen_bit_immediate(self) -> None:
        self.assertEqual(encode("IAU.INCS i0 -8192"), bytes.fromhex("c6030080"))
        self.assertEqual(encode("IAU.INCS i31 8191"), bytes.fromhex("c6e3ff7f"))
        self.assertEqual(encode("IAU.INCS i1 1"), bytes.fromhex("c6230400"))
        for source in ("IAU.INCS i0 -8193", "IAU.INCS i0 8192", "IAU.INCS i0 i1",
                       "IAU.INCS i32 0", "IAU.INCS i0 i1 0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lmull_uses_the_twenty_bit_integer_class(self) -> None:
        self.assertEqual(encode("IAU.LMULL i0 i0 i0"), bytes.fromhex("86040000"))
        self.assertEqual(encode("IAU.LMULL i31 i31 i31"), bytes.fromhex("86e4ff0f"))
        self.assertEqual(encode("IAU.LMULL i16 i17 i18 || PEU.PCCX NEQ 63"),
                         bytes.fromhex("ed244299fd"))
        for source in ("IAU.LMULL i0 i1 3", "IAU.LMULL i0 i1 -1",
                       "IAU.LMULL i32 i0 i0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_or_uses_the_twenty_bit_logical_class(self) -> None:
        self.assertEqual(encode("IAU.OR i5 i5 i5"), bytes.fromhex("86b19402"))
        self.assertEqual(encode("IAU.OR i16 i17 i18 || PEU.PCCX NEQ 63"), bytes.fromhex("ed314299fd"))
        with self.assertRaises(AssemblyError):
            encode("IAU.OR i0 i1 3")

    def test_signed_store_offset_has_its_own_lsu1_header_class(self) -> None:
        self.assertEqual(encode("LSU1.STO.32 i0 i0 -16384"), bytes.fromhex("c906400180"))
        self.assertEqual(encode("LSU1.STO.32 i31 i31 16383"), bytes.fromhex("c9f67fff7f"))
        for source in ("LSU1.STO.32 i0 i1 -16385", "LSU1.STO.32 i0 i1 16384",
                       "LSU1.STO.32 i0 i1 0 || LSU1.LDIL i2 1",
                       "LSU1.STO.32 i8 i9 0 || CMU.CMII.I32 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_signed_compare_register_order_differs_from_copy_destination_order(self) -> None:
        self.assertEqual(encode("CMU.CMII.I32 i31 i0"), bytes.fromhex("81f00101"))
        self.assertEqual(encode("CMU.CMII.I32 i0 i31"), bytes.fromhex("81003e01"))
        with self.assertRaises(AssemblyError):
            encode("CMU.CMII.I32 i0 1")

    def test_immediate_shift_uses_the_twenty_four_bit_add_class(self) -> None:
        self.assertEqual(encode("IAU.SHL i0 i0 0"), bytes.fromhex("c60c0080"))
        self.assertEqual(encode("IAU.SHL i31 i31 31"), bytes.fromhex("c6ecff8f"))
        for source in ("IAU.SHL i0 i1 -1", "IAU.SHL i0 i1 32", "IAU.SHL i0 i1 i32"):
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

    def test_lsu0_doubleword_store_reuses_the_measured_register_field(self) -> None:
        self.assertEqual(encode("LSU0.STO.64 v0.0 i0 0"), bytes.fromhex("c206400000"))
        self.assertEqual(encode("LSU0.STO.64 v31.1 i31 -3"), bytes.fromhex("c2f63ffaff"))
        self.assertEqual(encode("LSU0.STO.64 i31 i31 16383"), bytes.fromhex("c2f63fff7f"))
        self.assertEqual(encode("LSU0.STO.64 v24.1 i19 688"), bytes.fromhex("c286276005"))
        self.assertEqual(encode("LSU0.STO.64 v31.15 i31 -3"),
                         encode("LSU0.STO.64 v31.1 i31 -3"))
        for source in ("LSU0.STO.64 v32.0 i0 0", "LSU0.STO.64 v0.16 i0 0",
                       "LSU0.STO.64 i32 i0 0", "LSU0.STO.64 v0 i0 0",
                       "LSU0.STO.64 v0.0 i32 0", "LSU0.STO.64 v0.0 i0 16384",
                       "LSU0.STO.64 v0.0 i0 -16385"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "read port 8"):
            encode("LSU0.STO.64 i4 i5 0 || LSU1.STO.64 i8 i9 0")
        for operation in ("LSU1.CP.32 i8 i9", "LSU1.STO.32 i8 i9 0",
                          "LSU1.ST.32 i8 i9", "LSU1.STI.32 i8 i9",
                          "LSU1.STI.16.F32.F16 i8 i9"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AssemblyError, "read port 9"):
                encode("LSU0.STO.64 i4 i5 0 || " + operation)

    def test_lsu0_indirect_doubleword_load_has_distinct_vector_selectors(self) -> None:
        self.assertEqual(encode("LSU0.LD.64 v0.0 i0"), bytes.fromhex("820d8008"))
        self.assertEqual(encode("LSU0.LD.64 v31.1 i31"), bytes.fromhex("82fdff08"))
        self.assertEqual(encode("LSU0.LD.64 i31 i31"), bytes.fromhex("82fdbf00"))
        for source in ("LSU0.LD.64 v32.0 i0", "LSU0.LD.64 v0.2 i0",
                       "LSU0.LD.64 i32 i0", "LSU0.LD.64 v0 i0",
                       "LSU0.LD.64 v0.0 i32", "LSU0.LD.64 v0.0 i0 0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "write port 5"):
            encode("LSU0.LD.64 i4 i5 || LSU1.LD.32 i8 i9")
        with self.assertRaisesRegex(AssemblyError, "write port 4"):
            encode("LSU0.LD.64 i4 i5 || LSU1.LDO.64 i8 i9 0")

    def test_lsu1_indirect_doubleword_load_reuses_lsu0_fields(self) -> None:
        self.assertEqual(encode("LSU1.LD.64 v0.0 i0"), bytes.fromhex("890d8008"))
        self.assertEqual(encode("LSU1.LD.64 v31.1 i31"), bytes.fromhex("89fdff08"))
        self.assertEqual(encode("LSU1.LD.64 i31 i31"), bytes.fromhex("89fdbf00"))
        for source in ("LSU1.LD.64 v32.0 i0", "LSU1.LD.64 v0.2 i0",
                       "LSU1.LD.64 i32 i0", "LSU1.LD.64 v0 i0",
                       "LSU1.LD.64 v0.0 i32", "LSU1.LD.64 v0.0 i0 0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for operation in ("LSU0.LD.32 i4 i5", "LSU0.LDO.32 i4 i5 0",
                          "LSU0.LDO.64 i4 i5 0", "LSU0.LD.64 i4 i5",
                          "LSU0.LD.32.F16.F32 i4 i5"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AssemblyError, "write port 4"):
                encode(operation + " || LSU1.LD.64 i8 i9")
        with self.assertRaisesRegex(AssemblyError, "read port 6"):
            encode("CMU.CMII.F32 i0 i1 || LSU1.LD.64 v8.0 i9")

    def test_cmu_unsigned_to_float_conversion(self) -> None:
        self.assertEqual(encode("CMU.CP.32.U32.F32 i0 i0"), bytes.fromhex("810e0064"))
        self.assertEqual(encode("CMU.CP.32.U32.F32 i31 i31"), bytes.fromhex("81fe3f64"))
        for source in ("CMU.CP.32.U32.F32 i32 i0", "CMU.CP.32.U32.F32 i0 i32",
                       "CMU.CP.32.U32.F32 i0 v0", "CMU.CP.32.U32.F32 i0 i1.0",
                       "CMU.CP.32.U32.F32 i0 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

        for operation in ("LSU1.STI.16.F32.F16 i8 i9", "LSU1.STI.16 i8.0 i9", "LSU1.STI.32 i8 i9"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AssemblyError, "write port 3"):
                encode("CMU.CP.32.U32.F32 i0 i1 || " + operation)

    def test_cmu_float_to_unsigned_saturating_conversion(self) -> None:
        self.assertEqual(encode("CMU.CP.32.F32.U32S i0 i0"), bytes.fromhex("81040064"))
        self.assertEqual(encode("CMU.CP.32.F32.U32S i31 i31"), bytes.fromhex("81f43f64"))
        for source in ("CMU.CP.32.F32.U32S i32 i0", "CMU.CP.32.F32.U32S i0 i32",
                       "CMU.CP.32.F32.U32S i0 v0", "CMU.CP.32.F32.U32S i0 i1.0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for operation in ("LSU1.STI.16.F32.F16 i8 i9", "LSU1.STI.16 i8.0 i9", "LSU1.STI.32 i8 i9"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AssemblyError, "write port 3"):
                encode("CMU.CP.32.F32.U32S i0 i1 || " + operation)

    def test_cmu_scalar_replication_to_vector(self) -> None:
        self.assertEqual(encode("CMU.CP.128.32.R v0 i0"), bytes.fromhex("81070000"))
        self.assertEqual(encode("CMU.CP.128.32.R v31 i31"), bytes.fromhex("81f73f00"))
        for source in ("CMU.CP.128.32.R v32 i0", "CMU.CP.128.32.R v0 i32",
                       "CMU.CP.128.32.R i0 i1", "CMU.CP.128.32.R v0.0 i1",
                       "CMU.CP.128.32.R v0 v1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

        for operation in ("VAU.MUL.F32", "VAU.ADD.F32", "VAU.SUB.F32", "VAU.OR"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AssemblyError, "same vector register"):
                encode("CMU.CP.128.32.R v0 i1 || " + operation + " v0 v2 v3")

    def test_cmu_full_vector_copy(self) -> None:
        self.assertEqual(encode("CMU.CP.128 v0 v0"), bytes.fromhex("810c0048"))
        self.assertEqual(encode("CMU.CP.128 v31 v31"), bytes.fromhex("81fc3f48"))
        for source in ("CMU.CP.128 v32 v0", "CMU.CP.128 v0 v32",
                       "CMU.CP.128 i0 v1", "CMU.CP.128 v0.0 v1", "CMU.CP.128 v0 i1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "same vector register"):
            encode("CMU.CP.128 v0 v1 || VAU.OR v0 v2 v3")

    def test_lsu0_full_vector_copy(self) -> None:
        self.assertEqual(encode("LSU0.CP.128 v0 v0"), bytes.fromhex("82070048"))
        self.assertEqual(encode("LSU0.CP.128 v31 v31"), bytes.fromhex("82f73f48"))
        for source in ("LSU0.CP.128 v32 v0", "LSU0.CP.128 v0 v32",
                       "LSU0.CP.128 i0 v1", "LSU0.CP.128 v0.0 v1", "LSU0.CP.128 v0 i1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "same vector register"):
            encode("LSU0.CP.128 v0 v1 || VAU.OR v0 v2 v3")

    def test_lsu1_full_vector_copy(self) -> None:
        self.assertEqual(encode("LSU1.CP.128 v0 v0"), bytes.fromhex("89070048"))
        self.assertEqual(encode("LSU1.CP.128 v31 v31"), bytes.fromhex("89f73f48"))
        for source in ("LSU1.CP.128 v32 v0", "LSU1.CP.128 v0 v32",
                       "LSU1.CP.128 i0 v1", "LSU1.CP.128 v0.0 v1", "LSU1.CP.128 v0 i1"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "same vector register"):
            encode("LSU1.CP.128 v0 v1 || VAU.OR v0 v2 v3")

    def test_lsu0_scalar_byte_lane_load(self) -> None:
        self.assertEqual(encode("LSU0.LD.8 i0.0 i0"), bytes.fromhex("820d0004"))
        self.assertEqual(encode("LSU0.LD.8 i31.3 i31"), bytes.fromhex("82fdff04"))
        for source in ("LSU0.LD.8 i32.0 i0", "LSU0.LD.8 i0.4 i0",
                       "LSU0.LD.8 i0 i1", "LSU0.LD.8 v0.0 i1", "LSU0.LD.8 i0.0 i32"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "write port 4"):
            encode("LSU0.LD.8 i4.0 i5 || LSU1.LD.64 i8 i9")

    def test_lsu1_scalar_halfword_lane_load(self) -> None:
        self.assertEqual(encode("LSU1.LD.16 i0.0 i0"), bytes.fromhex("890d0002"))
        self.assertEqual(encode("LSU1.LD.16 i31.3 i31"), bytes.fromhex("89fdff02"))
        for source in ("LSU1.LD.16 i32.0 i0", "LSU1.LD.16 i0.4 i0",
                       "LSU1.LD.16 i0 i1", "LSU1.LD.16 v0.0 i1", "LSU1.LD.16 i0.0 i32"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "write port 5"):
            encode("LSU0.LD.64 i4 i5 || LSU1.LD.16 i8.0 i9")
        with self.assertRaisesRegex(AssemblyError, "read port 6"):
            encode("CMU.CMII.I32 i0 i1 || LSU1.LD.16 i8.0 i9")

    def test_cmu_scalar_float_maximum(self) -> None:
        self.assertEqual(encode("CMU.MAX.F32 i0 i0 i0"), bytes.fromhex("c104004000"))
        self.assertEqual(encode("CMU.MAX.F32 i31 i31 i31"), bytes.fromhex("c1f4ff4700"))
        for source in ("CMU.MAX.F32 i32 i0 i0", "CMU.MAX.F32 i0 i32 i0",
                       "CMU.MAX.F32 i0 i0 i32", "CMU.MAX.F32 i0 i1 0", "CMU.MAX.F32 v0 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for operation in ("LSU1.LDO.32 i8 i9 0", "LSU1.LD.16 i8.0 i9", "LSU1.ST.32 i8 i9"):
            with self.subTest(operation=operation), self.assertRaisesRegex(AssemblyError, "read port 6"):
                encode("CMU.MAX.F32 i0 i1 i2 || " + operation)
        with self.assertRaisesRegex(AssemblyError, "write port 3"):
            encode("CMU.MAX.F32 i0 i1 i2 || LSU1.STI.32 i8 i9")

    def test_cmu_scalar_float_minimum(self) -> None:
        self.assertEqual(encode("CMU.MIN.F32 i0 i0 i0"), bytes.fromhex("c105004000"))
        self.assertEqual(encode("CMU.MIN.F32 i31 i31 i31"), bytes.fromhex("c1f5ff4700"))
        for source in ("CMU.MIN.F32 i32 i0 i0", "CMU.MIN.F32 i0 i32 i0",
                       "CMU.MIN.F32 i0 i0 i32", "CMU.MIN.F32 i0 i1 0", "CMU.MIN.F32 v0 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        with self.assertRaisesRegex(AssemblyError, "read port 6"):
            encode("CMU.MIN.F32 i0 i1 i2 || LSU1.LD.32 i8 i9")
        with self.assertRaisesRegex(AssemblyError, "write port 3"):
            encode("CMU.MIN.F32 i0 i1 i2 || LSU1.STI.32 i8 i9")

    def test_cmu_scalar_half_to_float_conversion(self) -> None:
        self.assertEqual(encode("CMU.CP.32.F16.F32 i0 i0.0"), bytes.fromhex("81010068"))
        self.assertEqual(encode("CMU.CP.32.F16.F32 i31 i31.1"), bytes.fromhex("81f17f68"))
        for source in ("CMU.CP.32.F16.F32 i32 i0.0", "CMU.CP.32.F16.F32 i0 i32.0",
                       "CMU.CP.32.F16.F32 i0 i0.2", "CMU.CP.32.F16.F32 i0 i1",
                       "CMU.CP.32.F16.F32 i0 v1.0"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

    def test_lsu1_postincrement_byte_lane_store(self) -> None:
        self.assertEqual(encode("LSU1.STI.8 i0.0 i0"), bytes.fromhex("89090084"))
        self.assertEqual(encode("LSU1.STI.8 i31.3 i31"), bytes.fromhex("89f9ff84"))
        for source in ("LSU1.STI.8 i32.0 i0", "LSU1.STI.8 i0.4 i0",
                       "LSU1.STI.8 i0 i1", "LSU1.STI.8 v0.0 i1", "LSU1.STI.8 i0.0 i32"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)
        for operation, port in (("CMU.CMII.I32 i0 i1", "read port 6"),
                                ("CMU.CP.32.U32.F32 i0 i1", "write port 3"),
                                ("LSU0.STO.64 i4 i5 0", "read port 9")):
            with self.subTest(operation=operation), self.assertRaisesRegex(AssemblyError, port):
                encode(operation + " || LSU1.STI.8 i8.0 i9")

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
