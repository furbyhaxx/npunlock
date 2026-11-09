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

As individual vendor instructions, the same operations produce `82220100` and
`86b29402`, exactly matching the individual native encodings. Thus the native
object path concatenates correctly encoded slot bytes while the vendor packs
the issue packet differently (seven bytes versus eight). A return-only
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

## Independent native parser and packet encoder

The follow-up implementation in `tools/shaveasm/` is independent stdlib Python;
no third-party assembler or encoding table was imported. It remains a development
library, not a complete `.s` -> `.o` assembler or a selectable toolchain mode.
`parser.py` preserves directives and labels, strips comments without damaging
quoted strings, and joins inline/continued packets without rescheduling.
`encoding.py` fails closed outside the measured instruction forms below.
`oracle.py` uses the existing bounded native process launcher and Wine worker,
including correct ownership/release of the stage response buffers.

### Measured scalar packing model

For the six measured instruction forms, vendor output has these properties:

1. Operations are encoded in canonical order **CMU, LSU0, LSU1, SAU, IAU, PEU**,
   independent of textual order. Symbolic `BRU.BRA` is measured between IAU and
   PEU (see below); VAU order remains unmeasured.
2. Each standalone operation has an eight-bit prefix followed by its payload.
   In a packet, the individual prefixes are replaced by **one combined prefix**.
3. The combined prefix occupies **8, 16 or 24 bits** for the measured shapes.
   All 56 combinations of one through four of these six forms were derived.
   The complete measured `(width, value)` mapping is `_PREFIXES` in
   `tools/shaveasm/encoding.py`; it is an encoding-rule table, not a vendor
   object or captured instruction stream.
4. Payloads are concatenated **least-significant first at bit granularity**.
   Only the completed packet is zero-padded to a whole number of bytes, then
   emitted little-endian. Padding each instruction separately is incorrect.
5. Prefix selection depends on the instruction encoding classes; the current
   table must not be generalized to arbitrary instructions on those units.

For example, LSU0.LDIL has a 24-bit payload and IAU.XOR a 20-bit payload.
Their packet has an eight-bit prefix `0xaa` and 44 payload bits: 52 bits total,
rounded to seven bytes. Adding PEU.PC1C after IAU.XOR starts its eight-bit
payload immediately after the 20-bit XOR payload, not on a byte boundary.

The table was derived by encoding each operation independently, removing its
low eight prefix bits, arranging the payloads in canonical order, and finding
the unique header width making the combined vendor word equal those payloads.
Each observed shape had exactly one width among 4, 8, ..., 32 bits. Randomized
operands, textual permutations and full scalar register sweeps independently
checked the resulting model.

Payload fields below use least-significant-bit offsets **after removing the
standalone eight-bit prefix**; `d`, `s`, `l`, `r` are five-bit register numbers:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `CMU.CP.32 d s` | 24 | `0x08000c + (d<<9) + (s<<4)` | `0x81` |
| `LSU0.LDIL d imm16` | 24 | `2 + (d<<3) + (imm16<<8)` | `0x82` |
| `LSU1.LDIL d imm16` | 24 | same payload expression | `0x89` |
| `SAU.ADD.i32 d s imm5` | 24 | `0x100000 + (d<<10) + (s<<5) + (imm5<<15)` | `0x3c` |
| `IAU.XOR d l r` | 20 | `0x12 + (d<<10) + (l<<5) + (r<<15)` | `0x86` |
| `PEU.PC1C condition` | 8 | `0xb + (condition<<4)` | `0x85` |

The measured immediates are unsigned; other forms/ranges are rejected.
Predicate selectors are EQ=1, NEQ=14, LT=4, LTE=5, GT=2, GTE=3.
Register sweeps cover `i0..i31`; this is encoding parity, not a new claim about
hardware safety or register ABI.

`NOP` and `BRU.NOP` without a count encode as `0x07`. Explicit `NOP n` is
**different**: each full group of 16 slots emits `0xf0`; a remaining 1..15 slots
emits `(remaining-1)<<4`. In particular `NOP 1` is `0x00`, `NOP 6` is `0x50`,
and `NOP 17` is `f0 00`. Counted runs 1..64 were compared to moviAsm. These
measurements do not yet define all context-sensitive branch-delay compression.

The vendor analyzer retains write-back hazard state across `.code` switches:
adjacent standalone SAU/IAU register-sweep cases writing the same register
reported conflicting writes despite being in different sections. Each generated
case now has a separate preceding `NOP 16` padding section. This makes cases
independent without disabling the vendor analyzer or changing tested packets.

### Symbolic branch packets

Operand and combined-header sweeps against moviAsm establish the extended order
**CMU, LSU0, LSU1, SAU, IAU, BRU, PEU** for `BRU.BRA symbol`. The 24-bit BRU
payload follows IAU without byte padding and precedes PEU. For each of the 57
combinations of zero through four scalar slots, a search over branch positions
and header widths 4, 8, ..., 32 found exactly one matching layout. The encoder
retains the **52** branch shapes at or below its current 128-bit packet limit;
those prefixes are explicitly recorded in `_PREFIXES`, never inferred from unit
names. Some vendor packets exceed this limit and remain rejected.

| Form | Payload bits | Initial payload | Standalone prefix |
| --- | ---: | --- | --- |
| `BRU.BRA symbol` | 24 | `floor(b/8)` in low 16 bits; upper eight bits zero | `0xc7` |

Here `b` is the packet-relative bit offset of the branch payload. Standalone
`b=8` initializes the field to 1. After a 16-bit header and one LSU payload,
`b=40` initializes it to 5. Following IAU, `b` can be four bits into a byte;
the field is still 16 bits and the upper eight payload bits remain zero.

`encode_packet_with_fixups(packet)` returns `(bytes, tuple[Fixup, ...])`.
`Fixup(symbol, addend, bit_offset, bit_width, kind)` is immutable and its offset
is packet-relative, least-significant-bit first. The byte-only `encode_packet`
continues to reject any packet requiring relocation.

| Field placement | Vendor relocation number | `Fixup.kind` | Width |
| --- | ---: | --- | ---: |
| `b % 8 == 0` | 209 | `R_SHAVE_PCREL16` | 16 |
| `b % 8 == 4` | 210 | `R_SHAVE_PCREL16_AT4` | 16 |

Vendor `.rela` entries place `r_offset` at `floor(b/8)` and have addend zero.
The initialized field compensates for relocation's byte-relative `P`; object
writers must retain it rather than replacing it with zero. Both data bytes and
symbol/addend/field placement/kind are checked by `packet_diff`. Names here match
the locally named, measured relocation types in `lld-shave.patch`; the vendor
objects themselves provide numeric types only. Targets are restricted to plain
symbol names. A probe of `target+2` treated that entire token as a symbol,
not an arithmetic addend, so expression syntax remains rejected. Calls, resolved
branch distances, delay compression and VAU classes remain unmeasured.

### Differential gates and corpus inventory

Cached assembly can be inventoried without Wine or recompilation:

```sh
python3 -m tools.shaveasm.coverage /mnt/cache/build-shave/native-asm-corpus \
  /mnt/cache/build-shave/native-dynamic-example-corpus
```

The JSON report groups rejected packets by mnemonic and operand shape, counting
one occurrence per shape per packet. `unsupported_packets` identifies forms that
also fail alone; `rejected_packets` includes supported forms co-issued with an
unsupported form or header class. Counts overlap across shapes and must not be
summed as packet totals. Parse failures are reported separately and fail the
command. The combined baseline is 3291/11912 accepted packets and **98** distinct
mnemonics (97 in the literal corpus alone). With symbolic branches, coverage is
4017/11912 packets, including 726 requiring symbolic fixups. `accepted_packets`
counts bytes-plus-fixups support and `relocatable_packets` identifies that subset;
this does not assert whole-object parity.

```sh
python3 -m unittest discover -s tests/integration -p 'test_shaveasm_*.py'
python3 -m tools.shaveasm.packet_diff --native-dir build/linux \
  --movitools-dir "$NPUNLOCK_MOVITOOLS_DIR" \
  --output /mnt/cache/build-shave/native-packets-3720-v3 --seed 3720 --count 1000
python3 -m tools.shaveasm.packet_diff --native-dir build/linux \
  --movitools-dir "$NPUNLOCK_MOVITOOLS_DIR" \
  --output /mnt/cache/build-shave/native-packets-9001 --seed 9001 --count 1000
python3 -m tools.shaveasm.corpus --native-dir build/linux \
  --movitools-dir "$NPUNLOCK_MOVITOOLS_DIR" \
  --output /mnt/cache/build-shave/native-asm-corpus
```

Offline regressions: 17 passed. With symbolic branches, each randomized gate
passed **1400/1400** packets (seeds 3720 and 9001): 1000 random packets, 108
shapes, 224 register/predicate/branch sweep cases, three immediate boundaries,
and 65 bare/counted NOP cases. Every generated packet's
actual bytes are compared to moviAsm, not merely round-tripped through native
code. The six instruction forms all occur in the real compiler corpus.

Original C, compiler `.s`, vendor `.o` and JSON manifests stay under the cache
paths above. `elf.py` provides bounded ELF32 section inspection and a comparator
which reports every section-attribute or byte difference while ignoring only
file offsets. There are **no whole-object native parity results yet** because
the native object writer, expressions, symbol/relocation lowering and remaining
instruction classes are not implemented.

The captured corpus has **55 distinct complete kernel sources**: 39 literal
sources (including all seven contrib `.c` kernels) and 16 generated variants
from the three dynamic example files. Those variants cover per-row scalar
`f16/f32/u16/u32` in both operand positions, scalar-first in those four types,
and scalar/row unsigned broadcasts in `u16/u32`. The reviewed pure generator
functions were called in isolation, without running application bodies or NPU
inference; their originals and manifests are in
`/mnt/cache/build-shave/native-dynamic-example-corpus/`.

All 35 example files containing `controlled_act` are represented. The initial
literal scan also attempted a one-line entry fragment in the XGBoost generator,
which correctly failed compilation; discovery now reports it as dynamic input
rather than a complete source. Model-dependent XGBoost sources remain
uncaptured and require explicit model/generator inputs.

The parser structurally accepted all 55 captured assemblies. The literal
corpus contains 97 distinct mnemonics. Only **3291/11912** parsed packets are
accepted by the original byte-only encoder across the two corpora; the symbolic
branch extension raises bytes-plus-fixups support to **4017/11912**. These are
syntactic coverage counts, **not** full-stream or whole-object parity claims.
Calls, other branch forms, additional instruction/header classes, data and
alignment directives, ELF symbols and relocations remain the next gate. Hybrid
worker/config/cache integration and new-mode doctor/NPU acceptance must wait
for whole-corpus object parity. The existing default and prior linker-only
hardware evidence are unchanged; no branch push is justified yet.
