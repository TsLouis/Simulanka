## ADDED Requirements

### Requirement: Agent 表达优先使用图原生 surface
前端 SHALL 支持 Agent 在 Canvas 上通过 attention、annotation 和 Draft 表达与当前图对象相关的想法。纯文字消息仍可使用，但 MUST NOT 是所有 Agent 输出的唯一视觉形式。

#### Scenario: Agent 发现局部关系
- **WHEN** Agent 对当前 selection 识别出一条可能的新关系
- **THEN** 前端可在相关对象附近展示该关系的 Draft edge，并附极短解释，而无需自动展开完整 transcript

### Requirement: Attention 是临时投影
Agent attention（高亮、指向、局部 focus、临时 arrow/circle） SHALL 只影响当前 UI presentation，MUST NOT 写入 Node/Edge/Port、attrs 或 Registry。

#### Scenario: Agent 指出关键边
- **WHEN** Agent 请求用户注意某条已有 Edge
- **THEN** UI 临时突出该 Edge，结束本轮或清除 attention 后 semantic graph 保持逐字不变

### Requirement: Annotation 与 semantic graph 分离
对象附着的解释性 annotation SHALL 默认属于 Session/conversation sidecar 或临时 projection，而 MUST NOT 自动写成 Node attrs、note Node 或正式 Edge。只有用户通过明确的图写入动作提升时才可进入 semantic graph。

#### Scenario: 对 Evidence 的一句解释
- **WHEN** Agent 返回针对 Evidence #14 的短说明
- **THEN** UI 可把说明附在该对象旁，刷新后若 Session sidecar 支持恢复则可恢复，但 Evidence attrs 不因此变化

### Requirement: Draft 与正式图必须可区分
Agent 建议新增的 Node/Edge/结构在尚未正式提交时 SHALL 以 Draft 表达，并使用至少两种非颜色线索（如虚线、透明度、Draft 标记、轮廓）与正式图区分。产品 UI MAY 使用 Keep/Dismiss 等轻量语言，但底层提交、接受或拒绝 MUST 继续走权威 server action/write matrix。

#### Scenario: proposed edge 显示为 Draft
- **WHEN** server 返回一条 source=agent 且仍处于 proposed/unconfirmed 状态的 Edge
- **THEN** Canvas 将其呈现为 Draft，用户可执行当前 server affordances 允许的 Keep/Dismiss/更多操作，前端不得本地假接受

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
