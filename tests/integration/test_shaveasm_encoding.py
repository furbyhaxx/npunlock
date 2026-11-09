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
                       "SAU.SHL.X32 i0 i0 i1"):
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

    def test_float_multiply_uses_scalar_registers_in_the_sau_class(self) -> None:
        self.assertEqual(encode("SAU.MUL.F32 i0 i0 i0"), bytes.fromhex("3c040020"))
        self.assertEqual(encode("SAU.MUL.f32 i31 i31 i31"), bytes.fromhex("3ce4ff2f"))
        self.assertEqual(encode("SAU.MUL.F32 i1 i2 i3"), bytes.fromhex("3c448421"))
        for source in ("SAU.MUL.F32 i0 i1 0.5", "SAU.MUL.F32 i32 i0 i0",
                       "SAU.MUL.F32 i0 i0 i32", "SAU.MUL.F16 i0 i1 i2"):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                encode(source)

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
                       "LSU0.LD.32 i0 i1 0", "LSU0.LD.32.f16.f32 i0 i1"):
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
