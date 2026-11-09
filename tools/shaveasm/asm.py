"""Assemble the measured vendor SHAVE syntax into an ELF32 object."""

from __future__ import annotations

import argparse
from pathlib import Path

from .objwriter import assemble
from .parser import AssemblyError


def main() -> None:
    """Write an object only after the complete source assembles successfully."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        obj = assemble(args.source.read_text(encoding="utf-8"))
        args.output.write_bytes(obj)
    except (AssemblyError, OSError, UnicodeError) as error:
        parser.exit(1, f"{args.source}: {error}\n")


if __name__ == "__main__":
    main()
