## Why

Simulanka 已经具备 Registry 驱动的通用图工作台、Session、显式 supplemental context 与 server 权威 affordances，但旧前端曾以常驻 Inspector、ChatDock/ChatNode 和机制性术语承载这些能力。随着图成为人和 Agent 的共同工作对象，这种“面板 + 聊天框”结构会挤压 Canvas，并迫使用户理解 provenance、verdict、ghost 等内部机制。

用户已明确批准 Frontend v2 方向：默认界面极简、Canvas 优先；Node/Edge/Port/selection 是协作的一等对象；Agent 以轻量 Companion 形式依附图工作；Agent 的解释和建议优先通过图上的 Draft/annotation/attention 表达；低风险能力尽量交给系统与 harness，在真正高风险语义提交时才显式请求确认。

本 change 的目标是在不削弱现有 kernel/server 写权、安全和可追溯约束的前提下，把复杂机制隐藏到系统下面，让图本身成为主要人机交流媒介。

## What Changes

- 将默认工作区重构为 canvas-first shell：轻量顶栏、大面积 Graph Canvas；Inspector 与长对话按需出现而非常驻。
- Node 展示改为随缩放渐进展开：所有 zoom 下保留每个真实 input/output Port handle 的独立位置；远距离只隐藏 Port 文字与详情；近距离显示 Port 名称、关键字段与 PresentationSpec 详情。
- 选择 Node/Edge/Port 后优先出现轻量上下文动作（如 Ask / Open / more），完整 Inspector 作为按需详情面。
- 将 Agent 从永久 ChatDock/ChatNode 视觉中心降为轻量 Companion；主要 context 手势为按住 `A` 连续点击一个或多个 node/edge/port、松开 `A` 后直接输入问题。对象 surface 上的 `Ask Agent` / selection attach 作为备用入口；不再维护 drag-to-Pet 作为第二套 pointing 交互。
- Agent 的图上输出新增 Draft / annotation / attention 呈现层。第一版 `graph-chat` 可通过严格的 structured sidecar 在真实 explicit refs 上指向、注释或绘制临时 `draft_graph`；这些 projection 不写 semantic graph。
- 产品语言弱化 provenance/verdict/ghost 等机制词：对应能力通过 Context/Why、Draft、Keep/Dismiss 等轻量交互表达；内部字段和审计语义不因此删除。
- 明确风险分层方向：safe UI/projection 行为可直接发生；可逆图修改优先依靠 history/undo；真正改变研究语义或覆盖人工决定的操作继续受现有写权和显式确认约束。该 change 首阶段只做前端交互与现有语义映射，不擅自放宽 frozen write matrix。
- 像素风作为视觉语言实现，但不把复古装饰置于可读性之上；图信息密度、Port 可读性和操作反馈优先。

## Capabilities

### Modified Capabilities

- `registry-driven-workbench`: 增加 canvas-first shell、zoom-aware Node/Port presentation、contextual object actions 和轻量 Inspector 要求。
- `agent-session`: 前端不再要求永久 ChatNode/ChatDock 可视形态；同一 Session 生命周期可通过图原生 Companion/attached discussion 表达。
- `supplemental-context`: 增加 A-pointer、selection/Ask 等显式附加交互，但仍只编译用户明确指给 Agent 的 RefSet。

### New Capabilities

- `graph-native-agent-expression`: 定义 Agent 在 Canvas 上通过 Draft、annotation、attention 和轻量文字表达建议的产品合同，并区分临时 conversation layer 与正式 semantic graph。

## Impact

- 前端：`App.svelte` 逐步减少 workspace/session presentation 职责；旧 `ChatDock.svelte` / `ChatNode.svelte` 已从展示架构删除；`NodeInspector.svelte` 弱化为详情面；`litegraph-adapter.ts` / `theme.ts` 负责成熟 Node/Port 基线；`AgentCompanion.svelte`、Conversation Projection 与 Canvas projection 模块承载显式对象协作。
- Server/kernel：首阶段不改变 frozen write matrix、Node/Edge/Port 持久化 schema 或 session/context API；如后续要放宽 Agent 自动写入，必须另开规格或更新本 change 并做 frozen-contract review。
- 文档：落地后同步 `docs/frontend.md`；内部仍保留准确机制词，产品 UI 使用更轻的语言。
- 验证：需要前端 build/typecheck、现有 server/frontend 行为回归，以及人工目验默认画布、Port zoom 层级、连续多对象 A-pointer、显式 Agent context 和结构化 Draft/annotation/attention 表达。
