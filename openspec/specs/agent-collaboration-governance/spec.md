# agent-collaboration-governance Specification

## Purpose
定义 Simulanka 的 OpenSpec-first 开发生命周期、Codex 单一负责制、任务级单写者、证据化复核、模型分级和用户最终裁决规则。

## Requirements
### Requirement: OpenSpec-first development lifecycle
非平凡仓库开发 MUST 先通过 OpenSpec Explore 调查并明确需求，再形成 apply-ready 的 proposal、design、specs 和 tasks，最后才可实施批准的 task。Explore 阶段 MUST NOT 修改应用实现。

#### Scenario: New feature starts from an idea
- **WHEN** 用户提出尚未形成明确契约的新功能
- **THEN** 代理先进入 OpenSpec Explore 澄清范围、非目标和风险，并在形成 change 后才开始实现

#### Scenario: Existing change is apply-ready
- **WHEN** OpenSpec status 表明 planning artifacts 已完成且 tasks 可实施
- **THEN** 代理直接按 `openspec-apply-change` 执行所选 task，而不重复创建 proposal

### Requirement: Grill is a development-time alignment tool
grill MUST 只用于开发推进中出现的具体问题快速对齐，不得替代初始 OpenSpec Explore，也不得成为所有 task 的固定前置门。

#### Scenario: Routine implementation proceeds
- **WHEN** 已批准 task 的边界、设计和验收均明确
- **THEN** 实现代理直接施工和验证，不启动 grill

#### Scenario: Development reveals a design conflict
- **WHEN** 实现证据显示已接受需求冲突、冻结契约受影响或存在实质方案分叉
- **THEN** 主代理暂停相关施工并用 grill 对齐；若结论改变契约，则先更新 OpenSpec artifact

### Requirement: Single writer and independent review
每个 OpenSpec task 在任一时刻 MUST 只有一个写者。验证子代理 MUST 默认只读，提交、推送和 GitHub 状态变更 MUST 由主 Codex 会话统一执行，除非任务明确授权。合并前主 Codex 会话 MUST 对最终 diff 进行独立复读，并核对 OpenSpec、GitNexus 影响和验收结果；外部 Provider 交叉审 MUST NOT 成为固定门禁。权威文档 MUST 另受一篇一写者约束：同一篇 `docs/*.md` 在任一时刻 MUST 只由一个 task 修改，并在其 Issue 中认领。

#### Scenario: Parallel assistance
- **WHEN** 一个实现 task 同时需要上下文调查和测试分析
- **THEN** 可并行运行多个只读 Codex 子代理，但只有获授权的实现者可修改 task 范围内文件

#### Scenario: Self-review before merge
- **WHEN** Codex 完成一个 task 的实现与验证
- **THEN** 主会话复读最终 diff、检查预期影响与验证证据后自行决定是否合并，不等待 Claude

#### Scenario: Two tasks need the same authoritative doc
- **WHEN** 两个并行 task 都要改 `docs/frontend.md`
- **THEN** 先认领者独占该文件，另一任务等其合入后再改，不得同时编辑

### Requirement: Tiered model routing
Codex 子代理 MUST 按任务复杂度选择模型，不得默认全部使用最高能力模型。常规有界任务 MUST 优先使用轻量或均衡模型，高风险契约和架构任务 MUST 升级强模型。派发本身有冷启动成本，主代理 MUST NOT 在没有并行或隔离收益时为有界查找派发子代理；不使用子代理 MUST 是允许的常规路径。

#### Scenario: Bounded repository search
- **WHEN** 子任务仅需定位文件、符号、测试或整理日志且独立派发确有收益
- **THEN** Codex 使用 `gpt-5.6-terra`，而不是强制使用最强模型

#### Scenario: High-risk change
- **WHEN** GitNexus 风险为 HIGH/CRITICAL，或任务涉及冻结契约、事务、并发、恢复、迁移或删除
- **THEN** Codex 使用更强推理复核并在继续修改前向用户报告高风险；模型复核不替代用户对产品方向和冻结契约的裁决权

### Requirement: The user is the top of the escalation ladder
升级推理强度 MUST 被视为获得更强的判断，而非获得裁决权。当证据仍无法收敛、两次实质性实现或诊断失败、或结论会改变产品方向、冻结契约或已接受范围时，Codex MUST 停下并带证据与选项交用户裁决。

#### Scenario: Strong review cannot settle a conflict
- **WHEN** 强推理复核后仍存在不相容的正确性结论
- **THEN** Codex 停止相关施工并向用户呈交证据与可选方案，由用户拍板

### Requirement: Minimal task capsule
主代理派发子任务时 MUST 提供最小 task capsule，至少包含 change/task、baseline、目标、非目标、worktree、允许路径、契约引用、已知影响和验收命令。子代理 MUST 返回范围、证据、结论与未决风险。

#### Scenario: Spawn a routine builder
- **WHEN** 主代理将已批准 task 交给实现子代理
- **THEN** 子代理无需加载完整对话历史即可从 task capsule 完成有界工作，并不得扩张范围

### Requirement: Provider-specific supported configuration
Codex MUST 通过 `AGENTS.md` 和每次 spawn 参数选择子代理角色与模型，不得依赖 Claude 项目配置或创建未经支持的持久化 agent profile。仓库内当前治理 MUST NOT 要求 `.claude/` 或 `CLAUDE.md`。子代理的写权限 MUST 由任务显式授权；仓库内 agent 指令 MUST NOT 依赖个人环境假设。

#### Scenario: Codex starts repository work
- **WHEN** Codex 在任一 Simulanka checkout 开始任务
- **THEN** 它以 `AGENTS.md`、选定 OpenSpec change 和 GitHub Issue 为当前治理入口，不读取 Claude 专属配置作为门禁

#### Scenario: Codex spawns a child
- **WHEN** Codex 需要一个子代理且并行或隔离收益成立
- **THEN** 它依据 `AGENTS.md` 使用最小 task capsule、明确读写权限并选择适当模型

### Requirement: Active documentation has no provider ownership residue
当前协作文档和活动 OpenSpec change MUST NOT 将功能目录永久标记为 Provider 专属线路，也 MUST NOT 要求 Claude 参与、认证或交叉审。冻结归档和 Git 历史 MAY 保留历史表述，但 MUST NOT 被解释为当前分工。

#### Scenario: Read current governance
- **WHEN** 任一 Codex 会话读取当前 `AGENTS.md` 或活动 OpenSpec change
- **THEN** 它看到 Codex 单一负责、任务级范围和证据门禁，不会遇到 Claude handoff 或交叉审要求

### Requirement: Codex sole ownership
Codex MUST own the ongoing Simulanka development lifecycle across the entire repository, including implementation, verification, commits, pushes, GitHub Issue updates, merges, spec sync, and archive. Repository work MUST NOT depend on Claude availability, authentication, review, configuration, or handoff. Ownership SHALL remain task-scoped rather than directory-scoped.

#### Scenario: Codex completes an accepted task
- **WHEN** an apply-ready OpenSpec task passes its specified validation and final review
- **THEN** Codex may commit, push, merge, update the Issue, and close the change without waiting for Claude

#### Scenario: Work touches any repository area
- **WHEN** an accepted task requires changes in server, frontend, agent, kernel, documentation, or another repository area
- **THEN** Codex may implement that vertical slice subject to its OpenSpec scope and frozen-contract rules
