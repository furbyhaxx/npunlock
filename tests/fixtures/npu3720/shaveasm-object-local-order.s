.type .Ideclared,@function
.code .text.main
.type entry,@function
entry:
    LSU0.LDIH i1 .Isecond
    LSU0.LDIH i2 .Ifirst
    LSU0.LDIH i3 .Imissing
    NOP
.size entry, .-entry
.code .text.first
.type .Ifirst,@function
.Ifirst:
    NOP
.Ideclared:
    NOP
.type .Ilate,@function
.Ilate:
    NOP
.Lmark:
    NOP
.code .text.second
.type .Isecond,@function
.Isecond:
    NOP
.data .data.ptrs
.align 4
    .long .Isecond
    .long .Ifirst
    .long .Ilate
    .long .Lmark
    .long .Ilastmissing
.end
