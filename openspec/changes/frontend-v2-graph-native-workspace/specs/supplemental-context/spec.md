## MODIFIED Requirements

### Requirement: 上下文只能显式补充
系统 SHALL 只编译用户显式附加或上层程序显式声明的 RefSet。画布当前视图、全图状态、会话历史或领域默认对象 MUST NOT 自动成为补充上下文。前端 MAY 将 `Ask selection`、将 selection 拖给 Agent Companion、对象菜单 Attach 等交互视为显式附加，但 MUST 在发送前可见地呈现实际 pending refs。

#### Scenario: Ask 当前选择
- **WHEN** 用户选中若干 node/edge/port 并执行 `Ask`
- **THEN** 该 selection 成为本轮显式 pending RefSet，UI 显示将附加的对象；未选择的邻居、祖先和当前 viewport 不自动加入

#### Scenario: 将选择拖给 Agent
- **WHEN** 用户把一个已选 RefSet 拖到 Agent Companion 并完成 attach 动作
- **THEN** 只有该 RefSet 被加入 pending context，拖拽路径经过的其他实体不加入

### Requirement: 用户可预览实际补充内容
前端 SHALL 展示 pending refs、本轮将新发送的 bundle、已存在于原生会话而跳过发送的 bundle、最终 canonical payload 和 omissions。紧凑 Companion UI MAY 只显示 refs 摘要，但 MUST 提供按需展开完整 preview 的入口。

#### Scenario: 紧凑 Agent Companion
- **WHEN** 用户通过 Companion 准备发送带 3 个 refs 的问题
- **THEN** UI 至少显示“3 refs”及其对象摘要，并允许用户打开完整 ContextBundle preview 后再发送
