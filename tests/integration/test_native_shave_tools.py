"""Offline native assembler/linker smoke; requires explicitly selected external tools."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def verify_tools(assembler: Path, linker: Path) -> None:
    case = unittest.TestCase()
    with tempfile.TemporaryDirectory(prefix="npunlock-native-smoke-") as directory:
        obj = Path(directory) / "kernel.o"
        elf = Path(directory) / "kernel.elf"
        subprocess.run(
            [
                sys.executable,
                str(assembler),
                "obj",
                str(ROOT / "tests/fixtures/npu3720/native-link-smoke.s"),
                "--exact",
                "-o",
                str(obj),
            ],
            check=True,
            timeout=30,
        )
        subprocess.run(
            [
                str(linker),
                "-flavor",
                "gnu",
                "-EL",
                "-e",
                "controlled_act",
                "-z",
                "max-page-size=0x10",
                "--gc-sections",
                "-T",
                str(ROOT / "src/shavecc/shave_kernel.ld"),
                str(obj),
                "-o",
                str(elf),
            ],
            check=True,
            timeout=30,
        )
        data = elf.read_bytes()
        case.assertEqual(data[:7], b"\x7fELF\x01\x01\x01")
        case.assertEqual(struct.unpack_from("<HHI", data, 16), (2, 2, 1))
        case.assertEqual(struct.unpack_from("<I", data, 24)[0], 0x1D000000)
        shoff = struct.unpack_from("<I", data, 32)[0]
        shsize, count, names_index = struct.unpack_from("<HHH", data, 46)
        case.assertEqual(shsize, 40)
        headers = [struct.unpack_from("<10I", data, shoff + n * shsize) for n in range(count)]
        names_header = headers[names_index]
        names = data[names_header[4] : names_header[4] + names_header[5]]
        sections = {names[h[0] : names.index(b"\0", h[0])].decode(): h for h in headers}
        text = sections[".text"]
        case.assertEqual(text[3], 0x1D000000)
        case.assertEqual(text[2] & 6, 6)
        case.assertEqual(
            data[text[4] : text[4] + text[5]],
            bytes.fromhex("47f101500000001d0000000000000000"),
        )
        case.assertFalse(any(h[1] in (4, 9) for h in headers))
        symbols = sections[".symtab"]
        case.assertEqual(symbols[9], 16)
        symbol_names_header = headers[symbols[6]]
        strings = data[symbol_names_header[4] : symbol_names_header[4] + symbol_names_header[5]]
        entries = [
            struct.unpack_from("<IIIBBH", data, offset) for offset in range(symbols[4], symbols[4] + symbols[5], 16)
        ]
        entry = next(s for s in entries if strings[s[0] : strings.index(b"\0", s[0])] == b"controlled_act")
        case.assertEqual(entry[1:4], (0x1D000000, 16, 0x12))
        case.assertNotEqual(entry[5], 0)
    print("native assembler/linker smoke: PASS (ELF32 LE EM_SPARC, entry/text/symbol, ABS32, no relocations)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembler", type=Path, required=True)
    parser.add_argument("--linker", type=Path, required=True)
    args = parser.parse_args()
    verify_tools(args.assembler.resolve(), args.linker.resolve())


if __name__ == "__main__":
    main()
