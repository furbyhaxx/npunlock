# Private assembler source bridge

- Keep assembler implementation in `tools/shaveasm/`; follow its `AGENTS.md`.
- This initializer sets only the private package search path for source checkouts. Wheel builds map this package directly to `tools/shaveasm/` in `setup.py`.
- Keep installed-wheel and source-only import checks aligned; never expose a top-level `tools` package in wheels.
