# AEC ISA & PTX Input Specification

## 1. Input Language

The compiler accepts a restricted NVIDIA PTX ISA 9.3 scalar subset. Each input is a single `.visible .entry` kernel.

### PTX File Structure

```ptx
.version 9.3
.target sm_90
.address_size 64

.visible .entry kernel_name(
    .param .u64 param_a,
    .param .u32 param_n
)
{
    .reg .pred %p<4>;
    .reg .u32  %r<16>;
    .reg .u64  %rd<16>;
    .reg .f32  %f<16>;

LABEL:
    ...
    ret;
}
```

### Supported Directives

| Directive | Description |
|---|---|
| `.version 9.3` | PTX version declaration |
| `.target sm_90` | Target architecture |
| `.address_size 64` | 64-bit address space |
| `.visible .entry` | Kernel entry point |
| `.param` | Kernel parameter declaration |
| `.reg` | Virtual register declaration |
| label | Basic block label / branch target |

### Supported Types

| PTX Type | Use |
|---|---|
| `.pred` | Predicate register |
| `.b32` | 32-bit bit pattern |
| `.b64` | 64-bit bit pattern / pointer |
| `.u32` | 32-bit unsigned integer |
| `.s32` | 32-bit signed integer |
| `.u64` | 64-bit pointer / address |
| `.f32` | FP32 scalar |

### Memory Spaces

| Space | Use |
|---|---|
| `.gmem` | Global memory (load/store) |
| `.pmem` | Parameter memory (kernel arguments) |

---

## 2. AEC Opcodes

### Default Profile (`c1_default`)

| Opcode | Mnemonic | Description |
|---|---:|---|
| `0x0001` | `ADD` | Integer / FP32 addition |
| `0x0002` | `SUB` | Integer / FP32 subtraction |
| `0x0003` | `MUL` | Integer / FP32 multiplication |
| `0x0004` | `MAD` | Multiply-add (non-fused) |
| `0x0005` | `FMA` | Fused multiply-add (single rounding) |
| `0x0010` | `AND` | Bitwise AND |
| `0x0011` | `OR` | Bitwise OR |
| `0x0012` | `XOR` | Bitwise XOR |
| `0x0014` | `SHL` | Left shift |
| `0x0015` | `SHR` | Logical right shift |
| `0x0021` | `CMPP` | Compare and write predicate |
| `0x0030` | `LD` | Load from memory |
| `0x0031` | `ST` | Store to memory |
| `0x0040` | `BR` | Unconditional branch |
| `0x0041` | `BRX` | Predicated branch |
| `0x0045` | `HALT` | Terminate thread / lane |
| `0x0054` | `CPY` | Register copy / special register read |
| `0x0055` | `LOADI` | Load 32-bit immediate |
| `0x0056` | `LOADI64` | Load 64-bit immediate |

### Type Codes

| Code | Type |
|---:|---|
| `0x0` | `.b32` |
| `0x1` | `.b64` |
| `0x2` | `.u32` |
| `0x3` | `.s32` |
| `0x8` | `.f32` |
| `0xf` | `.none` |

---

## 3. Instruction Encoding

Each AEC instruction is 128 bits, stored as four little-endian 32-bit words (w0, w1, w2, w3).

```
bits [127:112]  Opcode      16 bits
bits [111:96]   Pred/Ctrl   16 bits
bits [95:80]    Dest        16 bits
bits [79:64]    Src1        16 bits
bits [63:32]    Src2/Imm32  32 bits
bits [31:0]     ImmExt      32 bits
```

File write order: `w0, w1, w2, w3` (each little-endian `uint32_t`).

### Pred/Ctrl Field

| Bits | Name | Description |
|---:|---|---|
| `[2:0]` | `pred` | Predicate register index (P0–P7) |
| `[6:3]` | `type` | Type code |
| `[10:8]` | `subop` | Compare subop / memory space |
| `[14]` | `pred_neg` | Predicate negate |
| `[15]` | `pred_en` | Predicate enable |

Predicate execution:
```
execute_lane = active_lane && (!pred_en || (P[pred] XOR pred_neg))
```

### Compare Subop Encoding

| Code | Op |
|---:|---|
| `0` | `.eq` |
| `1` | `.ne` |
| `2` | `.lt` |
| `3` | `.le` |
| `4` | `.gt` |
| `5` | `.ge` |

### Special Register Selectors

| Selector | Register |
|---:|---|
| `0x0100` | `%tid.x` |
| `0x0101` | `%ntid.x` |
| `0x0102` | `%ctaid.x` |
| `0x0103` | `%nctaid.x` |
| `0x0104` | `%laneid` |
| `0x0110` | `%tid.y` |
| `0x0111` | `%ntid.y` |
| `0x0112` | `%ctaid.y` |
| `0x0113` | `%nctaid.y` |
| `0x0120` | `%tid.z` |
| `0x0121` | `%ntid.z` |
| `0x0122` | `%ctaid.z` |
| `0x0123` | `%nctaid.z` |

---

## 4. Parameter ABI

PTX `.param` maps to AEC `.pmem` by declaration order with natural alignment.

| Type | Size | Align |
|---|---:|---:|
| `.u32` / `.s32` / `.b32` / `.f32` | 4 | 4 |
| `.u64` / `.b64` / pointer | 8 | 8 |

Parameter block total size is aligned to 8 bytes.

### Example

```ptx
.visible .entry vector_add(
    .param .u64 param_a,
    .param .u64 param_b,
    .param .u64 param_c,
    .param .u32 param_n
)
```

| Parameter | Offset | Size |
|---|---:|---:|
| `param_a` | 0 | 8 |
| `param_b` | 8 | 8 |
| `param_c` | 16 | 8 |
| `param_n` | 24 | 4 |
| padding | 28 | 4 |

---

## 5. Address ABI

- All addresses are byte addresses
- `.gmem`: byte address (global memory)
- `.pmem`: byte offset (parameter memory)
- 64-bit PTX pointers: low 32 bits used as AEC address (high 32 bits must be zero)
- `.u64` / `.b64` virtual registers map to two consecutive AEC GPRs (low, high)
- R255 cannot be the low register of a 64-bit pair

---

## 6. PTX-to-AEC Lowering Table

| PTX | AEC |
|---|---|
| `mov.u32 dst, %tid.x` | `CPY.u32 dst, %tid.x` |
| `mov.u32 dst, %ntid.x` | `CPY.u32 dst, %ntid.x` |
| `mov.u32 dst, %ctaid.x` | `CPY.u32 dst, %ctaid.x` |
| `mov.u32 dst, %nctaid.x` | `CPY.u32 dst, %nctaid.x` |
| `mov.u32 dst, %laneid` | `CPY.u32 dst, %laneid` |
| `mov.u32 dst, imm` | `LOADI dst, imm32` |
| `mov.u64 dst, imm` | `LOADI64 dst, imm64` |
| `mov.b32/u32 dst, src` | `CPY.b32/u32 dst, src` |
| `add.u32` | `ADD.u32` |
| `sub.u32` | `SUB.u32` |
| `mul.lo.u32` | `MUL.u32` |
| `mad.lo.u32` | `MAD.u32` |
| `mul.wide.u32` | `MUL.u32 low + LOADI high=0` |
| `add.u64` | `ADD.u32 low + LOADI high=0` |
| `and.b32` | `AND.b32` |
| `or.b32` | `OR.b32` |
| `xor.b32` | `XOR.b32` |
| `shl.b32` | `SHL.u32` |
| `shr.u32` | `SHR.u32` |
| `add.f32` / `add.rn.f32` | `ADD.f32` |
| `sub.f32` / `sub.rn.f32` | `SUB.f32` |
| `mul.f32` / `mul.rn.f32` | `MUL.f32` |
| `mad.f32` / `mad.rn.f32` | `MAD.f32` |
| `fma.rn.f32` | `FMA.f32` |
| `setp.eq/ne/lt/le/gt/ge.u32` | `CMPP.u32.eq/ne/lt/le/gt/ge` |
| `bra label` | `BR label` |
| `@%p bra label` | `BRX P, label` |
| `@!%p bra label` | `BRX !P, label` |
| `ld.param.u32/b32` | `LOADI offset + LD.pmem.u32/b32` |
| `ld.param.u64/b64` | two `LD.pmem.u32` |
| `ld.global.f32/u32/b32` | `LD.gmem.f32/u32/b32` |
| `st.global.f32/u32/b32` | `ST.gmem.f32/u32/b32` |
| `ret` | `HALT` |

---

## 7. `.aecbin` Format

Raw AEC 128-bit instruction stream — no header, no sections, no symbol table.

Requirements:
- File size is a multiple of 16 bytes
- At least one instruction
- Entry PC defaults to 0
- All labels resolved at compile time
- All opcodes, types, memory spaces, registers, and predicates within bounds

---

## 8. Test Manifest

Each test case is a directory containing `kernel.ptx` and `manifest.json`.

```json
{
  "kernel": "vector_add",
  "gridDim": [4096, 1, 1],
  "blockDim": [256, 1, 1],
  "dynamic_smem_bytes": 0,
  "params": [
    {"name": "param_a", "type": "u64", "kind": "gmem_ptr", "buffer": "a"},
    {"name": "param_b", "type": "u64", "kind": "gmem_ptr", "buffer": "b"},
    {"name": "param_c", "type": "u64", "kind": "gmem_ptr", "buffer": "c"},
    {"name": "param_n", "type": "u32", "kind": "value", "value": 1048576}
  ],
  "buffers": {
    "a": {"dtype": "f32", "numel": 1048576, "init": "rand_uniform"},
    "b": {"dtype": "f32", "numel": 1048576, "init": "rand_uniform"},
    "c": {"dtype": "f32", "numel": 1048576, "init": "zero", "output": true}
  },
  "check": {
    "type": "vector_add",
    "output": "c",
    "atol": 1e-6,
    "rtol": 1e-6
  }
}
```

| Field | Description |
|---|---|
| `kernel` | Kernel name |
| `gridDim` | Grid dimensions |
| `blockDim` | Block dimensions |
| `dynamic_smem_bytes` | Dynamic shared memory bytes |
| `params` | Kernel parameters |
| `buffers` | Global memory buffer initialization |
| `check` | Output correctness check rules |
