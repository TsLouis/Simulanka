## MODIFIED Requirements

### Requirement: 统一壳而无工作流模式
所有 Session SHALL 使用同一领域无关生命周期与事件合同；核心 UI MUST NOT 提供 `discussion/work` 模式选择、task 专属派工或开始实验按钮。前端 MAY 以 Agent Companion、对象附着 discussion、按需 transcript 等不同视觉 surface 呈现同一 Session，但这些 surface MUST NOT 创建新的领域会话类型。

#### Scenario: 从 task 节点交互
- **WHEN** 用户选择一个 task 节点并 Ask Agent
- **THEN** UI 仅把 task 作为普通上下文引用并复用同一种 Session，不显示派工或干活会话类型

### Requirement: 会话列表和刷新恢复
server SHALL 提供按 conversation tree 与 graph view scope 投影的会话列表与单场历史读取；前端刷新后 SHALL 能恢复会话元数据、完整消息、工具卡、上下文引用和最后状态。前端 MUST NOT 因默认隐藏长 transcript 而丢失或弱化恢复能力。

#### Scenario: Companion 默认折叠
- **WHEN** 页面刷新后存在历史 Session 但用户尚未展开 discussion surface
- **THEN** Agent Companion 可保持轻量状态，用户仍可显式恢复完整历史与工具事件

## ADDED Requirements

### Requirement: Agent Companion 不是语义图实体
前端 Agent Companion SHALL 是 Session/UI sidecar，而 MUST NOT 被创建为 Node、Edge、Port 或 Profile。其位置、动画和展开状态不得影响 semantic graph。

#### Scenario: Companion 在 Canvas 上移动
- **WHEN** 用户或布局逻辑移动 Agent Companion
- **THEN** Graph manifest、Node/Edge/Port 集合和 Registry 均不发生变化

### Requirement: 长对话按需展开
默认工作区 SHALL NOT 永久占用大面积 Canvas 展示 transcript。用户明确请求继续长讨论、查看历史或工具事件时，前端 SHALL 提供可展开 discussion surface，并继续消费同一归一 SessionEvent 流。

#### Scenario: 简短图上协作
- **WHEN** 用户选中两个节点并 Ask Agent，Agent 只返回一个短解释和 Draft
- **THEN** UI 可在图上完成该轮，不自动展开完整聊天面板
