.code .text.main
.type main,@function
main:
    NOP
.size main, .-main
.code .text.helper
.type .Ihelper,@function
.Ihelper:
    NOP
.size .Ihelper, .-.Ihelper
.data .rodata4.ptrs
.align 4
.type ptrs,@object
ptrs:
    .long .Ihelper+4
    .long main
    .long external
.size ptrs, .-ptrs
.end
