# SHAVE linker patch

- `lld-shave.patch` targets upstream `llvmorg-14.0.0`; retain both MIT and LLVM notices.
- Update `PROVENANCE` and `../../wiki/NATIVE_TOOLCHAIN.md` when changing the patch or pin.
- Keep proprietary MoviTools DLLs, archives, generated vendor objects and linked ELFs out of this tree.
- The external assembler is a research dependency, not a packaged or selected compiler mode.
