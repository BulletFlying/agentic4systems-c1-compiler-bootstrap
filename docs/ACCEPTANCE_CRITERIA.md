# C1 完整验收标准

本文档定义 C1 编译器从 M0 到最终交付的**全部验收条件**。每一项必须可验证、可证伪。来源：官方 `spec.md`、`scoring.md`、`C1_PROJECT_CHARTER.md`、`EVALUATION.md` 及 2026-07-14 主办方勘误。

---

## 证据层级

| Tier | 含义 | 要求 |
|------|------|------|
| 0 | 静态证据 | compileall、import graph、架构 guardrail |
| 1 | 单元证据 | parser 行为、encoder 字段、analysis 缓存、pass 排序、report 确定性 |
| 2 | 可执行本地证据 | 本地模拟器差分测试、O0/O2 二进制回归、public manifest harness |
| 3 | 官方 CModel 证据 | `aec-precise` 运行通过，记录精确命令和输出 |
| 4 | 性能模型证据 | 静态 report 对比、baseline vs candidate 对比 |

**铁律**：未运行 `aec-precise` 不得声称 "official correctness passed"。

---

## M0：ISA、CLI 与编码器基础

### M0.1 指令编码

- [ ] **M0.1.1** 所有 C1 合法 opcode 可确定性编码为 128-bit AEC 指令
- [ ] **M0.1.2** 所有合法 type code（.b32/.b64/.u32/.s32/.f32/.none）正确写入 Pred/Ctrl[6:3]
- [ ] **M0.1.3** 所有合法 memory space code（.gmem/.smem/.cmem/.lmem/.pmem）正确写入 Pred/Ctrl[13:11]
- [ ] **M0.1.4** Predicate 字段（pred_en, pred_neg, pred[2:0]）正确编码
- [ ] **M0.1.5** `shl.b32` 输入编码为 `SHL.u32`（2026-07-14 勘误），`AND/OR/XOR.b32` 保持 `.b32` 不变
- [ ] **M0.1.6** LOADI64 寄存器对约束：不允许 R255 为 low register，base 必须 ≤ 254
- [ ] **M0.1.7** 非法 opcode/type/space/register 组合显式抛出 `EncodeError`

### M0.2 二进制输出

- [ ] **M0.2.1** `.aecbin` 输出为 raw 128-bit 指令流，无 Header/Data/Reloc/Symbol
- [ ] **M0.2.2** 每条指令按 `w0, w1, w2, w3` 小端序 uint32 写入
- [ ] **M0.2.3** 文件大小为 16 字节的正整数倍
- [ ] **M0.2.4** 至少包含一条指令（空文件非法）
- [ ] **M0.2.5** 所有 label 在写入前已解析为绝对指令索引
- [ ] **M0.2.6** 所有 branch target 在 `[0, program_instructions)` 范围内

### M0.3 CLI 与工具

- [ ] **M0.3.1** `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json` 可执行
- [ ] **M0.3.2** `disassembler/aec-objdump output.aecbin` 可反汇编并输出可读格式
- [ ] **M0.3.3** 编译器入口可以是脚本/Python（官方确认 `python3` 可用）
- [ ] **M0.3.4** 编译超时 < 180 秒（官方硬限制）

### M0.4 测试

- [ ] **M0.4.1** 编码-解码往返测试（encoder→decoder 字段一致）
- [ ] **M0.4.2** LOADI64 往返测试
- [ ] **M0.4.3** `shl.b32→SHL.u32` 编码类型字段验证
- [ ] **M0.4.4** 非法字段组合拒绝测试

---

## M1：T1 基础 Lowering（正确性）

### M1.1 PTX 解析

- [ ] **M1.1.1** 正确解析 `.version 9.3`、`.target sm_90`、`.address_size 64`
- [ ] **M1.1.2** 正确解析 `.visible .entry kernel_name(...)` 及参数列表
- [ ] **M1.1.3** 正确解析 `.reg .pred %p<N>`、`.reg .u32 %r<N>`、`.reg .s32 %s<N>`、`.reg .u64 %rd<N>`、`.reg .b32 %b<N>`、`.reg .b64 %bd<N>`、`.reg .f32 %f<N>`
- [ ] **M1.1.4** 正确解析 label 声明（`LABEL:`）
- [ ] **M1.1.5** 正确解析所有 PTX 指令形式（见 spec.md §3 完整列表）
- [ ] **M1.1.6** 不支持的 directive/指令显式报错，不静默忽略

### M1.2 参数 ABI（PMEM）

- [ ] **M1.2.1** `.param` 按声明顺序映射到 `.pmem` byte offset
- [ ] **M1.2.2** 自然对齐：`.u32/.s32/.b32/.f32` 对齐 4 字节，`.u64/.b64/pointer` 对齐 8 字节
- [ ] **M1.2.3** 参数块总大小向上取整到 8 字节
- [ ] **M1.2.4** `ld.param.u32/b32` → `LOADI offset; LD.pmem.u32/b32`
- [ ] **M1.2.5** `ld.param.u64/b64` → 两次 `LD.pmem.u32`（低 32 位 + 高 32 位）
- [ ] **M1.2.6** 参数名在编译时解析为 `.pmem` byte offset

### M1.3 特殊寄存器

- [ ] **M1.3.1** `mov.u32 dst, %tid.x/y/z` → `CPY.u32 dst, selector`
- [ ] **M1.3.2** `mov.u32 dst, %ntid.x/y/z` → `CPY.u32 dst, selector`
- [ ] **M1.3.3** `mov.u32 dst, %ctaid.x/y/z` → `CPY.u32 dst, selector`
- [ ] **M1.3.4** `mov.u32 dst, %nctaid.x/y/z` → `CPY.u32 dst, selector`
- [ ] **M1.3.5** `mov.u32 dst, %laneid` → `CPY.u32 dst, selector`
- [ ] **M1.3.6** selector 编码使用正确的 16-bit 值（0x0100-0x0123）

### M1.4 整数 / 位运算 / 移位

- [ ] **M1.4.1** `add.u32/sub.u32` → `ADD.u32/SUB.u32`
- [ ] **M1.4.2** `mul.lo.u32` → `MUL.u32`
- [ ] **M1.4.3** `mad.lo.u32` → `MAD.u32`（Rd, Rs1, Rs2, Rs3 四操作数形式）
- [ ] **M1.4.4** `and.b32/or.b32/xor.b32` → `AND.b32/OR.b32/XOR.b32`
- [ ] **M1.4.5** `shl.b32` → `SHL.u32`（2026-07-14 勘误，编码类型字段为 .u32）
- [ ] **M1.4.6** `shr.u32` → `SHR.u32`

### M1.5 FP32 运算

- [ ] **M1.5.1** `add.f32 / add.rn.f32` → `ADD.f32`
- [ ] **M1.5.2** `sub.f32 / sub.rn.f32` → `SUB.f32`
- [ ] **M1.5.3** `mul.f32 / mul.rn.f32` → `MUL.f32`
- [ ] **M1.5.4** `mad.f32 / mad.rn.f32` → `MAD.f32`
- [ ] **M1.5.5** `fma.rn.f32` → `FMA.f32`

### M1.6 比较与分支

- [ ] **M1.6.1** `setp.eq/ne/lt/le/gt/ge.u32` → `CMPP.u32.subop`（subop 0-5）
- [ ] **M1.6.2** `bra LABEL` → `BR target_pc`
- [ ] **M1.6.3** `@%p bra LABEL` → `BRX P, target_pc`（pred_neg=0）
- [ ] **M1.6.4** `@!%p bra LABEL` → `BRX P, target_pc`（pred_neg=1）
- [ ] **M1.6.5** `ret` → `HALT`
- [ ] **M1.6.6** BRX 仅在 uniform predicate 或 proven-uniform 时生成（2026-07-14 勘误）
- [ ] **M1.6.7** 不实现 reconvergence stack / warp-divergent branch 支持

### M1.7 全局内存访问

- [ ] **M1.7.1** `ld.global.f32/u32/b32 dst, [addr]` → `LD.gmem.type Rd, [Ra]`
- [ ] **M1.7.2** `st.global.f32/u32/b32 [addr], src` → `ST.gmem.type [Ra], Rs`
- [ ] **M1.7.3** 64-bit 指针仅使用低 32-bit 作为 byte address（32-bit abstract address rule）
- [ ] **M1.7.4** 高位 32-bit 在测试保证下恒为零

### M1.8 64-bit / 地址计算

- [ ] **M1.8.1** PTX `.u64/.b64` 虚拟寄存器 → AEC GPR pair（low=Rk, high=Rk+1）
- [ ] **M1.8.2** `mul.wide.u32 dst64, a32, b32` → `MUL.u32` low + `LOADI` high=0
- [ ] **M1.8.3** `add.u64 dst64, a64, b64` → `ADD.u32` low + `LOADI` high=0
- [ ] **M1.8.4** `mov.u64 dst, imm` → `LOADI64 dst, imm64`（或两次 LOADI）
- [ ] **M1.8.5** `mov.b32/u32/b64 dst, src` → `CPY.type dst, src`
- [ ] **M1.8.6** R255 不得作为 64-bit pair 的 low register

### M1.9 测试

- [ ] **M1.9.1** 所有 5 个公开 T1-T5 manifest 编译通过并本地模拟器执行正确
- [ ] **M1.9.2** PMEM ABI 单元测试：声明顺序、自然对齐、8 字节块对齐、类型尺寸表
- [ ] **M1.9.3** Uniform + negated-uniform BRX 编码测试
- [ ] **M1.9.4** 至少一个 divergent branch 负面测试（验证不应支持）
- [ ] **M1.9.5** y/z 维度特殊寄存器可用
- [ ] **M1.9.6** 公开测试中参数/寄存器/标签重命名后仍正确
- [ ] **M1.9.7** `aec-precise` 至少对 T1 公开测试运行过一次并记录结果

---

## M2：T2 标量优化

### M2.1 CFG / 控制流正确性

- [ ] **M2.1.1** CFG 正确构建：基本块识别、前驱/后继边、支配树
- [ ] **M2.1.2** 循环识别（回边检测 + 循环头/体/出口）
- [ ] **M2.1.3** Uniformity 分析：对每条分支指令给出 UNIFORM / NON_UNIFORM / UNKNOWN
- [ ] **M2.1.4** `UNKNOWN` 绝不等于 `UNIFORM` — 未证明 uniform 的分支不得生成 BRX
- [ ] **M2.1.5** 多基本块 join point、不可达块、重排块的 CFG 正确
- [ ] **M2.1.6** CFG 改写后失效或重算 dominance、loop、def-use、uniformity 分析

### M2.2 死代码消除（DRE + Global DCE）

- [ ] **M2.2.1** Conservative DRE：移除"定义但从未被读"的纯计算指令
- [ ] **M2.2.2** DRE 使用整程序读集（conservative，安全但不完整）
- [ ] **M2.2.3** Global DCE：worklist-based，mark-sweep 算法
- [ ] **M2.2.4** Global DCE 正确处理 multi-def 寄存器（所有 def 都被读才标记为 live）
- [ ] **M2.2.5** 绝不删除 side-effecting 指令（load/store/branch/call/atom/setp）
- [ ] **M2.2.6** 绝不删除 predicated 指令
- [ ] **M2.2.7** 绝不删除 `.cc` modifier 指令
- [ ] **M2.2.8** 绝不删除 predicate destination（setp 结果）
- [ ] **M2.2.9** 寄存器/标签重命名后 DRE 行为不变
- [ ] **M2.2.10** O0 与 O2 本地模拟器等价

### M2.3 公共子表达式消除（CSE）

- [ ] **M2.3.1** BB-local CSE：同一基本块内相同(opcode, operands)的纯计算指令复用结果
- [ ] **M2.3.2** 正确处理中间操作数重定义（redefinition blocks CSE）
- [ ] **M2.3.3** 正确处理目标寄存器在别名使用前被重定义（blocks CSE）
- [ ] **M2.3.4** 不跨 label 边界 CSE
- [ ] **M2.3.5** 不 CSE predicated 指令
- [ ] **M2.3.6** 不 CSE memory / control / setp / unknown / .cc 边界指令
- [ ] **M2.3.7** 寄存器/标签重命名后 CSE 行为不变

### M2.4 常量折叠（Local CF）

- [ ] **M2.4.1** BB-local 常量折叠：两个操作数均为常量立即数时在编译时求值
- [ ] **M2.4.2** u32 常量运算折叠（add/sub/mul/and/or/xor/shl/shr）
- [ ] **M2.4.3** f32 常量运算折叠（含 hex float 立即数）
- [ ] **M2.4.4** f32 overflow 保留原指令（不折叠）
- [ ] **M2.4.5** 寄存器重定义 invalidate 常量
- [ ] **M2.4.6** 不跨 label 边界折叠
- [ ] **M2.4.7** 不折叠 predicated 指令
- [ ] **M2.4.8** 不折叠 memory / control / setp / unknown / .cc 边界指令

### M2.5 循环不变量外提（LICM）— 当前 O3，须提升到 O2

- [ ] **M2.5.1** 识别循环不变量：操作数在循环内不被重定义
- [ ] **M2.5.2** 验证支配性：不变量定义支配所有使用点
- [ ] **M2.5.3** 验证单定义安全：不变量在循环外有唯一定义
- [ ] **M2.5.4** 不提升 side-effecting 指令
- [ ] **M2.5.5** 不提升 predicated 指令
- [ ] **M2.5.6** 循环自由程序（无循环）不误提升
- [ ] **M2.5.7** 提升后所有原始指令仍保留在程序中

### M2.6 基本块合并/简化（Block Simplification）— 当前 O3，须提升到 O2

- [ ] **M2.6.1** 合并仅含无条件跳转的连续基本块
- [ ] **M2.6.2** 删除空基本块（无指令仅有 label→branch）
- [ ] **M2.6.3** 简化不可达基本块
- [ ] **M2.6.4** 简化后 CFG 语义等价
- [ ] **M2.6.5** 分支程序不崩溃

### M2.7 全局常量传播（Global CP）— 当前 O3，须提升到 O2

- [ ] **M2.7.1** 跨基本块边界传播常量赋值
- [ ] **M2.7.2** 在未标记的 CFG 边界正确重置常量
- [ ] **M2.7.3** 循环程序不崩溃
- [ ] **M2.7.4** 收敛（迭代上限 + warning）

### M2.8 M2 验收门禁

- [ ] **M2.8.1** O2 管线中每个 pass 有单元测试、负面测试、差分测试
- [ ] **M2.8.2** O2 vs O0 本地模拟器等价（所有公开 T1-T5）
- [ ] **M2.8.3** 编译报告记录每个 pass 的 changed/detail 指标
- [ ] **M2.8.4** 零 public-case dispatch（无文件名/寄存器名/标签名/立即数特判）
- [ ] **M2.8.5** 无优化 pass 依赖 divergent-BRX 语义
- [ ] **M2.8.6** T2 公开测试在 O2 下指令数可测量地减少
- [ ] **M2.8.7** `aec-precise` 至少对 T2 公开测试运行过一次

---

## M3：T3 内存访问优化

### M3.1 重复全局 Load 复用（已完成）

- [ ] **M3.1.1** 同一基本块内，相同 (address_register, load_type) 的全局 load 复用第一次结果
- [ ] **M3.1.2** Label 边界清空缓存
- [ ] **M3.1.3** Store（任何地址）清空全部缓存
- [ ] **M3.1.4** Branch/ret/brx/call/atom 清空全部缓存
- [ ] **M3.1.5** Predicated 指令清空全部缓存
- [ ] **M3.1.6** 地址寄存器被重定义时删除对应缓存条目
- [ ] **M3.1.7** 不同 load type 不复用（f32 vs u32 不同 key）
- [ ] **M3.1.8** 不同地址寄存器不复用
- [ ] **M3.1.9** 替换后的 mov 指令操作数正确

### M3.2 Load Hoisting（当前缺失，须实现）

- [ ] **M3.2.1** 识别循环不变量全局 load：地址在循环内不变
- [ ] **M3.2.2** 将不变量 load 提升到循环头之前
- [ ] **M3.2.3** 验证提升后无 store/控制流风险：循环内无可写该地址的 store
- [ ] **M3.2.4** 保守 alias 模型：任何 store 视为可能别名，不提升跨 store 的 load
- [ ] **M3.2.5** 不提升 predicated load
- [ ] **M3.2.6** 不提升跨条件分支的 load（控制流边界）
- [ ] **M3.2.7** 提升后本地模拟器等价
- [ ] **M3.2.8** 负面测试：跨 store 不提升、跨 branch 不提升、地址变化不提升

### M3.3 地址计算优化（当前缺失，须实现）

- [ ] **M3.3.1** 识别形如 `mul.wide.u32 + add.u64` 的地址计算模式
- [ ] **M3.3.2** 常量折叠地址计算中的常量偏移
- [ ] **M3.3.3** 复用重复的地址计算子表达式
- [ ] **M3.3.4** 优化后地址计算结果不变（本地模拟器等价）

### M3.4 M3 验收门禁

- [ ] **M3.4.1** 公开 T3 manifest 编译执行正确
- [ ] **M3.4.2** 内存访问模式变化后优化不退化
- [ ] **M3.4.3** 无 unsafe hoisting across stores/control boundaries
- [ ] **M3.4.4** 编译报告含 load_count、store_count、memory_instruction_ratio
- [ ] **M3.4.5** `aec-precise` 至少对 T3 公开测试运行过一次

---

## M4：T4 寄存器分配与指令调度

### M4.1 寄存器分配

- [ ] **M4.1.1** 虚拟 GPR → 物理 GPR 映射（R0-R239 可用，R240-R255 保留给临时寄存器）
- [ ] **M4.1.2** Predicate 独立分配（P0-P7）
- [ ] **M4.1.3** Liveness 分析：计算每个虚拟寄存器的 live range [first_def, last_use]
- [ ] **M4.1.4** Linear-scan 分配：按 first_def 排序，线性扫描分配
- [ ] **M4.1.5** 64-bit pair 约束：连续 even-odd 对（R2/R3），base 必须偶数
- [ ] **M4.1.6** 寄存器压力超限时：尝试 spill（见 M4.2），或 fallback bootstrap
- [ ] **M4.1.7** 无物理寄存器重叠（同一物理寄存器不同时分配给两个虚拟寄存器）
- [ ] **M4.1.8** Lowering 读取 RA 映射，存在时跳过 bootstrap allocator
- [ ] **M4.1.9** 测试：至少 1 个冲突检查测试、1 个 pair 约束测试、1 个压力测试

### M4.2 Spill/Reload（当前缺失，须实现）

- [ ] **M4.2.1** 物理寄存器不足时选择 live range 最长的虚拟寄存器 spill
- [ ] **M4.2.2** Spill：在 def 后 store 到 `.lmem`，在 use 前从 `.lmem` load
- [ ] **M4.2.3** Spill slot 正确分配（不重叠）
- [ ] **M4.2.4** Spill 后 liveness 更新正确
- [ ] **M4.2.5** Spill 后本地模拟器等价
- [ ] **M4.2.6** 测试：至少 1 个 spill 正确性测试

### M4.3 依赖图构建（当前缺失，须实现）

- [ ] **M4.3.1** 构建数据依赖图（DDG）：RAW、WAR、WAW 依赖
- [ ] **M4.3.2** 构建内存依赖：load/store 顺序保持
- [ ] **M4.3.3** 构建控制依赖：分支指令与之前的指令
- [ ] **M4.3.4** DDG 确定性（相同输入 → 相同图）

### M4.4 指令调度（当前缺失，须实现）

- [ ] **M4.4.1** List scheduling：就绪队列 + 拓扑序调度
- [ ] **M4.4.2** 调度保持 DDG 所有依赖边
- [ ] **M4.4.3** Load/compute 交错：将独立计算指令插入 load 延迟槽
- [ ] **M4.4.4** 调度保持内存顺序（load/store 相对顺序不变）
- [ ] **M4.4.5** 调度确定性（相同输入 → 相同调度结果）
- [ ] **M4.4.6** 测试：至少 1 个依赖保持测试、1 个内存顺序测试、1 个确定性测试

### M4.5 M4 验收门禁

- [ ] **M4.5.1** 公开 T4 manifest 编译执行正确
- [ ] **M4.5.2** O2 vs O0 物理寄存器数可测量地减少
- [ ] **M4.5.3** 无物理寄存器重叠（冲突检查通过）
- [ ] **M4.5.4** Pair 约束全部满足
- [ ] **M4.5.5** 编译报告含 register_count、predicate_count、spill_count、estimated_dependency_depth
- [ ] **M4.5.6** `aec-precise` 至少对 T4 公开测试运行过一次

---

## M5：T5 FP32 标量 GEMM

### M5.1 基础正确性（已完成）

- [ ] **M5.1.1** 二维索引计算正确（row = blockIdx.x*blockDim.x + threadIdx.x, col = ...）
- [ ] **M5.1.2** K 维循环 lowering 正确（loop over K with accumulator）
- [ ] **M5.1.3** FP32 全局 load/store 地址计算正确
- [ ] **M5.1.4** FP32 multiply-add 累加正确（MAD 或 FMA 指令）
- [ ] **M5.1.5** 公开 T5 128×128×128 在 1e-4 容差内通过

### M5.2 循环优化（当前缺失，须实现）

- [ ] **M5.2.1** K 循环展开（至少 2x-4x）以减少分支开销
- [ ] **M5.2.2** 循环展开后寄存器重命名正确（无错误复用）
- [ ] **M5.2.3** 累加器寄存器跨展开迭代正确更新
- [ ] **M5.2.4** 展开后本地模拟器等价（多尺寸验证）

### M5.3 Load/Compute 调度（当前缺失，须实现）

- [ ] **M5.3.1** A/B 矩阵 load 交错排列以隐藏延迟
- [ ] **M5.3.2** 将独立计算指令插入 load 延迟槽
- [ ] **M5.3.3** K 循环内 load 和 multiply-add 形成流水线
- [ ] **M5.3.4** 调度后本地模拟器等价

### M5.4 寄存器压力管理（当前缺失，须实现）

- [ ] **M5.4.1** K 循环临时变量（地址增量、循环计数器）紧凑分配
- [ ] **M5.4.2** 累加器占用最少物理寄存器
- [ ] **M5.4.3** 无 spill（在公开 GEMM 尺寸下）
- [ ] **M5.4.4** 多尺寸下不 OOM

### M5.5 M5 验收门禁

- [ ] **M5.5.1** 至少 3 种 GEMM 尺寸编译执行正确（如 64×64×64, 128×128×128, 256×256×256）
- [ ] **M5.5.2** 边界变体正确（M≠N, 奇数尺寸）
- [ ] **M5.5.3** 无越界访问
- [ ] **M5.5.4** 无固定尺寸 pattern dispatch
- [ ] **M5.5.5** 不涉及 Tensor/TMUL/低精度
- [ ] **M5.5.6** 编译报告显示 load_count、store_count、instruction_count 对多尺寸合理
- [ ] **M5.5.7** `aec-precise` 至少对 T5 公开测试运行过一次

---

## 横切需求（全部 M 适用）

### X.1 架构纪律

- [ ] **X.1.1** Analysis 只产生事实，不修改 IR
- [ ] **X.1.2** Pass 显式声明 consumed/preserved/invalidated analyses
- [ ] **X.1.3** CFG 改写后失效或重算相关分析
- [ ] **X.1.4** `compiler.py` 是 facade，不吸收 pass 实现
- [ ] **X.1.5** `legacy_lowering.py` 是兼容边界，新优化不进此文件
- [ ] **X.1.6** 无 analysis→backend 依赖
- [ ] **X.1.7** 无 pass→filename/testcase dispatch
- [ ] **X.1.8** 编译器与模拟器不共享核心语义实现（防自证循环）

### X.2 安全 / 鲁棒性

- [ ] **X.2.1** 零 public-case 语义 dispatch（文件名/寄存器名/标签名/立即数/矩阵尺寸）
- [ ] **X.2.2** 不根据 testcase ID 或 hash 特判
- [ ] **X.2.3** 非法输入显式报错，不静默生成错误二进制
- [ ] **X.2.4** 保守 fallback 优于猜测：不确定时拒绝编译
- [ ] **X.2.5** `legacy_varying_branch_items` 已移除或严格隔离
- [ ] **X.2.6** 不依赖 C2/C3 运行时（CUDA/CuPy/H200/ONNX/C2 libaec_device.so）

### X.3 编译报告

- [ ] **X.3.1** `compile_report.json` 包含 status/input/output/opt_level
- [ ] **X.3.2** 包含 num_ptx_instructions / num_aec_instructions / num_basic_blocks
- [ ] **X.3.3** 包含 num_virtual_registers / num_physical_registers / num_predicates
- [ ] **X.3.4** 包含 spills: {loads, stores}
- [ ] **X.3.5** 包含 passes: {dce, cse, licm, ...} boolean flags
- [ ] **X.3.6** 包含 scheduler 字段（"list" 或 "none"）
- [ ] **X.3.7** 包含 warnings 数组
- [ ] **X.3.8** 报告确定性（相同输入 → 相同 JSON）
- [ ] **X.3.9** 不伪造官方 cycle metric

### X.4 鲁棒性测试基础设施（当前缺失，须建立）

- [ ] **X.4.1** 至少参数规模变化自动化测试
- [ ] **X.4.2** 至少 grid/block 维度变化自动化测试
- [ ] **X.4.3** 至少寄存器重命名自动化测试
- [ ] **X.4.4** 至少基本块顺序变化自动化测试
- [ ] **X.4.5** 至少循环次数变化自动化测试
- [ ] **X.4.6** 至少死代码插入不退化测试
- [ ] **X.4.7** 至少地址计算形式变化测试
- [ ] **X.4.8** 至少 GEMM 尺寸变化测试

---

## 最终交付门禁

在声称 C1 就绪前，仓库必须满足以下全部条件：

### G.1 编译与执行

- [ ] **G.1.1** `compiler/aec-cc kernel.ptx -O2 -o output.aecbin --report compile_report.json` 对全部公开 T1-T5 可运行
- [ ] **G.1.2** 生成的 `.aecbin` 符合 raw 128-bit 指令流格式（含 `shl.b32→SHL.u32` 勘误）
- [ ] **G.1.3** PMEM ABI 和 Address ABI 符合 `spec.md`
- [ ] **G.1.4** 编译超时 < 180 秒
- [ ] **G.1.5** `python3` 环境下可运行（无额外系统依赖）

### G.2 正确性证据

- [ ] **G.2.1** T1-T5 全部公开类别有可执行正确性证据
- [ ] **G.2.2** 至少每个类别 1 个 `aec-precise` 验证记录（精确命令 + 输出）
- [ ] **G.2.3** 本地模拟器通过 ≠ 声称官方通过（必须标注证据层级）

### G.3 优化证据

- [ ] **G.3.1** T2-T5 有非 case-specific 优化证据（不依赖公开测试具体值）
- [ ] **G.3.2** O2 vs O0 对比显示可测量的指令数减少或性能提升
- [ ] **G.3.3** 每类优化有对应的负面/变异测试

### G.4 鲁棒性证据

- [ ] **G.4.1** 覆盖 11 种官方变异维度（见 X.4）
- [ ] **G.4.2** 无公开案例结构假设导致的退化

### G.5 文档与治理

- [ ] **G.5.1** `docs/STATUS.md` 真实反映当前实现能力
- [ ] **G.5.2** `docs/EVALUATION.md` 与实际得分映射一致
- [ ] **G.5.3** README 含最新勘误说明
- [ ] **G.5.4** 无过期声明（C1 Agent scoring、Cycle Model、Tensor ISA、低精度 GEMM、Header/Data/Reloc/Symbol .aecbin、divergent-branch reconvergence）

### G.6 仓库安全

- [ ] **G.6.1** `origin` 指向 `BulletFlying/agentic4systems-c1-compiler-bootstrap`
- [ ] **G.6.2** 官方仓库 `ephonic/Agentic4SystemSummerSchoolContest` 未配置为 remote
- [ ] **G.6.3** 无 `__pycache__`、`.pytest_cache`、`.pyc`、临时二进制、日志被跟踪
- [ ] **G.6.4** GitHub Actions CI green

### G.7 最终检查

- [ ] **G.7.1** `python -m compileall -q src compiler disassembler agent tests` 无错误
- [ ] **G.7.2** `python -m pytest -q tests` 全部通过
- [ ] **G.7.3** `git diff --check` 无空白警告
- [ ] **G.7.4** `git status --short` clean
- [ ] **G.7.5** 无硬编码答案 / 特判逻辑
- [ ] **G.7.6** 无未披露第三方依赖
