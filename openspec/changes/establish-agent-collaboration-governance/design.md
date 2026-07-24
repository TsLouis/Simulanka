## Context

当前仓库同时存在三套未完全对齐的协作信息：

- `AGENTS.md` 仍按目录永久划分 Claude/Codex 所有权；
- 活动 S8 文档与 OpenSpec tasks 仍将个别任务写成“Codex 线施工、Claude 出规格”；
- Codex 已有 OpenSpec skills，但没有项目级持久化子代理格式；Claude Code 支持 `.claude/agents/*.md` 项目代理。

用户已确认的新口径是：Claude 与 Codex 工作相同，只在各自 worktree/分支承担临时认领的任务；非平凡开发先用 OpenSpec Explore 明确需求，再建立和实施 change；grill 只在推进中遇到开发问题时快速对齐；子代理按任务复杂度选择模型，不默认使用最强模型。

## Goals / Non-Goals

**Goals:**

- 让 Claude、Codex 和它们的子代理读取同一套当前协作规则。
- 用 OpenSpec artifacts 承载范围、设计、需求、任务和验收，GitHub Issue 只做协调。
- 通过单写者、交叉审查、模型升级条件和固定交接格式控制质量与 token 成本。
- 清理活动文档中的旧目录所有权和供应方施工线残留。

**Non-Goals:**

- 不改变 Simulanka 产品架构、运行时 agent 机制或 S8 的功能验收。
- 不修改冻结的 `docs/archive/design.md`；其中历史分工只作为当时决策记录。
- 不创建 Codex 尚不支持的 `.codex/agents` 配置体系。
- 不让子代理自行提交、推送、修改 GitHub 或改变 OpenSpec 状态，除非任务明确授权。

## Decisions

1. **OpenSpec 是开发生命周期，grill 是处理中工具。**
   - 默认顺序为 `explore → propose → apply → review → sync/archive`。
   - Explore 只调查和澄清，不实现。
   - grill 不作为开始开发的必经门；只有实现中出现已接受需求冲突、冻结契约/边界问题、证据支持的方案分叉或持续失败时使用。
   - grill 若改变范围、需求、设计或任务，必须先更新相应 artifact，再继续实现。
   - 备选“先 grill 再 OpenSpec”被否决，因为它重复需求探索并把临时对话置于可审查契约之前。
   - 2026-07-24 用户在交叉审查中确认：grill 不再默认，需要时由用户自己调用。

2. **Claude/Codex 同责，任务临时所有。**
   - 不设永久目录所有者。一个 GitHub Issue 对应一个 OpenSpec change 或其中明确 task。
   - 实现者在自己的 worktree 和供应方前缀分支施工，另一方交叉审查。
   - 任一时刻每个 task 只有一个写者；文档同步也由该 task 指定的单写者完成。
   - 单写者是 task 级的，挡不住两个并行 task 同时改 `frontend.md`：权威文档另加“一篇文档同一时刻只由一个 task 改动、在 Issue 中认领”的约束（交叉审查补，替代原“文档单写者=Claude”）。
   - 分支命名对称：`codex/<topic>` 与 `claude/<topic>`；合并在主检出 `/home/ts/Simulanka` 执行（唯一带 `.venv` 的树）。
   - kernel/schema、写权矩阵和 server edge endpoints 的冻结契约约束保留，但触发的是设计与审查要求，不是供应方所有权。

3. **子代理是任务模板，不是长期目录团队。**
   - 固定角色为 context scout、contract guardian、slice builder、verification prober、change reviewer。
   - 子代理只接收 task capsule，不继承不必要的完整历史；返回范围、证据、结论和未决风险。
   - 同时可以有多个只读代理，但只能有一个写代理。
   - 派发本身有成本：子代理冷启动要重读 `AGENTS.md` 与相关文档，有界查找往往主会话直接读更便宜。只在并行或隔离确有收益时派发（交叉审查补）。

4. **模型按风险分层。**
   - Codex：`gpt-5.6-terra` 承担有界检索、常规实现、测试和常规审查；`gpt-5.6-sol` 承担需求/契约综合、高风险架构裁决和升级审查。
   - Claude：Haiku 承担只读侦察，Sonnet 承担常规实现/验证/审查，Opus 承担冻结契约与高风险架构裁决。
   - GitNexus HIGH/CRITICAL、跨三个以上架构区域、事务/并发/恢复/迁移/删除、OpenSpec 自相矛盾或连续两次实质失败会触发强模型升级。
   - 阶梯顶端是人不是模型：最强模型仍不收敛、builder 与 reviewer 持续对立、或决定会改变产品方向/冻结契约/已接受范围时，带证据和选项交用户裁决（交叉审查补，对齐项目一贯的人裁至上）。

5. **供应方采用各自真实支持的配置。**
   - Claude 项目代理放在 `.claude/agents/`，使用受支持的 YAML frontmatter 和工具/权限限制。
   - Codex 的角色与模型路由写入 `AGENTS.md`，每次 spawn 显式指定模型与 `fork_turns: "none"`；不虚构持久化 agent profile。
   - 写权边界用配置强制而非提示词：slice builder 由 `disallowedTools` 硬禁 `git commit/push/merge` 与 `gh`（已核对 2.1.218 的 markdown agent 解析器支持该字段）。
   - `tools:` 白名单会连 MCP 工具一起挡掉：要求用 GitNexus 的只读代理必须显式列出所需 `mcp__gitnexus__*` 工具（交叉审查修）。
   - 仓库内的 agent 定义不写个人环境假设（如 `rtk` 前缀——本机已有全局 hook 自动改写）。

6. **只清活动残留，不改写历史。**
   - 更新 `AGENTS.md`、`CLAUDE.md`、`docs/assembly.md` 和活动 S8 change。
   - 已从主线删除的 `docs/to-codex.md`、`docs/to-claude*.md` 不得恢复。
   - PTY 主路线只保留在归档材料中作为死端记录。

## Risks / Trade-offs

- [Claude/Codex 模型别名或工具字段以后变化] → 使用当前官方支持的项目 agent 格式，并保持定义最小；升级工具时用 `claude doctor`/官方文档复核。
- [轻量模型低估风险] → 明确自动升级条件，contract guardian 和最终主代理保留裁决权。
- [多个文档再次漂移] → `AGENTS.md` 为当前协作入口，`CLAUDE.md` 只作 Claude 启动摘要并链接入口；OpenSpec 保存变更契约，不另建分工台账。
- [活动 S8 wording 清理被误认为功能变化] → 只移除供应方所有权文字，不改任务内容、顺序或验收。
- [子代理共享 worktree 相互覆盖] → 并行只读、单写者；提交和推送由主代理统一完成。

## Migration Plan

1. 建立并校验本 OpenSpec change。
2. 更新根协作入口与 Claude 启动说明。
3. 新增 Claude 项目子代理；写入 Codex spawn 路由。
4. 清理活动文档和 S8 artifacts 中的旧供应方分工文字。
5. 搜索残留、运行 OpenSpec 校验、Claude 配置健康检查和 GitNexus change detection。
6. 在 Codex 分支提交，交由 Claude 交叉审查后合入 `main`。

回滚时可整体撤销该治理提交；不会影响应用数据或运行时状态。

## Open Questions

无。具体任务使用哪一个实现代理由主代理根据 task capsule 和升级条件动态决定。
