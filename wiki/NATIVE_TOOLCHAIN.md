# Native SHAVE assembler and linker

## Status and scope

The Linux default is still the full MoviTools toolchain under Wine. **There is
no selectable hybrid mode yet.** On 2026-11-09, native linking was validated
on NPU3720 (`8086:ad1d`), but the published Python assembler failed the vendor
assembly compatibility gate. Do not advertise the linker-only experiment as
replacement of both assembler and linker.

The intended interface is C -> Wine `moviCompile -S` -> native assembler ->
native `ld.lld` -> existing native patchblob and inference. The compiler and
`mlibm.a` remain proprietary. The archive is a native link input, not a program
executed by Wine. No vendor payload is bundled here.

## Pinned native linker

`third_party/npunlock-work/PROVENANCE` records the imported patch, licenses and
audit limits. Only the seven-file lld patch was imported from
[lallolapalooza/npunlock-work](https://github.com/lallolapalooza/npunlock-work)
commit `8e58dd384847b6df613fea97112c44aed4bb6dfb`. No fork, binary, pickle or
encoding table is bundled. The patch targets upstream LLVM `llvmorg-14.0.0`,
peeled commit `329fda39c507e8740978d10458451dcdb21563be`.

Reproduced build (CMake, Ninja, Git, C++ compiler and Python required):

```sh
repo="$PWD"
mkdir -p /mnt/cache/build-shave
cd /mnt/cache/build-shave
git clone --depth 1 --branch llvmorg-14.0.0 --filter=blob:none --sparse \
  https://github.com/llvm/llvm-project.git llvm-project
cd llvm-project
git sparse-checkout set llvm lld cmake libunwind/include
test "$(git rev-parse HEAD)" = 329fda39c507e8740978d10458451dcdb21563be
patch --dry-run -p1 < "$repo/third_party/npunlock-work/lld-shave.patch"
patch -p1 < "$repo/third_party/npunlock-work/lld-shave.patch"
cmake -G Ninja -S llvm -B ../lld-build \
  -DCMAKE_BUILD_TYPE=Release -DLLVM_ENABLE_ASSERTIONS=ON \
  -DLLVM_ENABLE_PROJECTS=lld -DLLVM_TARGETS_TO_BUILD=X86 \
  -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF \
  '-DCMAKE_CXX_FLAGS=-include cstdint -include limits' \
  -DCMAKE_INSTALL_PREFIX=/opt/shave-lld
cmake --build ../lld-build --target lld -j8
sudo install -d /opt/shave-lld/bin
sudo install -m755 ../lld-build/bin/lld /opt/shave-lld/bin/ld.lld
/opt/shave-lld/bin/ld.lld --version
```

The explicit standard headers are needed with GCC 16's standard library:
LLVM 14 otherwise fails compiling `SmallVector.h` with missing `uint64_t`.
`libunwind/include` supplies a Mach-O header used when building lld's driver,
even though these experiments link only ELF. No LLVM source workaround beyond
the saved SHAVE patch was applied. Version output was `LLD 14.0.0 (compatible
with GNU linkers)`.

Link a SHAVE object using exactly the kernel layout and GC policy:

```sh
/opt/shave-lld/bin/ld.lld -flavor gnu -EL -e controlled_act \
  -z max-page-size=0x10 --gc-sections -T src/shavecc/shave_kernel.ld \
  kernel.o "$NPUNLOCK_MOVITOOLS_DIR/lib/mlibm.a" -o kernel.elf
```

Do not use the system's unpatched lld or a normal SPARC assembler. EM_SPARC is
this container's machine identifier; SHAVE instructions are not SPARC ISA.

## Offline regression

`tests/fixtures/npu3720/native-link-smoke.s` is independently authored source;
it contains no vendor output. The test requires an explicit external assembler
checkout at the pinned npunlock-work revision, with `shave_asm.py` and its
`encodings.json` adjacent. It does not download anything or use MoviTools.

```sh
python3 tests/integration/test_native_shave_tools.py \
  --assembler /mnt/cache/build-shave/npunlock-work/shave-isa/shave_asm.py \
  --linker /opt/shave-lld/bin/ld.lld
```

Observed: `native assembler/linker smoke: PASS`. This checks ELF32 LE
ET_EXEC/EM_SPARC, entry and executable text at `0x1d000000`, exact 16-byte text,
the global function symbol, absolute 32-bit relocation resolution, and absence
of remaining relocation sections. It is an opt-in standalone test, not a new
CTest dependency. It proves a small assembler-supported dialect, not compiler
output compatibility. Python dependencies are stdlib only.

## Assembler compatibility gate

The published assembler uses only stdlib imports. Its default legalizer changes
load/branch padding, LSU choices and other scheduling decisions. `--exact`
disables those rewrites; preserving vendor scheduling is a separate requirement
from parsing the vendor syntax.

Measured with both actual compiler outputs:

| Kernel | Assembly bytes | Vendor object bytes | Native `obj --exact` |
| --- | ---: | ---: | --- |
| README/example GELU FP32 | 8039 | 1625 | `line 1: unknown mnemonic /*` |
| Graph-global five-input FP16 | 3590 | 832 | `line 1: unknown mnemonic /*` |

Removing only the leading C block comment exposes `unknown mnemonic NOP`
(GELU line 15; five-input line 17 in the comment-stripped text). Inspection also
shows that the native parser ignores `.code` section switches, splits operands
on commas instead of vendor whitespace, and does not merge continuation lines
beginning with `||`. Unknown directives are silently ignored, so a successful
exit alone cannot prove correct code.

More importantly, syntax normalization is insufficient. An independently
authored two-operation packet gave:

```text
Vendor source:
    LSU0.LDIL i4 1
        || IAU.XOR i5 i5 i5
Vendor packet bytes: aa220100b29402

Native source (same operations, normalized syntax):
    LSU0.LDIL i4,1 || IAU.XOR i5,i5,i5
Native --exact bytes: 8222010086b29402
```

The native object path concatenates separately encoded slot bytes. The vendor
packs the issue packet differently (seven bytes versus eight). A return-only
control did match: `BRU.JMP i30` followed by vendor `NOP 6` or native
`.byte 0x50` produced `47f10150`. No mismatching packet was executed on hardware.
A correct vendor-dialect parser **and packet encoder**, including predicate and
compressed-NOP handling, are required before wiring selectable mode/config,
worker timeouts, cache identity and doctor. The assembler and its recovered
tables were deliberately not adopted before that gate.

## Verified ELF and relocation observations

Both real kernels, still assembled by moviAsm, were linked with the native lld
and compared against moviLLD outputs using `readelf -hSWl`, `-sW`, `-rW` and
section-byte comparisons:

| Property | GELU | Five-input |
| --- | ---: | ---: |
| Vendor/native file bytes | 53856 / 53852 | 972 / 964 |
| `.text` bytes, identical | 992 | 336 |
| `.arg.data` address/size | `0x1e000000` / 0 | same |
| Entry / `.text` address | `0x1d000000` | same |
| Symbol/string tables | identical | identical |
| Remaining relocation sections | none | none |

The `.comment` shrinks from 61 to 54 bytes: the truthful native banner replaces
`Movidius Linker (moviLLD) v3.0.9` with `npunlock shave-lld v0.1.0`, both based
on LLD 14.0.0. Subsequent nonallocated offsets and section-header offsets shift
by four bytes (GELU) or eight (five-input), including alignment effects.
Five-input has no other section-content differences.

GELU retains nonallocated library DWARF. Native linking changes bytes in
`.debug_loc` (63), `.debug_info` (2533), `.debug_ranges` (712), `.debug_line`
(9), and `.debug_frame` (35). Every changed byte is zero in the vendor output;
native output has nonzero address/offset values there, consistent with applied
debug fixups. These sections are not executable or allocated and do not change
patchblob's kernel image. Detailed vendor debug-relocation policy and each
individual debug fixup are not established by this comparison.

GELU object relocations directly observed: 200 (`0xc8`) and 202 (`0xca`) for
`tanhf` address materialization; 209 (`0xd1`) for branches. Five-input has six
209 relocations. The authored offline fixture exercises 208 (`0xd0`). The
patch's recovered formulas are `S+A` low/high 16, absolute 32, and `S+A-P`
added to a prefilled PC-relative field. Offsets can point inside a variable-size
instruction. Types 201/203/204-207/210 are implemented by the patch but not
independently covered here; 211-214 are unsupported in relocation application.
No dynamic linking/PLT validation is claimed.

## ABI groundwork for a future LLVM backend

The vendor assembly and successful native-link NPU runs establish these narrow
facts for these kernels:

- The C entry's layer-parameter argument arrives in `i18`; generated prologues
  use `i19` as the stack pointer and save/restore `i30` for a math call.
- GELU materializes `tanhf` in `i30` with paired LSU high/low loads, then calls
  through `BRU.SWP i30`; the argument/result is in `i18`. Return uses
  `BRU.JMP i30`. This does not establish a complete callee-save ABI.
- Operand spelling is whitespace-separated, with case variants such as
  `SAU.MUL.f32`. Symbols and data are sectioned via `.code` directives.
- Packets use continuation `||` lines. Actual compiler output contains four
  operations in some packets: do not impose an unverified three-operation cap.
- `NOP`, `NOP n`, PEU predicates and packed branch/packet control need explicit
  encoding support. Do not substitute instruction concatenation or re-run a
  heuristic legalizer over already scheduled vendor output.
- Existing NPU3720 invocation-layout, precision and patchblob validation remain
  unchanged. ELF machine identity alone is not a sufficient ABI check.

For the linker-only experiment, a temporary harness injected each saved native
ELF at `NativeLibraries.compile_shave`, asserted the exact original source and
one compile call, then ran the unmodified examples. Results: GELU maximum
absolute error `2.38419e-07`; five-input matched all 32 values exactly, copied
and shared buffers. This is **not** end-to-end hybrid compilation: both compiler
and assembler still ran under Wine offline. The unchanged default
`python -m npunlock doctor --full` passed 32-element FP16 add-one with zero
mismatches. Doctor in a new mode is not implemented or validated.
