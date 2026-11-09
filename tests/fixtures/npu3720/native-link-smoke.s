.section .text.controlled_act,"ax",@progbits
.global controlled_act
.type controlled_act,@function
controlled_act:
    BRU.JMP i30
    .byte 0x50
    .long controlled_act
    .align 16
.size controlled_act,16
