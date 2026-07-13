# C1 AEC IR 编译器：项目总纲与验收基线

> 本文是 `Track-C/C1-compiler/` 的长期事实基线，用于统一人类开发者、Codex/LLM Agent 与后续代码审阅的上下文。实施状态单独维护在 `docs/STATUS.md`；本文不因单次提交而改写项目目标。

## 1. 项目使命

C1 的目标不是针对 5 个公开 PTX 文件生成固定答案，而是实现一套可泛化、可验证、可优化的 PTX 风格 IR 到 AEC ISA 的编译工具链：

```text
PTX-style source
  -> parser / typed IR
  -> basic blocks / CFG / analyses
  -> legality lowering and control-flow legalization
  -> optimization pass pipeline
  -> register allocation and spill
  -> dependency-aware scheduling
  -> AEC 128-bit encoding / object container
  -> disassembly
  -> correctness and cycle-model feedback
  -> offline optimization Agent
```

必需入口：

```bash
compiler/aec-cc input.ptx -O0|-O2|-O3 -o output.aecbin
disassembler/aec-objdump output.aecbin
agent/run_agent
```

正确性是性能计分的前置门禁。任何优化都必须保留可执行语义；无法证明安全时，应拒绝编译或采用保守 fallback，不得猜测。

## 2. 权威来源与冲突处理

事实来源优先级如下：

1. 本仓库保留的 C1 `spec.md` 与 `scoring.md` 副本。
2. 已交叉核对过的 Track-B Appendix A AEC Precise ISA Specification 事实。
3. 已复制或内联保留的 Track-B assembly/binary/testcase 参考向量。
4. 官方 Track-C/C2 starter kit，仅用于明确标注的 C2/B3 扩展，不得覆盖 Track-B 默认 profile。
5. 发布会 PPT、群内公告和现场答疑。
6. 本仓库文档、推断和临时兼容策略。

出现冲突时必须：

- 在代码中隔离为 profile、serializer 或 ABI policy，不把冲突硬编码进公共 lowering；
- 在 `docs/STATUS.md` 的“Organizer clarification”中记录；
- 默认采用更保守、与官方公开 binary 可交叉验证的实现；
- 不得把推断写成已确认事实。

当前已知未冻结事项：

- C1 `output.aecbin` 所要求的 Header/Code/Data/Relocation/Symbol Table 精确布局尚未公开；
- C1 PMEM 参数块的正式 ABI 尚未明确；
- PTX-05 最终采用 Track-B scalar profile 还是 C2/B3 tensor extension 尚需确认；
- 官方 C1 Golden Model、Cycle Model 与统一评分脚本尚未公开。

## 3. 仓库与远端安全边界

仓库角色：

- `BulletFlying/agentic4systems-c1-compiler-bootstrap`：本项目唯一 Git remote 和可写 public repo。
- `ephonic/Agentic4SystemSummerSchoolContest`：不得配置为本地 Git remote；仅在用户明确要求刷新外部事实时，通过网页或一次性查询读取。

强制规则：

- 禁止向官方仓库推送 branch、commit、tag、release、PR 或 issue，除非用户明确逐次授权；
- 本地 `origin` 必须指向 BulletFlying 仓库；不得保留 `origin`、`upstream` 或其他指向官方仓库的 remote；
- 每轮结束必须核对项目仓库的 `main` SHA，并确认本地没有官方 remote；
- 不得 force-push `main`；功能开发使用独立 branch，验收后 fast-forward 或正常合并；
- 不得提交 `__pycache__`、`.pytest_cache`、临时 binary、日志、waveform、测试输出或 disposable artifact。

## 4. 官方评分基线

依据官方 `Track-C/C1-compiler/scoring.md`：

| 大项 | 分值 | 实施含义 |
|---|---:|---|
| 编译与执行正确性 | 50 | 100 个隐藏测试，T1-T5 各 20；二进制格式和 Golden Model 输出均须正确 |
| 生成代码效率 | 35 | 仅正确 case 计分；以 AEC Cycle Model `total_cycles` 衡量 |
| 泛化与鲁棒性 | 5 | 50 个自动变异测试，禁止依赖公开 case 固定结构 |
| Agent 自动优化 | 10 | 性能 8 + 闭环完整性 2 |

发布会/PPT 进一步给出的 C1 计分细节：

```text
正确性 = T1*4 + T2*8 + T3*10 + T4*12 + T5*16
性能归一化 = p(T_base / T_candidate)，以 AEC Cycle Model total_cycles 为主指标
Agent = 8 分性能几何均值 + 2 分闭环完整性
```

2026-07-13 群公告和配套 PPT 还要求 C 赛道性能优化参考类 NVIDIA GPGPU 目标硬件指标建立 Performance Model。具体目标硬件指标、PPA 公式和报告字段方向维护在 `docs/PERFORMANCE_MODEL.md`。

性能分分布：

| 类别 | 性能分 | 公开代表题 |
|---|---:|---|
| T1 基础 Lowering | 0 | PTX-01 vector_add |
| T2 控制与标量优化 | 5 | PTX-02 invariant_poly |
| T3 内存优化 | 9 | PTX-03 repeated_reuse |
| T4 寄存器与调度 | 10 | PTX-04 reg_schedule |
| T5 Tensor/GEMM | 11 | PTX-05 gemm_f16 |

隐藏变异至少包括：参数/矩阵规模变化、寄存器重命名、基本块重排、循环次数变化、死代码插入、寄存器压力增加、数据类型变化、内存复用模式变化。因此，任何依赖文件名、case ID、hash、固定标签、固定 PTX 寄存器编号或固定指令位置的实现均视为违规设计。

Agent 必须形成真实闭环：独立运行、读取性能报告、调整配置重编译、验证正确性、生成最终优化报告。仅输出静态 JSON 或调用 LLM 不构成完成。

## 5. 编译器架构基线

代码应维持清晰分层，避免把解析、分析、变换、分配、调度和编码全部堆入 `compiler.py`。

建议层次：

```text
ptx.py             lexical/structural parsing and source locations
ir.py              typed operands, instructions, functions, blocks, SSA values
cfg.py             CFG, dominators, loops, traversal
analysis.py        uniformity, def-use, liveness, alias/memory facts
passes/            canonical optimization and legalization passes
lowering/          PTX -> target-independent lowered IR -> AEC legal forms
regalloc.py        physical allocation, pair constraints, spill/reload
scheduler.py       DDG, latency model, list scheduling, issue pairing
isa.py             profile-specific encoding/decoding only
object.py          raw/image/C1 object serializers
sim.py             local semantic oracle subset; never treated as official model
agent.py           report-driven offline search loop
```

架构约束：

- Analysis 只产生事实，不直接修改代码；transform/pass 显式消费事实；
- CFG 变换后必须失效或重算 dominance、loop、def-use、uniformity 等分析；
- 未知 uniformity 不等于 uniform；只有 `proven_uniform` 条件允许直接生成 AEC `BRX`；
- varying control 优先采用语义可证明的 predication/if-conversion；不得生成可能 mixed-lane 的 `BRX`；
- kernel 顶层 PTX `ret` 下降为 `HALT`；AEC `RET` 仅用于真实 `CALL` 栈；
- AEC 地址是 memory-space 内 32-bit byte offset；64-bit PTX pointer lowering 必须以显式 address legalization 表达；
- Track-B 默认 profile 与 C2/B3 tensor profile 必须隔离；默认输出不得混用 opcode/type 编号；
- encoder/decoder round-trip 只能证明内部一致性，必须同时保留官方 golden hex/vector 交叉测试。

## 6. 里程碑路线图

### M0：规格、编码与 CLI 基座

目标：ISA profile、128-bit encoder/decoder、raw writer、objdump、PTX parser、CLI smoke。

验收：官方 Track-B assembly/hex 至少一组 bit-exact；错误输入明确失败；默认 profile 不混入 C2 编码。

### M1：PTX-01 本地可执行正确性闭环

目标：参数、特殊寄存器、地址计算、FP32 load/add/store、partial-warp 边界 if-conversion、本地差分执行。

验收：边界与随机 N；非法 lane 无 GMEM side effect；无 boundary `BRX`；bit-exact 输出；M0 回归通过。

### M2.1：PTX-02 CFG 与 uniform loop correctness

目标：基本块、CFG、dominators、backedge/natural loop、三态 uniformity、varying forward exit legalize、uniform loop `BRX`、本地 bit-exact 差分。

验收：boundary predicate proven varying；loop predicate proven uniform；仅保留 uniform backedge `BRX`；N=0/partial/full warp 与随机输入均正确；非法 lane 无 GMEM side effect。

### M2.2：T2 标量优化

目标：常量传播/折叠、CSE、DCE、LICM、基本块简化/合并；`-O0/-O2/-O3` 连接真实 pass pipeline。

验收：每个 pass 有独立 unit test、negative test 与优化前后差分；循环次数、标签名、寄存器名变化后仍成立；优化指标可解释。

### M3：PTX-03 内存优化

目标：memory def-use、alias conservatism、load reuse、loop-invariant load hoist、合并访问分析、shared-memory promotion 与同步合法性。

验收：随机复用模式和边界；无错误 hoist；memory transaction 统计下降；correctness 不依赖固定 loop=16。

### M4：PTX-04 寄存器分配与调度

目标：liveness/live interval、linear scan 或 graph coloring、32/64-bit pair constraints、spill/reload、DDG、latency-aware list scheduling、合法 issue pairing。

验收：高压与重命名测试；无物理寄存器冲突；spill 地址合法；调度保持依赖与 memory order；周期/指令指标可复现。

### M5：PTX-05 多精度 GEMM

目标：通用 GEMM 语义检测、scalar fallback、u16/f16 legalization、tile search、边界处理、9 种精度；官方确认后启用 tensor profile/TLDA/TMUL/TSTA。

验收：多尺寸含非 16 倍数边界；精度矩阵；无 out-of-bounds；pattern detection 不依赖文件名和固定寄存器；fallback correctness 始终可用。

### M6：Agent、容器格式与最终交付

目标：真实 report-driven 搜索、最终 serializer、鲁棒诊断、Docker 离线复现、完整报告和原创性披露。

验收：Agent 闭环独立运行；失败候选自动回退；提交目录和入口一致；全量测试、静态检查、打包检查通过。

## 7. 每轮开发流程

每个 milestone/sub-milestone 使用以下顺序：

1. 记录 `git status --short`、branch、HEAD、remotes 和项目 `main` SHA，并确认没有官方 remote。
2. 从 clean tree 建 feature branch。
3. 先写语义/验收测试，再写最小实现；不得用放松 simulator 约束来让测试通过。
4. 运行目标测试、全量回归、CLI smoke、`git diff --check`。
5. 审阅：正确性、泛化、代码复杂度、声明真实性、临时文件。
6. 将已验证事实写入 `docs/STATUS.md`；未执行项必须标记 `Not run`。
7. 合并并只推送项目仓库；再次确认本地 Git remote 只指向项目仓库。

推荐提交粒度：analysis/IR、implementation、tests/docs 分离，提交信息使用 `refactor(c1):`、`feat(c1):`、`test(c1):`、`fix(c1):`、`docs(c1):`。

## 8. 通用验收矩阵

每个功能至少覆盖：

- unit：单个 parser/analysis/encoder/pass 行为；
- structural：CFG、def-use、liveness、branch target、register constraints；
- executable：本地 simulator 或官方 model 的端到端结果；
- differential：优化前后或 PTX reference 与 AEC execution 对比；
- mutation：寄存器重命名、标签重命名、参数/loop 变化、dead code；
- negative：未知 opcode、undefined label、unsafe branch、register exhaustion、非法 binary；
- regression：此前 milestone 全部测试；
- artifact：CLI、objdump、文件长度/格式、无缓存和临时产物。

测试声明规则：

- “passed”仅用于本轮实际执行且有可复核输出的命令；
- GitHub 没有 Actions/check 时不得写“CI passed”；
- 本地 simulator 通过不得表述为官方 Golden/Cycle Model 通过；
- “可 lower”不得表述为“语义正确”；
- encoder/decoder round-trip 不等于官方编码合规。

## 9. 代码质量与反屎山约束

- 禁止 case-specific 分支、固定寄存器号/标签名判断、文件名/hash dispatch；
- 禁止 `legacy_*` 或 fallback 路径静默绕过安全分析；不安全路径必须显式 error 或被测试隔离；
- 禁止全局可变分析状态跨函数/编译单元泄漏；
- 临时寄存器不得回绕复用；正式阶段必须由 liveness-aware allocator 管理；
- 一个函数只承担一个可描述职责；复杂控制流规划必须拆为独立 analysis/transform；
- magic number 必须来自 ISA/ABI/profile 常量或带来源说明；
- pass 必须声明 prerequisites、preserved analyses、invalidated analyses 与可观察统计；
- simulator 不得复制 compiler 的错误假设作为“独立 oracle”；reference 计算和 target execution 必须尽量独立；
- README/Agent 输出不得声称尚未实现的 pass 已启用；
- 遇到技术债务应登记在 `docs/STATUS.md`，不得通过注释“暂时”长期掩盖。

代码审阅优先级：

1. 会导致错误二进制、mixed-lane `BRX`、OOB、错误寄存器覆盖的 correctness defect；
2. 对隐藏变异不成立的泛化 defect；
3. compiler 与 simulator 共用错误语义造成的伪验证；
4. 复杂度、重复逻辑、职责混杂和难维护接口；
5. 性能优化机会。

## 10. 最终交付门禁

正式声称“完整满足 C1”前，必须同时满足：

- 公开五题均有 executable correctness，而非仅 parse/lower；
- 100 个隐藏类型所需语法/控制/内存/寄存器/Tensor 能力有泛化测试；
- `-O0/-O2/-O3` 是真实且可解释的 pipeline；
- 正确性通过后有 Cycle Model 性能证据；
- register allocation、spill、DDG/list scheduling、memory optimization、GEMM precision/tile 均实际存在；
- `aecbin` 最终格式与官方 validator 一致；
- Agent 完成读取报告—重编译—验证—选择—报告闭环；
- Docker 离线构建与 180 秒限制内运行；
- 文档披露所有第三方代码、工具和 LLM 辅助；
- 官方仓库未被配置为 remote 或作为写入目标，提交包无无关产物。

在上述条件未全部满足前，应使用“完成 Mx 本地验收”“bootstrap”“locally validated”等精确措辞，不得宣称 C1 完整完成。
