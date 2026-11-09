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
measurements define NOP bytes; branch delay-window metadata additionally depends
on the following packets, as described below.

The vendor analyzer retains write-back hazard state across `.code` switches:
adjacent standalone SAU/IAU register-sweep cases writing the same register
reported conflicting writes despite being in different sections. Each generated
case now has a separate preceding `NOP 16` padding section. This makes cases
independent without disabling the vendor analyzer or changing tested packets.

### Scalar indirect load

Independent destination/base sweeps through `i0..i31` establish:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `LSU0.LD.32 d a` | 24 | `0x1000d + (d<<4) + (a<<9)` | `0x82` |

All **181** current 24-bit `LSU0` header shapes match with LD.32 substituted for
LDIL, including branch, store and predicate packets. The randomized gate selects
both forms and explicitly checks all 181 LD.32 shapes plus 64 independent register
cases. Conversion suffixes have different payload/header classes and remain
unsupported; the bare mnemonic must not be generalized to them.

### Scalar signed immediate increment

Sweeping `i0..i31`, positive/negative immediate bits and both range boundaries
establishes the read-modify-write form:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `IAU.INCS d imm14` | 24 | `3 + (d<<5) + ((imm14 & 0x3fff)<<10)` | `0xc6` |

The immediate is signed **-8192..8191**; moviAsm rejects both adjacent values.
All **168** current `IAU.ADD24` header shapes were independently compared with
INCS substituted for SHL. Each preserves its prefix and 24-bit payload boundary,
including branch and store packets. The randomized gate selects INCS, repeats
all 168 shapes explicitly, and includes 32 register cases plus 31 signed
immediate cases. Register increments and three-operand forms remain unsupported.

### Scalar low-word multiply

Independent sweeps of all three registers through `i0..i31` establish:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `IAU.LMULL d l r` | 20 | `0x04 + (d<<10) + (l<<5) + (r<<15)` | `0x86` |

The 96 register-field cases and all **180** existing 20-bit IAU header shapes
matched moviAsm, including branch and PCCX packets. LMULL reuses the measured
`IAU` class without changing ordering or padding. Positive and negative immediate
operands were rejected by moviAsm and remain unsupported. The randomized gate
selects LMULL and explicitly repeats every measured IAU shape with it.

### Scalar signed-offset store

Independent `i0..i31` sweeps of both registers, offset-bit sweeps and signed
range boundaries establish:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `LSU1.STO.32 v a offset15` | 32 | `0x14006 + (v<<4) + (a<<9) + ((offset15 & 0x7fff)<<17)` | `0xc9` |

Offsets are signed -16384..16383, without scaling; both out-of-range neighbors
were rejected by moviAsm. Header derivation across **277** combinations of the
measured non-LSU1 classes found unique layouts. The **150** shapes at or below
128 bits are retained explicitly as class `LSU1.STO32`; LSU1 keeps its original
position before SAU. AND, SHL and CMU comparison variants are additionally
checked in the randomized gate wherever their resource usage allows co-issue.

moviAsm rejects **CMU.CMII.I32/U32 + LSU1.STO.32** on scalar read port `IRFrp6`, even
with disjoint registers; CP.32 + STO.32 with those same registers is accepted.
The native encoder rejects this measured conflict without changing scheduling.
The generator selects CP.32 for store-containing CMU packets and never silently
reschedules a conflicting CMII packet. This is a specific measured conflict,
not a general functional-unit legality model.

### Scalar signed and unsigned register comparison

Independent sweeps of both operands through `i0..i31` establish:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `CMU.CMII.I32 l r` | 24 | `0x10000 + (l<<4) + (r<<9)` | `0x81` |
| `CMU.CMII.U32 l r` | 24 | `(l<<4) + (r<<9)` | `0x81` |

The first source occupies the low register field, unlike CP.32's destination.
All **124** measured legal CMU 24-bit header shapes matched when either CMII.I32
or CMII.U32 replaced CP.32, including mixed branch/PCCX classes. Each form has
64 independent register-field sweeps; unsigned comparison clears payload bit 16.
The randomized gate chooses all three forms and explicitly repeats the 124
legal shapes with each comparison form. Both comparison variants conflict with
STO.32 on scalar read port 6 and are rejected in those packets. Immediate
comparisons remain unmeasured.

### Scalar immediate left shift

Both register fields were swept separately through `i0..i31`, and every shift
amount 0..31 was measured:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `IAU.SHL d s imm5` | 24 | `0x80000c + (d<<10) + (s<<5) + (imm5<<15)` | `0xc6` |

moviAsm rejected both -1 and 32. All **131** measured `IAU.ADD24` header shapes
were independently compared with SHL substituted for ADD; every header and
24-bit payload boundary remained unchanged. The class name records its original
measured ADD form, not a restriction to that mnemonic. Random packets now choose
SHL as well as both ADD forms, with 96 dedicated operand sweeps and all 131 SHL
header shapes repeated explicitly. Register-controlled shifts remain rejected.

### Scalar bitwise AND and OR

Sweeping each of the three register operands independently through `i0..i31`
establishes:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `IAU.AND d l r` | 20 | `0x10 + (d<<10) + (l<<5) + (r<<15)` | `0x86` |
| `IAU.OR d l r` | 20 | `0x11 + (d<<10) + (l<<5) + (r<<15)` | `0x86` |

Every one of the **140** measured header shapes containing the 20-bit IAU class
was independently checked with AND substituted for XOR. All retained the same
prefix and bit layout, including branches and twelve-bit PCCX suffixes. The
random generator selects both mnemonics, and explicitly repeats all 140 shapes
with AND plus the 96 individual register-field sweeps. Immediate AND forms remain
unmeasured and rejected. OR was independently swept through all 96 register-field
cases. With the store extension, every one of the **180** current 20-bit IAU
header shapes is explicitly tested with each of AND and OR, alongside randomized
selection among XOR/AND/OR. Immediate OR remains rejected.

### Predicate cross-condition

All six predicates crossed with every immediate 0..63 were compared to moviAsm:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `PEU.PCCX condition imm6` | 12 | `1 + (condition<<2) + (imm6<<6)` | `0xc5` |

The selectors are EQ=1, **NEQ=6**, LT=4, LTE=5, GT=2, GTE=3. NEQ differs from
PC1C's selector 14 and must not be shared. The immediate is unsigned six-bit;
moviAsm rejected 64. Standalone byte padding obscures this class's width:
co-issuing IAU.XOR proves the payload is **12**, rather than 16 bits. For example,
`IAU.XOR i16 i17 i18 || PEU.PCCX NEQ 63` is `ed 32 42 99 fd`, not a padded
six-byte packet. Header sweeps of 172 combinations of measured non-PEU classes
yielded unique layouts. The **135** shapes at or below 128 bits are explicitly
retained as class `PEU.PCCX12`. PEU remains after BRU in the canonical order.

### Scalar compare against zero

A complete `i0..i31` source-register sweep establishes:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `CMU.CMZ.I32 s` | 16 | `s<<4` | `0x41` |

`CMU.CMZ16` is a distinct header class from 24-bit CMU.CP.32. Co-issuing with
LSU0.LDIL uses prefix `0x94`, with the load starting after 16 CMU bits. Header
sweeps of 128 combinations of the already measured non-CMU classes each yielded
one matching layout; the **104** at or below 128 bits are explicitly retained.
Scalar compare variants other than this signed zero form remain rejected.

### Scalar integer addition

Separate sweeps of all three register fields and immediate bit/range boundaries
establish these forms, with a common 24-bit payload/header class:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `IAU.ADD d l r` | 24 | `(d<<10) + (l<<5) + (r<<15)` | `0xc6` |
| `IAU.ADD d l imm8` | 24 | `0x800000 + (d<<10) + (l<<5) + (imm8<<15)` | `0xc6` |

Immediate values are unsigned 0..255; negative operands were rejected by moviAsm.
Unlike IAU.XOR's 20-bit class, both ADD forms use `_Operation.prefix_class`
`IAU.ADD24`. Both were measured independently against each of **83** combinations
of zero through four other slots, including either LSU0.LDIL or LSU0.LDO.32.
Each pair had the same unique header; **68** shapes at or below 128 bits are
retained in `_PREFIXES`. Payload order is unchanged, but subsequent branch and
PEU fields move by four bits relative to XOR, changing branch relocation kind
where necessary. No arithmetic mnemonic other than the explicitly measured ADD
forms is accepted by inference from these fields.

### Signed scalar load offsets

Register sweeps `i0..i31` for each operand, positive/negative immediate bit sweeps,
and range boundaries establish this additional class:

| Form | Payload bits | Payload expression | Standalone prefix |
| --- | ---: | --- | --- |
| `LSU0.LDO.32 d s offset15` | 32 | `0x14002 + (d<<4) + (s<<9) + ((offset15 & 0x7fff)<<17)` | `0xc2` |

Offsets are signed **-16384..16383**, in source units without scaling. Both
out-of-range neighbors were rejected by moviAsm. This is a different header
class from LSU0.LDIL: `_Operation.prefix_class` distinguishes `LSU0.LDO32`
while functional-unit conflict detection and ordering still use physical LSU0.
Combined-header sweeps with zero through four other measured scalar/branch slots
found unique 8/16/24-bit headers for all 57 shapes. The **42** shapes at or below
128 bits are retained explicitly in `_PREFIXES`. For example, sharing IAU.XOR
uses eight-bit prefix `0xba`, rather than LDIL/XOR's `0xaa`; the 32-bit load
payload precedes XOR's 20 bits. Sharing BRU updates the branch field position and
initial byte-offset bias normally. LSU1 loads and other load sizes remain
unmeasured and rejected.

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
| `BRU.BRA symbol` | 24 | `floor(b/8) + (delay_span<<16)` | `0xc7` |

Here `b` is the packet-relative bit offset of the branch payload. Standalone
`b=8` initializes the field to 1. After a 16-bit header and one LSU payload,
`b=40` initializes it to 5. Following IAU, `b` can be four bits into a byte;
the relocation field is still 16 bits. The upper eight payload bits record the
following delay window's byte span, independently of the relocation.

`encode_packet_with_fixups(packet, following=...)` returns
`(bytes, tuple[Fixup, ...])`. `following` must contain the remaining packets in
the same code section; the empty default describes an isolated/end-of-section
packet. A whole-stream writer must pass the actual suffix rather than relying
on that default. `Fixup(symbol, addend, bit_offset, bit_width, kind)` is immutable
and its offset is packet-relative, least-significant-bit first. The byte-only `encode_packet`
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
branch distances and VAU classes remain unmeasured.

#### Branch delay-window byte span

Sweeping counted `NOP 1..32`, repeated bare NOPs, scalar loads and mixed measured
packets establishes the upper BRU byte:

| Following code in the same section | `delay_span` |
| --- | ---: |
| Fewer than six following issue slots | 0 |
| At least six following issue slots | Bytes from the branch packet's end through the encoded packet/byte containing slot six |
| `NOP 1..5` only | 0 |
| `NOP 6..32` | 1 |
| Six bare `NOP` packets | 6 |
| Six `LSU0.LDIL` packets | 24 |
| `NOP 4`, one LDIL, one bare NOP | 6 |

An ordinary packet consumes one issue slot regardless of its number of co-issued
operations. Counted `NOP n` consumes `n` slots; each encoded NOP byte represents
up to 16 slots, so `NOP 17` still ends the six-slot window after its first byte.
The byte span is independent of the BRU payload's bit alignment. For example,
IAU.XOR+BRU followed by NOP6 sets bit 16 of its BRU payload, just as a standalone
BRU does. Its fixup offset/type/addend do not change.

The derivation's 738 repeated/mixed sequences matched every vendor byte. The
randomized gate includes the 1..32 sweep, repeated measured operations, and 1000
random mixed suffixes for each of standalone BRU and IAU.XOR+BRU. Control
transfers inside the first six delay slots fail closed. Non-packet layout
changes inside a delay window remain unmeasured; section boundaries must not be
silently treated as ordinary packet boundaries.

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
mnemonics (97 in the literal corpus alone). With symbolic branches, signed
loads/stores, indirect loads, integer addition, comparisons, PCCX, AND/OR,
LMULL, INCS and immediate SHL, coverage is **8501/11912** packets, including
799 requiring symbolic fixups.
Twenty-one distinct mnemonics occur in accepted packets (six at baseline); the
corpus still has 98 mnemonics.
`accepted_packets` counts bytes-plus-fixups support and `relocatable_packets`
identifies that subset. Coverage tests isolated packet forms; it does not
validate whole-stream branch suffixes or assert whole-object parity.

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

Offline regressions: 32 passed. Each randomized gate passed **6789/6789 cases**
(seeds 3720 and 9001): the original 2362 isolated-packet cases (1000 random
packets, 457 shapes, 352 mixed operand sweeps, 96 ADD sweeps, 384 PCCX pairs,
eight immediate boundaries and 65 NOP cases), plus 64 counted-NOP branch
suffixes, 168 repeated-operation suffixes and 2000 random mixed branch suffixes.
An additional 140 AND header cases and 96 individual register sweeps cover AND;
131 SHL header cases and 96 operand sweeps cover immediate SHL. CMII.I32 adds
124 header cases and 64 independent register sweeps. STO.32 adds 150 header
classes, 32 mixed store sweeps, 64 register-field sweeps, five boundaries and
77 additional AND/SHL header cases. OR adds 180 header cases and 96 operand
sweeps. CMII.U32 adds 124 legal header cases and 64 register-field sweeps.
LMULL adds 180 header cases and 96 independent register-field sweeps.
INCS adds 168 header cases, 32 register cases and 31 signed immediate cases.
LSU0.LD.32 adds 181 header cases and 64 independent register-field cases.
The current total is 607 prefix shapes.
Every case's full instruction bytes and fixups are compared to moviAsm, not
merely round-tripped through native code. All measured instruction forms occur
in the real compiler corpus.

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
branch, scalar-load/store, ADD, compare, PCCX, AND/OR, LMULL, INCS and SHL extensions raise
bytes-plus-fixups support to **8501/11912**. These are
syntactic coverage counts, **not** full-stream or whole-object parity claims.
Calls, other branch forms, additional instruction/header classes, data and
alignment directives, ELF symbols and relocations remain the next gate. Hybrid
worker/config/cache integration and new-mode doctor/NPU acceptance must wait
for whole-corpus object parity. The existing default and prior linker-only
hardware evidence are unchanged; no branch push is justified yet.
