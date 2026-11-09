.file "authored-text.s"
.nowarn
.code .text.entry
.align 16
.type entry,@function
entry:
    CMU.CP.32 i1 i2
    LSU0.LDIL i4 1 || IAU.XOR i5 i5 i5
    NOP 16
    LSU1.LDIL i6 2 || SAU.ADD.i32 i7 i8 3 || PEU.PC1C EQ
.Ldone:
    NOP 6
.size entry, .Ldone-entry
.nowarnend
.end
