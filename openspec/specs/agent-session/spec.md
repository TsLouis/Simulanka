# agent-session Specification

## Purpose
Frontend and server contracts for provider-neutral sessions, explicit context, and Agent Companion presentation.
## Requirements
### Requirement: 领域无关会话生命周期
系统 SHALL 提供领域无关的 Session；会话创建、恢复、分叉、中断和归档 MUST NOT 要求 task、run、discussion 或其他领域节点。用户在 Agent Companion 的空白草稿中发送首条消息时 SHALL 懒创建会话。

#### Scenario: 无锚首轮
- **WHEN** 用户未选择任何图实体并在 Agent Companion 的空白草稿中发送消息
- **THEN** 系统创建会话并发送该消息，不要求先执行派工、开始实验或选择模式

#### Scenario: 任意选择集首轮
- **WHEN** 用户附加任意节点、边或端口后发送首条消息
- **THEN** 系统创建同一种 Session，并把选择集作为 supplemental context，而不是改变会话类型

### Requirement: 一场会话绑定一个 Provider
Session SHALL 持久化平台 session id、Provider id、native session id、workspace、状态和 parent/fork 元数据。一场会话在生命周期内 MUST 绑定同一 Provider；更换 Provider 或模型 SHALL 建立 fork 或新会话。

#### Scenario: 更换 Provider
- **WHEN** 用户在已有 Codex 会话中选择 OpenCode
- **THEN** 系统创建显式 fork 或新会话，原会话 Provider 与 transcript 保持不变

### Requirement: 归一事件流与自持转录
server SHALL 将 Provider 原始输出翻译成 `user_msg / agent_text / tool_call / tool_result / status / error` 事件，并边流边追加到 Simulanka 自持 JSONL。前端 SHALL 只消费归一事件，不依赖 Provider 原始格式。

#### Scenario: 工具轮流式显示
- **WHEN** Provider 在一轮中输出文本并调用工具
- **THEN** 前端按到达顺序显示 agent 文本、默认折叠的工具调用/结果卡和最终状态

#### Scenario: 未知 Provider 事件
- **WHEN** Adapter 收到无法识别的原始事件
- **THEN** Adapter 丢弃或降级为 status/error，事件流不中断且原始格式不泄漏给前端

### Requirement: 会话列表和刷新恢复
server SHALL 提供按 conversation tree 与 graph view scope 投影的会话列表与单场历史读取；前端刷新后 SHALL 能恢复会话元数据、完整消息、工具卡、上下文引用和最后状态。旧格式 JSONL 缺少新字段时 MUST 以 legacy/unassigned 会话可读展示，且不得混入任一正常 scope。

#### Scenario: 刷新恢复
- **WHEN** 用户在若干轮后刷新页面
- **THEN** 用户可从会话列表重新打开该会话并看到完整归一历史

### Requirement: 会话树保留 scope 与活动分支
每个根 Session SHALL 开始一棵 conversation tree，其根 session id SHALL 作为不可变 tree id，并绑定根 Session 创建时的 graph view root。fork SHALL 通过 parent session 继承 tree 与 scope；前端 SHALL 在 Agent Companion 的按需 history surface 中选择 tree 与活动分支，而 MUST NOT 将 Session 投影为 Canvas 窗口、Node、Edge、Port 或 Profile。

#### Scenario: 当前层创建新树
- **WHEN** 用户在当前 graph view 的 Agent Companion 草稿发送首条消息
- **THEN** 系统创建根 Session，以其 id 建立一棵绑定该 graph view scope 的 tree，Canvas 不增加会话窗口

#### Scenario: fork 留在原节点
- **WHEN** 用户从 Agent Companion history 中的活动 Session fork
- **THEN** 新 Session 成为同一 tree 的分支并可在同一 history surface 内切换，Canvas 不增加会话窗口

#### Scenario: 跨层导航与返回
- **WHEN** 用户从 scope A 下钻到 scope B 后再返回 A
- **THEN** B 只显示 B scope 的 Session tree；返回 A 后恢复 A 的 tree 和活动分支，导航本身不创建 Session 或 Turn

#### Scenario: 旧会话没有 scope
- **WHEN** server 扫描到 created 事件缺少 scope 的旧会话树，或原 scope 节点已不存在
- **THEN** 该树进入独立 unassigned/recovery 入口，历史保持可读且不出现在任一正常 graph view

#### Scenario: server 重启时遗留 running
- **WHEN** server 重启后转录最后状态仍为 running 但没有活动 TurnHandle
- **THEN** 系统显示 orphaned/interrupted，不得声称该轮仍在执行

### Requirement: 中断当前轮而保留会话
Adapter 支持 interrupt 时，server SHALL 允许用户中断当前 TurnHandle，追加 `status: interrupted`，并保留 native session id、转录、ContextBundle 和已发生的工作区副作用。下一条消息 SHALL 继续同一原生会话。

#### Scenario: 用户暂停
- **WHEN** Provider 正在运行且用户点击暂停
- **THEN** 当前轮被请求中断、消息流出现已中断状态，后续消息仍以原 native session id resume

#### Scenario: Provider 不支持中断
- **WHEN** 当前 Adapter 未声明 interrupt capability
- **THEN** 前端不显示可执行的暂停按钮，并明确显示该能力不可用

### Requirement: 统一壳而无工作流模式
所有 Session SHALL 使用同一领域无关生命周期与事件合同；前端由 Agent Companion 与按需 history surface 呈现，不得藉此创建新的领域会话类型。核心 UI MUST NOT 提供 `discussion/work` 模式选择、task 专属派工或开始实验按钮；工作流差异只能由以后显式加载的程序、prompt preset 或卡片扩展表达。

#### Scenario: 从 task 节点交互
- **WHEN** 用户选择一个 task 节点并打开 Agent Companion
- **THEN** UI 仅把 task 作为普通上下文引用，不显示派工或干活会话类型

### Requirement: 失败和能力降级可见
Provider 启动失败、native session 缺失、事件解析失败、工具失败和中断失败 SHALL 进入归一事件流或会话状态，页面 MUST NOT 把失败显示成完成。

#### Scenario: 原生会话被外部删除
- **WHEN** Provider resume 返回 native session 不存在
- **THEN** 会话标记为 native_missing，并提供显式新建/fork 路径，不自动 replay transcript
