## Why

S8 已经证明浏览器能够显示流式 agent 文本与工具事件，但当前实现把通用会话壳绑定到 `task` 派工、`discussion/work` 模式和 OpenCode。平台需要先建立一个不理解“讨论、实验或派工”的原生 CLI 会话插座：Simulanka 管理会话、可见性和补充上下文，Codex、Claude、OpenCode 等 Provider 继续管理自己的历史、工具、压缩与 prompt cache。

## What Changes

- 把 `WorkSession` 收敛为领域无关 Session：任意会话均可创建、恢复、分叉、中断和归档，不再要求 task/run。
- **BREAKING（前端交互）**：删除 task 专属「派工」入口与 `discussion/work` 模式选择；用户在统一 ChatNode 中直接发送消息，首条消息懒创建会话。
- 新增结构化 `RefSet` 与不可变 `ContextBundle`。上下文只来自用户或上层程序显式附加的节点、边、端口，并且只是本轮增量补充，不替代 Provider 原生上下文。
- 新增 Provider Adapter 合同。适配器 MUST 优先使用原生 session/thread resume，不得把完整 Simulanka transcript 重新拼回 prompt；Codex 首个适配器走 `codex exec --json` / `codex exec resume <SESSION_ID>`，OpenCode 适配器承接现有实现。
- 增量上下文序列化保持确定、可寻址、可预览；相同 bundle 不重复注入。Provider 报告 cache usage 时，前端与转录显示 `cached_input_tokens` 等原生遥测，但平台不伪造 cache 命中。
- 保留现有归一事件流、JSONL 转录、actor 贯通、工具调用卡片和统一 ChatNode 外壳；补齐会话索引、历史恢复、停止和 Provider 能力降级展示。
- `run agent` 骑 run 括号及 run/diff/acceptance 工作流退出本 change，后续作为上层执行程序独立提案。

## Capabilities

### New Capabilities

- `agent-session`: 领域无关的会话生命周期、事件流、持久化、恢复、分叉、中断、归档与统一前端壳。
- `supplemental-context`: `RefSet → ContextBundle` 的显式补充上下文、确定性序列化、增量注入、预览与可追溯要求。
- `provider-adapter`: 外部 agent CLI 的能力声明、原生会话续接、事件归一、取消与 cache usage 遥测合同。
- `actor-passthrough`: Provider 子进程继承 Simulanka actor 身份，CLI 显式参数仍拥有最高优先级。

### Modified Capabilities

（无；主规格目录尚无已归档 capability。）

## Impact

- 后端：`agent/session.py`、`server/sessions.py`、`server/app.py`，新增 Provider/Context 边界与会话索引。
- 前端：`App.svelte`、`ChatNode`、`ChatDock`、API DTO；删除 type/mode 专属分支，增加会话管理与上下文预览。
- 兼容：现有 session JSONL 可读；旧 `discussion` 端点在迁移期保留为兼容入口，但不再定义平台会话类型。
- 不动：Node/Edge/Port schema、PatchIntent 原子性、写权矩阵、run 测量和领域工作流。
