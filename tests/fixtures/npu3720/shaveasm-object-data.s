.data .rodata4.items
.align 4
.type items,@object
items:
    .word 0x12345678
    .long external
    .long external+4
    .byte 0x12, 0x34
    .short 0xabcd
    .float 1.25
    .fill 2, 3, 0x123456
    .ascii "A\n"
.size items, .-items
.end
