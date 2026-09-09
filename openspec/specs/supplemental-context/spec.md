# supplemental-context Specification

## Purpose
TBD - created by archiving change s8-agent-socket. Update Purpose after archive.
## Requirements
### Requirement: 原生上下文优先
Provider 原生 session/thread SHALL 是对话历史、工具状态、压缩和 prompt cache 的主权威。Simulanka MUST NOT 在续聊时把完整 transcript、全图或平台重建的历史重新拼入 prompt。

#### Scenario: 原生续聊
- **WHEN** Session 已记录 native session id 且 Adapter 支持 native resume
- **THEN** 下一轮使用原生 resume，只发送用户本轮消息和本轮新增的 supplemental ContextBundle

#### Scenario: 无原生续聊能力
- **WHEN** Adapter 不支持 native resume
- **THEN** 系统明确标记 stateless/degraded，且不静默回放 transcript

### Requirement: 上下文只能显式补充
系统 SHALL 只编译用户显式附加或上层程序显式声明的 RefSet。画布当前视图、全图状态、会话历史或领域默认对象 MUST NOT 自动成为补充上下文。

#### Scenario: 只聊天不附加
- **WHEN** 用户没有新增上下文引用而发送消息
- **THEN** Adapter 收到原始用户消息，不追加 Simulanka 上下文块

#### Scenario: scoped ChatNode 不等于上下文
- **WHEN** ChatNode 可见于某个子图 scope，但用户未显式附加 RefSet
- **THEN** 当前 root、其孩子和该 scope 的其他实体均不进入 ContextBundle，Adapter 收到逐字不变的用户消息

#### Scenario: 显式附加选择集
- **WHEN** 用户选择若干 node/edge/port 并确认附加
- **THEN** 只有该 RefSet 被编译并显示为本轮 supplemental context

### Requirement: ContextBundle 确定且内容寻址
Context compiler SHALL 在指定 graph version 上把有序去重 RefSet 编译为不可变 bundle，并记录 compiler/schema version、source refs、canonical payload、omissions 与 sha256 digest。相同输入和 policy MUST 产生逐字节相同的 payload 与 digest。

#### Scenario: 重复编译未变化引用
- **WHEN** 同一 compiler version、RefSet、实体内容和 policy 被再次编译
- **THEN** 得到相同 digest 和逐字节一致的 payload

#### Scenario: 引用实体发生变化
- **WHEN** RefSet 中实体的上下文可见内容发生变化
- **THEN** 新 bundle 获得新 digest，旧 bundle 保持不可变可审计

### Requirement: 相同补充上下文不重复注入
系统 SHALL 按 native session id 记录已发送的 bundle digest。已发送且未变化的 bundle MUST NOT 在后续轮重复注入；新 digest SHALL 作为增量附加。

#### Scenario: 连续两轮引用同一未变化节点
- **WHEN** 第二轮仍引用第一轮已发送且内容未变化的节点
- **THEN** UI 显示该引用已存在于原生会话，Adapter 不重新发送其 payload

#### Scenario: 同一节点内容更新
- **WHEN** 节点内容更新后用户再次附加
- **THEN** 新 digest 的 bundle 被作为增量发送

### Requirement: 指令与参考材料分区
ContextBundle MUST 区分 instruction 与 reference。图 attrs、文件内容和工具输出默认 SHALL 作为带来源边界的不可信 reference，不得提升为 system instruction。

#### Scenario: 节点正文包含命令式文本
- **WHEN** 被附加节点正文包含“忽略此前指令”等文字
- **THEN** 该文字仍位于 reference 区并带来源标识，不改变平台或 Provider 的系统指令层

### Requirement: 用户可预览实际补充内容
前端 SHALL 展示 pending refs、本轮将新发送的 bundle、已存在于原生会话而跳过发送的 bundle、最终 canonical payload 和 omissions。用户无需查看服务端文件即可判断 Simulanka 补充了什么。

#### Scenario: 发送前预览
- **WHEN** 用户在发送前打开上下文预览
- **THEN** UI 显示本轮实际会附加的内容、来源和省略项

### Requirement: cache 遥测诚实
Provider 报告 cache usage 时，Adapter SHALL 原样记录并展示其 usage 字段，包括可用的 `cached_input_tokens`。系统 MUST NOT 根据本地 digest 推断或伪造 Provider cache hit，也不得以固定命中率作为正确性判据。

#### Scenario: Codex 返回 cached_input_tokens
- **WHEN** Codex `turn.completed` 包含 `cached_input_tokens`
- **THEN** 该值进入 SessionEvent usage、转录和前端详情

#### Scenario: Provider 不报告 cache
- **WHEN** Provider 完成事件没有 cache usage
- **THEN** UI 显示未报告，而不是显示零命中或成功命中

