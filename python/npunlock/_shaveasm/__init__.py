"""Resolve the shared assembler sources only in an uninstalled checkout."""

from __future__ import annotations

from pathlib import Path

_source = Path(__file__).resolve().parents[3] / "tools" / "shaveasm"
if not (_source / "__init__.py").is_file():
    raise ImportError("native SHAVE assembler sources are missing")
__path__ = [str(_source)]
