.code .text.work
.local local
.type local,@function
local:
    NOP
.type work,@function
work:
    NOP
.Lmark:
    NOP
.data .rodata4.table
.align 4
.type table,@object
table:
    .long local+2
    .long work
    .long .Lmark
.size table, .-table
.end
