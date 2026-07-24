## Why

Simulanka 的 Claude 与 Codex 协作规则仍保留按目录划分所有权的旧约定，也没有把 OpenSpec 生命周期、开发中按需 grill、子代理模型分层和单写者约束统一成可执行规范。需要清理这些冲突，让两边从同一任务契约工作，同时用轻量模型承担有界工作以降低 token 成本。

## What Changes

- 以 OpenSpec `explore → propose → apply → review → archive` 作为非平凡开发的默认生命周期。
- 将 grill 定位为开发推进中遇到需求冲突、设计分叉或失败证据时的快速对齐手段，而非需求探索或施工前置门。
- 移除 Claude/Codex 的永久目录所有权，改为按 GitHub Issue 和 OpenSpec task 临时认领垂直功能线；实现者使用自己的 worktree/分支，另一方交叉审查。
- 建立子代理角色、读写边界、交接格式和模型路由；常规检索、实现、验证优先使用较轻模型，高风险契约与架构裁决才升级强模型。
- 为 Claude Code 提供项目级子代理定义；Codex 使用仓库规则约束每次 spawn 的模型和职责，不引入未经支持的持久化配置格式。
- 清理活动文档和未完成 OpenSpec change 中的旧“Claude 线 / Codex 线 / 单一目录所有者”残留；冻结归档只保留历史，不再作为当前分工依据。

## Capabilities

### New Capabilities

- `agent-collaboration-governance`: 规定 Claude/Codex 与子代理如何通过 OpenSpec、GitHub Issue、独立 worktree、模型路由和交叉审查协同开发。

### Modified Capabilities

（无。S8 中的供应方所有权措辞属于施工分配残留，不改变 `run-agent-bracket` 的功能需求。）

## Impact

- 协作入口：`AGENTS.md`、`CLAUDE.md`。
- 权威开发文档：`docs/assembly.md`。
- 活动 OpenSpec：`openspec/changes/s8-agent-socket/`。
- Claude Code 项目子代理：`.claude/agents/`。
- 不修改应用代码、运行时 API、kernel/schema 或冻结的 `docs/archive/design.md`。
