.code .text.x
    BRU.BRA .Ltarget
.code .text.y
    NOP 16
.code .text.x
    NOP 5
    NOP
.Ltarget:
.section .text.z,"ax",@progbits
    BRU.BRA external
.section .text.z,"ax",@progbits
    NOP 6
    .align 4
.end
