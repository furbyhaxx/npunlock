# Native SHAVE assembly

- Stdlib Python only; preserve vendor scheduling rather than adding a legalizer.
- `parser.py` preserves vendor labels/directives and packet boundaries; `encoding.py` encodes only explicitly measured scalar classes.
- `elf.py` inspects/compares sections; it does not emit objects. Keep object parity separate from supported-packet counts.
- `oracle.py` is a developer-only MoviTools bridge through the existing bounded native worker transport.
- `packet_diff.py` generates isolated random packets; `corpus.py` captures literal source sites and reports dynamic-input gaps.
- Keep captured vendor assembly, objects and ELF corpora under `/mnt/cache/build-shave`, never in git.
- Add offline tests using independently authored assembly; verify encoding changes against moviAsm and document rules in `../../wiki/NATIVE_TOOLCHAIN.md`.
- Fail closed on unsupported syntax or instruction forms. Passing a subset is not whole-corpus compatibility.
