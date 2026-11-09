.section .text.alpha,"ax",@progbits
.global alpha
.type alpha,@function
alpha:
    NOP
    .align 4
.size alpha, .-alpha
.section .const,"a",@progbits
    .byte 1, 2
.section .data.beta,"aw",@progbits
.global beta
beta:
    .long alpha
.end
