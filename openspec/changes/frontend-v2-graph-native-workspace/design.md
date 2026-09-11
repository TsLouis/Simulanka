## Context

现有 Simulanka 前端已经拥有统一 Node/Edge/Port 渲染、Registry descriptor、server affordances、SSE、Inspector、ChatDock/ChatNode、Session 与显式 ContextBundle。问题不在“缺能力”，而在能力的默认编排：常驻面板和聊天壳占据画布，内部机制词直接暴露给用户，Agent 的主要表达仍偏消息而不是图。

本 change 不改变“kernel 是图的唯一写者”“人裁优先”“ContextBundle 只来自显式附加 RefSet”等底层约束。它改变的是前端交互语法：图成为默认共同语言，机制退到系统层。

## Goals / Non-Goals

**Goals:**

- 打开项目时主要看到 Graph，而不是工具面板。
- Node 在不同 zoom 下显示恰当的信息密度；Port 是节点正常表达的一部分，但远距离可隐藏。
- 选择对象后即可轻量 Ask/Open，不要求先打开永久 Inspector/Chat。
- Agent 能围绕 node/edge/port/selection 工作，并用图上 Draft/annotation/attention 表达想法。
- 产品语言简洁，内部安全、审计和来源信息仍可追溯。
- 优先复用现有 Registry、affordance、Session、ContextBundle 和 proposed semantics。

**Non-Goals:**

- 本 change 首阶段不放宽 frozen write matrix。
- 不把 Agent Companion 做成复杂游戏角色或动画系统。
- 不删除 Session transcript、ContextBundle 审计或 Provider adapter。
- 不把临时 annotation/attention 持久化成正式 Node/Edge。
- 不一次性重写 LiteGraph 引擎或图持久化格式。

## Decisions

### 1. Default shell is quiet and canvas-first

默认工作区只有轻量 TopBar、窄 Activity Bar、Graph Canvas 和低存在感 Agent Companion。Inspector、file/run/session secondary surfaces 按需滑出或浮现。

`App.svelte` 不再作为所有 UI concern 的永久宿主；实现阶段逐步提取 WorkspaceShell、TopBar、ActivityBar、ContextPopover、AgentCompanion 等组件，但保持现有数据加载和导航语义。

### 2. Node information density follows zoom

Node presentation 分三级，但用户不感知“模式”：

- overview：类型/图标 + 名称；Port 与非必要字段隐藏。
- working：显示可连接 Port 的视觉接口；关键状态可见。
- detail：显示 Port 名称及 input/output 语义、受控 PresentationSpec 字段和必要 badge。

阈值由前端统一策略决定，不写进 Profile。具体字段仍由 PresentationSpec 决定；Port 列表来自真实 Graph payload/Registry contract，不复制领域类型规则。

### 3. Port is a first-class visual affordance

Port 不是“详情属性”。在 working/detail zoom 下，输入 Port 固定投影在左侧、输出 Port 在右侧；方向、type 和连接 eligibility 继续由 Registry/Edge Profile 约束。远距离隐藏 Port 是视觉降噪，不代表 Port 不存在或不可追溯。

root boundary IO 仍遵守现有括号/隧道规则；本 change 只统一其视觉语言。

### 4. Selection reveals context, not a permanent panel

单击对象先高亮对象及相关关系，并显示小型 contextual controls，例如 Ask、Open、more。完整 Inspector 只在 Open、快捷键或明确请求时出现。

Inspector 继续由 PresentationSpec 与 affordance 驱动；只是默认可见性降低，不削弱能力。

### 5. Agent Companion is a surface, not a new semantic entity

Companion 是 UI sidecar，不成为 Node/Edge/Port/Profile。它代表当前可交互 Agent/session state，可在画布边缘或 selection 附近出现。

用户可通过 Ask、显式 attach、拖拽 selection 到 Companion 等方式构造 pending RefSet。只有用户明确完成附加的 RefSet 才进入 ContextBundle；当前 viewport、祖先和邻居不会因为视觉靠近而自动注入。

### 6. Graph-native expression has three persistence levels

Agent 输出分为：

1. **Attention**：临时 highlight/arrow/focus，纯 UI，不持久化图。
2. **Annotation**：依附对象的短解释，可属于 conversation/session sidecar；不自动成为 semantic graph。
3. **Draft**：对新增 Node/Edge/关系结构的视觉提议。若底层已有 proposed/ghost 安全语义则映射它；若只是预览则保持 projection sidecar，直到通过现有 server action 提交。

正式 semantic graph 仍只能由 server/kernel 权威写入。

### 7. Product language hides mechanism terms

UI 默认使用：Draft、Keep、Dismiss、Context、Why、Related、Needs attention。底层字段可继续叫 proposed、verdict、provenance 等；高级详情/调试界面可显示原始字段。

### 8. Trust model changes incrementally

首阶段不修改权限，只改变展示与操作路径。后续若要实现“reversible action auto-apply + Undo”，必须证明：

- action 可由现有 event/checkpoint/history 完整逆转；
- undo 的事务边界明确；
- 不覆盖 `verdict_by=user` 或其他人工最终决定；
- server 仍是最终 authority。

无法满足者继续要求显式确认。

### 9. Pixel visual style is subordinate to readability

采用清晰、克制的像素视觉语言：深色低噪背景、1–2px 边框、有限语义色、轻量状态动画。禁止用大量 glow、装饰性城堡/星空背景或游戏 HUD 元素侵占图语义。

## Risks / Trade-offs

- [隐藏机制导致用户不知道发生了什么] → 关键变更提供局部反馈、Undo/详情入口和可追溯来源。
- [zoom 信息密度抖动] → 使用带 hysteresis 的阈值或稳定区间，避免滚轮轻微变化反复切换。
- [Agent Companion 变成新聊天壳] → 默认小而安静；长 transcript 只在用户主动展开 Discussion 时出现。
- [Draft 与正式图混淆] → 必须同时使用透明度/线型/标识，不只依赖颜色。
- [显式 context 交互过重] → Ask selection 可作为一步 attach，但 UI 必须显示将发送的对象，并保留 preview。
- [拆 App.svelte 引入大范围回归] → 先抽 shell/纯展示组件，保持原 API/store 流；每 slice 单独验证。

## Migration Plan

1. 建立 Frontend v2 shell 与设计 tokens，不改变 server API。
2. 抽离默认常驻 Inspector/Chat 的布局依赖，保持旧组件可按需打开。
3. 在 LiteGraph adapter 增加 zoom-aware card/Port presentation，并做人工目验。
4. 增加 selection ContextPopover 与 Ask/Open 流程。
5. 增加 Agent Companion，复用现有 session/context API。
6. 增加 Attention/Annotation/Draft projection，优先映射现有 proposed semantics。
7. 运行前端与后端回归，更新 authoritative `docs/frontend.md`。
8. 再评估是否另开或扩展 trust/undo change；未验证前不放宽写权。
