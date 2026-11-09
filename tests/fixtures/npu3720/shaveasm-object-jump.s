.code .text.jump
.type jump,@function
jump:
    BRU.JMP i30
    NOP 4
    LSU0.LDIL i4 1
    NOP
.size jump, .-jump
.code .text.jumpmixed
.type jumpmixed,@function
jumpmixed:
    IAU.XOR i5 i6 i7 || BRU.JMP i30
    NOP 6
.size jumpmixed, .-jumpmixed
.end
