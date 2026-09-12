## MODIFIED Requirements

### Requirement: 上下文只能显式补充
系统 SHALL 只编译用户显式附加或上层程序显式声明的 RefSet。画布当前视图、全图状态、会话历史或领域默认对象 MUST NOT 自动成为补充上下文。前端 MAY 将 `Ask selection`、将 graph-object reference 拖给 Agent Companion、对象菜单 Attach 等交互视为显式附加，但 MUST 在发送前可见地呈现实际 pending refs。

#### Scenario: 只聊天不附加
- **WHEN** 用户没有新增上下文引用而发送消息
- **THEN** Adapter 收到原始用户消息，不追加 Simulanka 上下文块

#### Scenario: scoped Companion 不等于上下文
- **WHEN** Agent Companion 恢复到某个子图 scope，但用户未显式附加 RefSet
- **THEN** 当前 root、其孩子和该 scope 的其他实体均不进入 ContextBundle，Adapter 收到逐字不变的用户消息

#### Scenario: 显式附加选择集
- **WHEN** 用户选择若干 node/edge/port 并确认附加
- **THEN** 只有该 RefSet 被编译并显示为本轮 supplemental context

#### Scenario: Ask 当前选择
- **WHEN** 用户选中若干 node/edge/port 并执行 `Ask`
- **THEN** 该 selection 成为本轮显式 pending RefSet，UI 显示将附加的对象；未选择的邻居、祖先和当前 viewport 不自动加入

#### Scenario: 将对象引用拖给 Agent
- **WHEN** 用户从 node/edge/port 的显式对象 surface 开始拖拽，并把带有 Simulanka typed-ref payload 的拖拽放到 Agent Companion
- **THEN** 只有 payload 指定的 Ref 被加入 pending context；拖拽路径经过的其他实体不加入，semantic graph 的位置、连接和 attrs 均不改变

#### Scenario: 普通文本拖拽不等于上下文
- **WHEN** 用户把普通文字或不含有效 Simulanka typed-ref payload 的外部拖拽放到 Agent Companion
- **THEN** 前端 MUST NOT 因此创建 Context Ref

### Requirement: 用户可预览实际补充内容
前端 SHALL 展示 pending refs、本轮将新发送的 bundle、已存在于原生会话而跳过发送的 bundle、最终 canonical payload 和 omissions。紧凑 Companion UI MAY 先显示对象/来源/omission 摘要，并把 canonical payload 与 delivery reason 放入按需展开的 technical details；这些底层信息 MUST 保持可访问但不必成为默认产品界面。

#### Scenario: 发送前预览
- **WHEN** 用户在发送前打开上下文预览
- **THEN** UI 显示本轮实际会附加的对象、来源和省略项，并提供按需查看完整 canonical payload 的入口

#### Scenario: 紧凑 Agent Companion
- **WHEN** 用户通过 Companion 准备发送带 3 个 refs 的问题
- **THEN** UI 至少显示“3 refs”及其对象摘要，并允许用户查看 delivery/source/omission 摘要；完整 ContextBundle/payload 可作为二级 technical details 展开
