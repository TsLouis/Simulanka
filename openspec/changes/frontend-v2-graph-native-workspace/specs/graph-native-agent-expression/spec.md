## ADDED Requirements

### Requirement: Agent 表达优先使用图原生 surface
前端 SHALL 支持 Agent 在 Canvas 上通过 attention、annotation 和 Draft 表达与当前图对象相关的想法。纯文字消息仍可使用，但 MUST NOT 是所有 Agent 输出的唯一视觉形式。

#### Scenario: Agent 发现局部关系
- **WHEN** Agent 对当前显式上下文识别出一条可能的新关系，并返回可定位到具体 Ref 的结构化建议
- **THEN** 前端可在相关对象附近展示该关系的 Draft edge，并附极短解释，而无需自动展开完整 transcript

### Requirement: 图上投影必须使用结构化 Ref，不得猜测锚点
Attention、annotation、临时 arrow/circle 或其他 object-attached Agent presentation SHALL 由结构化 sidecar/projection 数据明确声明目标 node/edge/port Ref。前端 MUST NOT 从自然语言、当前 selection、最后一次 pending refs、当前 viewport 或“看起来最相关”的对象推断锚点。

#### Scenario: 只有文字没有 projection metadata
- **WHEN** Session 只收到一条 `agent_text`，没有结构化 object Ref / projection metadata
- **THEN** UI 可在 Companion 显示该文字或 idea-ready 提示，但 MUST NOT 自动把它贴到某个 Node/Edge/Port 上

#### Scenario: 切换 branch 后仍能正确定位
- **WHEN** 一个可恢复的 annotation 属于某个 Session branch，并显式携带目标 Ref
- **THEN** 恢复该 branch 时 UI 根据持久化/sidecar projection 数据定位；不得根据恢复时的当前 selection 重新猜测

### Requirement: Attention 是临时投影
Agent attention（高亮、指向、局部 focus、临时 arrow/circle） SHALL 只影响当前 UI presentation，MUST NOT 写入 Node/Edge/Port、attrs 或 Registry。

#### Scenario: Agent 指出关键边
- **WHEN** 一个结构化 projection 请求用户注意某条已有 Edge
- **THEN** UI 临时突出该 Edge，结束本轮、清除 projection 或离开对应 discussion 后 semantic graph 保持逐字不变

### Requirement: Annotation 与 semantic graph 分离
对象附着的解释性 annotation SHALL 默认属于 Session/discussion sidecar 或临时 projection，而 MUST NOT 自动写成 Node attrs、note Node 或正式 Edge。只有用户通过明确的图写入动作提升时才可进入 semantic graph。

#### Scenario: 对 Evidence 的一句解释
- **WHEN** Agent 返回针对 Evidence #14 的结构化短说明，projection 明确引用该 Evidence Ref
- **THEN** UI 可把说明附在该对象旁，刷新后若 Session sidecar 支持恢复则可恢复，但 Evidence attrs 不因此变化

### Requirement: Draft 与正式图必须可区分
Agent 建议新增的 Node/Edge/结构在尚未正式提交时 SHALL 以 Draft 表达，并使用至少两种非颜色线索（如虚线、透明度、Draft 标记、轮廓）与正式图区分。产品 UI MAY 使用 Keep/Dismiss 等轻量语言，但底层提交、接受或拒绝 MUST 继续走权威 server action/write matrix。

#### Scenario: proposed edge 显示为 Draft
- **WHEN** server 返回一条仍处于 proposed/unconfirmed 状态的 Edge（其 provenance MAY 为 agent）
- **THEN** Canvas 将其呈现为 Draft，用户可执行当前 server affordances 允许的 Keep/Dismiss/更多操作，前端不得本地假接受；`source=agent` 本身 MUST NOT 被当作 Draft 生命周期判断

### Requirement: Draft 可以长时间存在而不强迫即时裁决
前端 SHALL 允许 Draft 与正式图同时存在，不得在每个 Agent 建议产生时强制打开 modal 或阻塞后续工作。

#### Scenario: 用户暂不处理建议
- **WHEN** Agent 产生一个 Draft hypothesis 而用户继续查看其他节点
- **THEN** Draft 保持可辨认状态且工作流不被阻塞；用户稍后仍可回到它处理

### Requirement: 产品语言不得掩盖真实状态
UI 可用 Draft、Context、Why、Keep、Dismiss 等简化术语，但 MUST 在详情或调试入口保留真实来源、状态、actor 和拒绝原因的可访问性，不得把失败或未确认内容显示成正式事实。

#### Scenario: server 拒绝 Keep
- **WHEN** 用户点击 Keep 但 server 因当前 write policy 拒绝
- **THEN** Draft 保持未提交/未接受状态，并显示可理解的拒绝原因；UI 不得乐观地把它改成正式图
