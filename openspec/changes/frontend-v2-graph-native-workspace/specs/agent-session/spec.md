## MODIFIED Requirements

### Requirement: 统一壳而无工作流模式
所有 Session SHALL 使用同一领域无关生命周期与事件合同；核心 UI MUST NOT 提供 `discussion/work` 模式选择、task 专属派工或开始实验按钮。前端 MAY 以 Agent Companion、对象附着 discussion、按需 transcript 等不同视觉 surface 呈现同一 Session，但这些 surface MUST NOT 创建新的领域会话类型。

#### Scenario: 从 task 节点交互
- **WHEN** 用户选择一个 task 节点并 Ask Agent
- **THEN** UI 仅把 task 作为普通上下文引用并复用同一种 Session，不显示派工或干活会话类型

### Requirement: 会话列表和刷新恢复
server SHALL 提供按 conversation tree 与 graph view scope 投影的会话列表与单场历史读取；前端刷新后 SHALL 能恢复会话元数据、完整消息、工具卡、上下文引用和最后状态。旧格式 JSONL 缺少新字段时 MUST 以 legacy/unassigned 会话可读展示，且不得混入任一正常 scope。前端 MUST NOT 因默认隐藏长 transcript 而丢失或弱化恢复能力。

#### Scenario: 刷新恢复
- **WHEN** 用户在若干轮后刷新页面
- **THEN** 用户可从会话列表重新打开该会话并看到完整归一历史

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


### Requirement: Session 编排独立于 Canvas 展示
前端 SHALL 将 Session tree/branch、history/recovery、provider capability、streaming、stop/fork/archive 和显式 refs/preview 编排置于独立 controller/store。该层 MUST NOT 依赖 Canvas 节点或图位置，且 MUST 继续使用现有 server Session API 与 DTO。

#### Scenario: 刷新包含多棵会话树的 Workspace
- **WHEN** 恢复当前 scope 的多棵 Session tree
- **THEN** 仅轻量 Companion 默认出现，Canvas 不创建任何会话窗口；用户可显式打开 history 切换 tree/branch 并读取完整事件

#### Scenario: 关闭完整历史后继续流式响应
- **WHEN** 用户在 Agent 回复期间关闭 history
- **THEN** controller 继续接收同一 Session 的事件，重新打开 history 可查看工具输入/输出、上下文引用与状态，并可按 provider 能力 stop、fork 或 archive

### Requirement: 会话树保留 scope 与活动分支
每个根 Session SHALL 开始一棵 conversation tree，以根 session id 作为不可变 tree id，并绑定创建时的 graph view root。fork SHALL 通过 parent session 继承 tree 与 scope。前端 SHALL 在 Companion 中选择当前 scope 的 tree 与活动分支，MUST NOT 将 tree 投影成 Canvas 窗口，也 MUST NOT 创建 Node/Edge/Port 或 Profile 来表示 Session。

#### Scenario: 当前层创建新树
- **WHEN** 用户在当前 graph view 的 Companion 草稿发送首条消息
- **THEN** 系统创建根 Session 并保留其 tree 与 scope，Companion 选中该 tree，Canvas 不增加会话窗口

#### Scenario: fork 留在原树
- **WHEN** 用户从当前活动 Session fork
- **THEN** 新 Session 成为同一 tree 的分支，按需 history 可切换分支，Canvas 不增加任何会话窗口

#### Scenario: 跨层导航与返回
- **WHEN** 用户从 scope A 下钻到 scope B 后再返回 A
- **THEN** Companion 只选择当前 scope 的 tree；返回 A 后恢复 A 的 tree 和活动分支，导航本身不创建 Session 或 Turn

#### Scenario: 旧会话没有 scope
- **WHEN** server 扫描到 created 事件缺少 scope 的旧会话树，或原 scope 节点已不存在
- **THEN** 该树进入独立 unassigned/recovery 入口，历史保持可读且不出现在任一正常 graph view

## REMOVED Requirements

### Requirement: 一棵会话树恰有一个 scoped ChatNode
**Reason:** #18 删除 Session tree 到 Canvas 聊天窗口的旧展示架构。
**Migration:** 以“会话树保留 scope 与活动分支”保留既有 Session/tree/scope/fork/recovery 合同；通过 Agent Companion 和按需 history 访问，不迁移或重写 server Session 数据。
