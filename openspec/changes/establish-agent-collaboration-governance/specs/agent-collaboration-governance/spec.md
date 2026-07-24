## ADDED Requirements

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

### Requirement: Issue-scoped equal ownership
Claude 与 Codex MUST 具有相同的仓库工作范围，不得按目录永久分配所有权。工作所有权 MUST 绑定到 GitHub Issue 和 OpenSpec task，并由实现者在自己的 worktree/分支承担。

#### Scenario: Codex implements a server task
- **WHEN** Codex 认领一个包含 `server/` 修改的 OpenSpec task
- **THEN** 只要满足冻结契约和设计要求，Codex 可在 `codex/<topic>` 分支实施并由 Claude 交叉审查

#### Scenario: Claude implements an agent task
- **WHEN** Claude 认领一个包含 `agent/` 修改的 OpenSpec task
- **THEN** Claude 可在自己的分支实施并由 Codex 交叉审查

### Requirement: Single writer and independent review
每个 OpenSpec task 在任一时刻 MUST 只有一个写者。验证和审查代理 MUST 默认只读，提交、推送和 GitHub 状态变更 MUST 由主代理统一执行，除非任务明确授权。

#### Scenario: Parallel assistance
- **WHEN** 一个实现 task 同时需要上下文调查和测试分析
- **THEN** 可并行运行多个只读子代理，但只有 slice builder 可修改 task 范围内文件

### Requirement: Tiered model routing
子代理 MUST 按任务复杂度选择模型，不得默认全部使用最高能力模型。常规有界任务 MUST 优先使用轻量或均衡模型，高风险契约和架构任务 MUST 升级强模型。

#### Scenario: Bounded repository search
- **WHEN** 子任务仅需定位文件、符号、测试或整理日志
- **THEN** Codex 使用 `gpt-5.6-terra`，Claude 使用 Haiku 或 Sonnet，而不是强制使用最强模型

#### Scenario: High-risk change
- **WHEN** GitNexus 风险为 HIGH/CRITICAL，或任务涉及冻结契约、事务、并发、恢复、迁移、删除
- **THEN** 使用 `gpt-5.6-sol` 或 Claude Opus 进行契约/风险裁决，并在继续修改前向用户报告高风险

### Requirement: Minimal task capsule
主代理派发子任务时 MUST 提供最小 task capsule，至少包含 change/task、baseline、目标、非目标、worktree、允许路径、契约引用、已知影响和验收命令。子代理 MUST 返回范围、证据、结论与未决风险。

#### Scenario: Spawn a routine builder
- **WHEN** 主代理将已批准 task 交给实现子代理
- **THEN** 子代理无需加载完整对话历史即可从 task capsule 完成有界工作，并不得扩张范围

### Requirement: Provider-specific supported configuration
Claude 项目子代理 MUST 使用 `.claude/agents/*.md` 的受支持格式配置。Codex MUST 通过 `AGENTS.md` 和每次 spawn 参数选择角色与模型，不得创建未经支持的持久化 agent profile。

#### Scenario: Claude session loads project agents
- **WHEN** Claude Code 从仓库启动或重启
- **THEN** 它可发现项目级 scout、guardian、builder、verifier 和 reviewer 定义及其模型/权限

#### Scenario: Codex spawns a child
- **WHEN** Codex 需要一个子代理
- **THEN** 它依据 `AGENTS.md` 使用 `fork_turns: "none"` 并显式选择 Terra 或 Sol

### Requirement: Active documentation has no provider ownership residue
当前协作文档和活动 OpenSpec change MUST NOT 将功能目录或任务永久标记为“Claude 线”或“Codex 线”。冻结归档 MAY 保留历史表述，但 MUST NOT 被解释为当前分工。

#### Scenario: Read current S8 tasks
- **WHEN** 任一代理读取活动的 S8 proposal、design 或 tasks
- **THEN** 它看到的是 task 内容与交叉审查要求，而不是指定 Claude/Codex 的永久施工所有权
