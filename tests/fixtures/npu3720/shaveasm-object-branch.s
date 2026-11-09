.code .text.branch
.type branch,@function
branch:
    BRU.BRA .Ldestination
    NOP 4
    LSU0.LDIL i4 1
    NOP
.Ldestination:
    NOP
.size branch, .-branch
.code .text.mixed
.type mixed,@function
mixed:
    IAU.XOR i5 i6 i7 || BRU.BRA .Lmixed
    NOP 6
.Lmixed:
    NOP
.size mixed, .-mixed
.end
