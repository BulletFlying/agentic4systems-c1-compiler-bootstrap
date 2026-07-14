# AGENTS.md — C1 编译器协作规则

本文件适用于 `Track-C/C1-compiler/` 及其子目录。详细目标、评分、里程碑和验收基线见 `docs/C1_PROJECT_CHARTER.md`；当前实施状态见 `docs/STATUS.md`；branch、PR 与新模块修改门禁见 `docs/DEVELOPMENT_POLICY.md`。

## 1. 不可违反的边界

- 官方仓库 `ephonic/Agentic4SystemSummerSchoolContest` 不得配置为本地 Git remote。没有用户逐次明确授权，不得向其 push、创建 branch/tag/release/PR/issue 或修改任何内容。
- 只允许将开发结果写入 `BulletFlying/agentic4systems-c1-compiler-bootstrap`；本地 `origin` 必须指向该仓库。
- 禁止根据文件名、case ID、输入 hash、固定标签、固定 PTX 寄存器编号或固定指令位置生成特例答案。
- 禁止放松 simulator/validator 语义来让测试通过。
- 无法证明合法的 lowering/optimization 必须保守 fallback 或明确报错，不得猜测。
- 未实际运行的验证不得标为 passed；本地 simulator 通过不得表述为官方 `aec-precise`/CModel 通过。

## 2. 事实来源顺序

1. 官方 C1 `spec.md`、`scoring.md`。
2. 官方 C1 manifest-based public testcase package。
3. 发布会/群公告中与当前 C1 包一致的补充说明。
4. 官方 Track-B / C2 材料中仍被当前 C1 `spec.md` 明确引用的兼容事实。
5. 本仓库文档和兼容推断。

默认 ISA 与 binary format 以当前 C1 `spec.md` 为准：raw AEC 128-bit instruction stream、官方 C1 opcode/type/space 表、官方 PMEM ABI。旧 Track-B/C2/B3 tensor 资料只能作为历史背景，不得把 Tensor/TMUL/低精度 GEMM 重新纳入 C1 默认路径。

## 3. 每轮开始前

必须记录：

```bash
git status --short
git status --branch --short
git rev-parse HEAD
git remote -v
git branch -vv
git ls-remote origin refs/heads/main
```

确认 clean tree 后，从最新项目 `main` 创建符合 `docs/DEVELOPMENT_POLICY.md` 命名规则的短生命周期 branch。除用户明确授权的紧急文档修正外，不得直接在 `main` 开发；代码、测试和基础设施变更必须通过 PR 合并。若 `origin` 未指向 BulletFlying 仓库，必须先报告并修正，不得自行假设。

新建或重大修改模块前，必须先写清模块责任、接口、analysis preservation/invalidation、语义不变量、保守 fallback、迁移路径和验收测试。可先建立 GitHub `C1 module or milestone change` issue，PR 必须填写仓库内模板。

## 4. 实施原则

- Parser、IR、CFG、analysis、transform、regalloc、scheduler、ISA/object、simulator、Agent 分层；避免继续扩大单体 `compiler.py`。
- Analysis 只产生事实；transform 显式消费事实。CFG 改写后重算或失效相关分析。
- `UNKNOWN` uniformity 绝不等于 `UNIFORM`。只有 proven-uniform predicate 可生成直接 AEC `BRX`。
- kernel 顶层 PTX `ret` 降为 `HALT`；AEC `RET` 仅服务真实 `CALL`。
- 临时寄存器不得回绕覆盖；寄存器不足必须报错，后续由 liveness-aware allocator/spill 解决。
- 64-bit PTX pointer 到 AEC 32-bit memory-space offset 的转换必须作为显式 address legalization，不得伪装成完整通用 u64 ALU。
- 每个 pass 要有独立测试、negative test、优化前后 executable differential，并说明 preserved/invalidated analyses。
- 不得让 compiler 与 simulator 共享同一段核心语义实现，从而形成自证循环。

## 5. 里程碑顺序

严格按以下主线推进，除非用户明确调整：

```text
M0 ISA/CLI/encoder baseline
M1 PTX-01 executable correctness
M2.1 PTX-02 CFG + uniform loop correctness
M2.2 CSE/DCE/LICM/basic-block optimization
M3 PTX-03 memory optimization
M4 PTX-04 register allocation + scheduling
M5 PTX-05 FP32 scalar GEMM
M6 final packaging, official `aec-precise` integration, and optional report-driven tooling
```

不得在当前 milestone 的 correctness gate 未通过时提前宣称后续能力完成。

## 6. 测试与验收

每轮至少执行：

```bash
python -m compileall -q src compiler disassembler agent tests
python -m pytest -q tests
git diff --check
git status --short
```

并根据本轮功能增加：CLI compile、objdump、structural assertions、boundary/random differential、invalid-lane side-effect、mutation、negative tests。

完成标准：

- 目标测试和此前全部 regression 通过；
- 生成代码结构满足证明条件，不只输出相同结果；
- 无缓存、临时 binary、日志或 disposable artifact；
- README/STATUS 对实现能力描述真实；
- 本地 Git remote 不包含官方仓库；
- 只推送项目仓库；
- GitHub Actions 已运行时必须为 green；仅存在 workflow 文件不得表述为 CI passed。

## 7. 代码审阅优先级

1. 错误二进制、mixed-lane branch、OOB、寄存器覆盖等 correctness defect。
2. 对寄存器/标签重命名、loop/shape 变化不成立的泛化 defect。
3. compiler 与 simulator 同源假设导致的伪验证。
4. 静默 fallback、`legacy_*` 绕过、职责混杂、长函数和重复逻辑。
5. 性能优化机会。

发现技术债务应记录到 `docs/STATUS.md`，并给出严重级别、影响、触发条件和建议修复 milestone。

## 8. 最终汇报格式

每轮结束固定输出：

```text
Summary
Changed files
Design / proof
Verification (Passed / Failed / Not run)
Code quality review
Git status and remote verification
Known limitations
Organizer clarification needed
Next single main task
```

不要使用“完整完成 C1”这一表述，除非 `docs/C1_PROJECT_CHARTER.md` 的最终交付门禁全部满足。
