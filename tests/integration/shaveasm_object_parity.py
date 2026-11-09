"""Compare authored object fixtures with the developer-only moviAsm oracle."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.shaveasm.elf import compare_sections
from tools.shaveasm.oracle import Oracle

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/npu3720"


def main() -> None:
    """Assemble fixtures with the CLI and compare every section and complete object."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-dir", type=Path, required=True)
    parser.add_argument("--movitools-dir", type=Path, required=True)
    args = parser.parse_args()
    oracle = Oracle(args.native_dir, args.movitools_dir)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="shaveasm-parity-") as directory:
        for source in sorted(FIXTURES.glob("shaveasm-object-*.s")):
            output = Path(directory) / (source.stem + ".o")
            subprocess.run(
                [sys.executable, "-m", "tools.shaveasm.asm", str(source), "-o", str(output)],
                cwd=ROOT,
                check=True,
                timeout=30,
            )
            vendor = oracle.assemble(source.read_text(encoding="utf-8"))
            native = output.read_bytes()
            differences = compare_sections(vendor, native)
            exact = vendor == native
            print(f"{source.name}: section_differences={differences}, exact_bytes={exact}")
            failures += bool(differences) or not exact
    if failures:
        raise SystemExit(f"object parity failed for {failures} fixture(s)")


if __name__ == "__main__":
    main()
