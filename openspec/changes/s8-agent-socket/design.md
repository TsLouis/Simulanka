## Context

现有 S8 已落下四块可复用地基：归一事件词表、OpenCode JSON 适配、逐条 JSONL 转录、ChatNode 的流式文本/工具卡片/全屏展示。但它仍有三处产品语义泄漏：

1. server 的 `WorkSession` 和首轮 prompt 只认识 task card；
2. 前端平行维护 `discussionMessages` / `workMessages` 与 `activeChatKind`；
3. 会话运行时直接调用 OpenCode，Simulanka transcript 被误当成未来 Provider 上下文的候选来源。

Codex CLI 的现行稳定接口已经提供 `codex exec --json`、`codex exec resume <SESSION_ID>` 与 `thread.started`/`turn.completed` JSONL；完成事件可报告 `cached_input_tokens`。平台应复用这些原生能力，而不是在每轮重放历史或重建一套上下文窗口。

## Goals / Non-Goals

**Goals:**

- 一套领域无关的 Session/Turn/Event 生命周期和一种可多实例化的 ChatNode 前端壳。
- Provider 原生 session/thread 是对话历史、工具状态、压缩和 cache 的主权威。
- Simulanka 上下文仅作用户显式选择的、确定且可检查的增量补充。
- 同一 ContextBundle 在同一 Provider 会话中不重复发送；内容变化产生新 digest。
- Provider 的原生配置、AGENTS、skills、MCP、sandbox 与 approval 行为默认原样继承。
- 用户只用前端即可创建、切换、恢复、分叉、中断和归档会话，并看见上下文及 cache usage 遥测。

**Non-Goals:**

- 不替 Provider 实现历史裁剪、上下文压缩、prompt cache 或工具调度。
- 不把 Session、Turn、消息或 ChatNode UI 投影建成物理图节点/Profile。
- 不定义“讨论、实验、派工、审查”等工作流模式。
- 不在本 change 内实现 run agent 括号、diff/acceptance 结果面板或 Profile/Capability 注册表。
- 不保证某一轮一定产生 cache hit；平台只保证不主动破坏稳定前缀并如实呈现 Provider 遥测。

## Decisions

### 1. Session 是 sidecar 资源，不是领域图实体

平台 Session 保存 Simulanka id、Provider id、native session id、workspace、父会话/fork 点、状态与事件文件。消息和工具事件继续存在 `.simulanka/agent/`，避免高频转录污染 Node/Edge 图。领域程序以后可通过确定性 Projection 把摘要或结果落图。

一个 Session 在生命周期内绑定一个 Provider。更换 Provider 或模型通过 fork 新会话表达；不得在原会话中静默换后端。

conversation tree 是 Session sidecar 的确定性投影，不另建 `session_ids[]`
索引。根 Session 的 `session_id` 同时是不可变 `tree_id`；其 created
事件显式记录创建时的 `scope_root_id`（顶层为显式 `null`）。fork 只记录
`parent_session_id`，通过父链继承 tree 和 scope。旧 created 事件缺少
scope 时归为 `unassigned/legacy`，只能从独立恢复入口认领，不混入任一正常
graph view。

### 2. ProviderAdapter 只做 transport 与事件翻译

Adapter 合同包含：

- `capabilities`：`native_resume`、`native_fork`、`interrupt`、`tool_events`、`usage`；
- `start_turn`：新建原生会话并返回规范化事件；
- `resume_turn`：用 native session id 续接；
- `interrupt`：取消活动 TurnHandle；
- 原始事件 → `SessionEvent` 的薄适配。

Codex adapter：

- 首轮使用 `codex exec --json`；
- 后续轮使用 `codex exec resume <SESSION_ID> --json`；
- 从 `thread.started` 捕获 native id；
- 从 `turn.completed.usage` 记录 `input_tokens`、`cached_input_tokens`、`output_tokens` 等 Provider 原生字段。

OpenCode adapter 承接现有参数构造和 normalize 逻辑。Provider 不支持 native resume 时，平台明确显示 `stateless` 降级；MUST NOT 悄悄把全部 transcript 拼进新 prompt。

### 3. Simulanka 上下文是增量附件，不是主提示

每轮输入由两个部分组成：

1. 用户原始消息；
2. 可为空的 supplemental ContextBundle 列表。

平台不添加常驻 system prompt，不复述历史，不自动附加全图，也不因当前画布选择变化而后台修改原生会话。只有用户显式附加或上层程序显式声明的 RefSet 才进入补充上下文。

Adapter 若有结构化附件通道则优先使用；否则在本轮消息尾部追加一个稳定边界块。没有新增 bundle 时，发送给 Provider 的用户文本保持原样。

平台按 native session id 记录已经发送过的 bundle digest：

- digest 未见过：本轮附加；
- digest 已见且内容未变：仅在 UI 保留引用，不重复发送；
- 引用实体内容变化：编译出新 digest，并作为增量附加。

Provider 自己决定旧内容的压缩、淘汰与 cache；Simulanka 不通过重复发送进行“修复”。

### 4. ContextBundle 内容寻址、确定序列化

`RefSet` 是由统一 `ContextRef(kind, id)` 组成的有序去重序列；`kind`
当前取 `node / edge / port`，且跨 kind 的用户选择顺序保持不变。Context
compiler 在一个 graph version 上解析引用，并输出：

- bundle schema/compiler version；
- source refs；
- 每个实体的 id/type/name、稳定字段和出处；
- graph version；
- 明确的 omissions；
- canonical payload；
- `sha256` digest。

同一 compiler version、同一实体内容与同一 policy MUST 产生逐字节一致的 payload。Bundle 写入 `.simulanka/agent/contexts/<digest>.json`，SessionEvent 只引用 digest 和本轮 `sent/skipped` 状态。

上下文内容按 `instruction` 与 `reference` 分隔；图 attrs、文件内容和工具输出默认属于不可信 reference，不得提升为系统指令。前端预览展示最终 payload、来源和省略项。

### 5. Simulanka transcript 用于 UI 与审计，不用于隐式 replay

保留词表：

`user_msg / agent_text / tool_call / tool_result / status / error`

Provider、native session id、context digests、usage、interrupt reason 等放入事件字段或 `details`。旧 `.jsonl` 文件仍可读取；缺失新字段按 legacy 会话显示。

会话列表可通过扫描 created 事件建立，首版不另建易失同步的数据库索引。
server 在扫描结果上解析 parent forest，输出 `tree_id` 和有效
`scope_root_id`，并可按当前 graph view scope 过滤。父链缺失或成环必须作为
可见损坏报告，不得把分支静默挂到另一棵树。

### 6. 一种会话壳，一棵树一个 ChatNode

ChatNode 是 UI-sidecar 投影而非 Node/Edge/Port。其稳定 UI id 为
`chat:<tree_id>`，位置复用 `.simulanka/ui/positions.json` 现有的
per-view bucket；活动分支按 tree 记忆。graph view 切换只决定哪些 ChatNode
挂载，不会创建 Provider Session、发送消息、编译 ContextBundle 或改变
Provider 上下文。

一个新根 Session 创建一棵树和一个 ChatNode；fork 保留同一 tree id 并在
节点内部增加分支，MUST NOT 创建第二个 ChatNode。归档是当前分支的非破坏
状态变化，首版不提供整树归档或跨 scope 搬家。scope 节点后来不存在时，会话
树进入独立恢复入口而不删除。

前端状态收敛为：

```text
sessions_by_id
trees_by_scope[scope_root_id][tree_id]
active_session_by_tree[tree_id]
pending_refs_by_tree[tree_id]
events_by_session[session_id]
```

ChatDock 的上下文条展示当前 ChatNode/草稿树的 pending refs；用户可删除、
固定和预览。发送首条消息时在当前 graph view scope 创建根 Session，此后使用
该树的 active branch。流式回调必须捕获 `{tree_id, session_id}`，不得因用户
在 turn 中途下钻而把事件写入另一层或另一棵树。UI 不显示
`discussion/work` 类型，也不提供 task 专属“派工”或“开始”动作。

scope 只控制 UI 归属和可见性，永远不等价于 ContextRef。即使 ChatNode 位于
某个子图内，没有显式 RefSet 时仍逐字发送用户消息；相同 bundle 的 sent
digest 仍按 native session id 隔离，fork 分支不会因共享 ChatNode 而共享去重
账本。

停止按钮只在 turn running 时出现。`暂停`在 v1 的精确定义是：请求 Adapter 中断当前 TurnHandle，保留 native session id、转录与工作区；下一条消息继续同一原生会话。

### 7. 外部副作用与图事务不伪装为一个原子操作

SessionCommand 管理会话；PatchIntent 继续只管理图事务。Agent 在工作区或图中产生的副作用沿现有 CLI、写权闸和测量机制发生。Session 不根据 agent 文本猜测“任务已完成”。

## Risks / Trade-offs

- [Provider CLI 参数或事件格式漂移] → 每个 Adapter 独立样本锁；前端只认 SessionEvent。
- [错误地宣称 cache 成功] → 只展示 Provider 返回的 usage；验收验证“不重复发送”，不设 cache hit 数值下限。
- [原生 session 被外部删除] → 会话标 `native_missing`，提供显式 fork/new session；不静默 replay。
- [ContextBundle 包含 prompt injection] → instruction/reference 分区、来源标识、预览与稳定边界。
- [server 重启时活动进程句柄丢失] → 历史 `running` 会话恢复为 `orphaned/interrupted`，不得显示仍在执行。
- [legacy discussion 暂时并存] → 只保留兼容端点；前端迁壳后不再把它当会话类型。
- [会话树与 ChatNode 重复或漂移] → tree id 取根 Session id，分支通过 parent forest 推导；不维护第二份 session id 列表。
- [跨层切换污染流式事件] → turn 回调捕获 tree/session id，导航只切挂载集合。
- [旧会话无 scope 或 scope 节点已删除] → 放入独立 unassigned/recovery 入口，不混入当前层也不删除历史。

## Migration Plan

1. 先加入 ProviderAdapter、ContextBundle 与通用 Session 模型，不移除旧端点。
2. 用 OpenCode adapter 包装现有实现，确保旧 U1 流式行为不回退。
3. 加入 Codex adapter，并验证首轮 `thread.started`、原生 resume 与 usage 映射。
4. 前端迁移为按 scope/tree/session 分层的状态；完成历史恢复与中断。
5. 删除 task 派工入口和 discussion/work 状态分支；legacy discussion 端点保留兼容。
6. 独立提案后再处理 run-agent-bracket 与 Profile/Capability 注册表。

回滚时可恢复旧前端入口；旧 session JSONL 未迁移、未破坏。

## Open Questions

- Claude CLI 的稳定流式与 resume 形态在其 Adapter 开工时再以本机版本和官方文档确认，不预写成跨 Provider 假设。
- Provider 若未来公开结构化附件 API，可替换稳定文本边界块，但不得改变 ContextBundle 的 digest 与审计语义。
