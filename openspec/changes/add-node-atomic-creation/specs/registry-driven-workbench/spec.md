## MODIFIED Requirements

### Requirement: Canvas Add Node 是一个可观察的原子创建动作

用户从 Canvas Add Node 搜索/菜单选择一个模板时，系统 SHALL 将该 Node 与模板声明的 Ports 作为一个 semantic graph transaction 提交。前端 MUST NOT 向用户暴露“Node 已存在但模板 Ports 尚未创建”的中间图状态。

#### Scenario: Node 与模板 Ports 一起成功
- **WHEN** 用户在某个 canvas point 选择一个包含多个 Ports 的合法模板
- **THEN** kernel 在一个 PatchIntent 中创建 Node 与全部 Ports，graph_version 只前进一次，返回的 `node_id` 与 `port_ids` 均属于该次提交

#### Scenario: 任一 Port 校验失败
- **WHEN** 同一 Add Node transaction 中任一 template Port 被 Registry/kernel 校验拒绝
- **THEN** 整个 PatchIntent 失败，Node 和所有 Ports 均不得持久化，graph_version 不得因该请求前进

### Requirement: PatchIntent-local Node ref 可供 CreatePort 使用

`CreatePortOp.node` SHALL 支持引用同一个 PatchIntent 中更早 `CreateNodeOp(ref=...)` 声明的 `@ref`。该 ref 仅用于 intent 内解析，MUST NOT 作为 graph entity id 或事件中的持久标识。

#### Scenario: Port 指向 pending Node
- **WHEN** 一个 PatchIntent 先声明 `CreateNodeOp(ref="new")`，后声明 `CreatePortOp(node="@new", ...)`
- **THEN** Port 对 pending Node 进行验证并使用其最终生成的真实 Node id 持久化

#### Scenario: 未知 local ref
- **WHEN** `CreatePortOp.node` 引用不存在的 `@ref`
- **THEN** 整个 PatchIntent 返回 validation error，且不得产生部分 graph write

### Requirement: 新 Node 第一帧使用 summon point

Canvas Add Node SHALL 在 creation-triggered graph reload 被允许渲染之前，将服务端返回的真实 Node id 与用户选择模板时的 canvas summon point 关联到当前 view 的 UI position bucket。

#### Scenario: SSE commit 先于 create response 被观察
- **WHEN** creation commit 已经到达 SSE，但对应 Add Node request 尚未完成 position handoff
- **THEN** 前端延迟/合并该 graph reload；create response 返回后先记录并持久化真实 Node id 的 summon point，再执行 reload，因此用户不看到 dagre fallback 的中间位置

#### Scenario: 多个 Add Node 请求重叠
- **WHEN** 用户快速连续创建多个 Node 且请求生命周期重叠
- **THEN** 前端分别保留每个 Node 的 summon point，并只在所有相关 position handoff 安全后释放合并 reload；不得用单一易竞争 boolean 丢失某次创建

#### Scenario: position sidecar 写入失败
- **WHEN** semantic Node+Ports transaction 成功但 UI position persistence 失败
- **THEN** 前端保留当前 session 的正确内存位置并显示错误；不得伪装 graph transaction 失败，也不得删除已成功创建的 semantic graph entity

### Requirement: Add Node 保留现有命名与权限语义

本修复 MUST 保留 sibling collision suffixing、Registry/action validation、TemplateSpec attrs/ports 来源及 server/kernel 最终 authority。

#### Scenario: 同名 sibling
- **WHEN** 当前 parent 下已经存在模板默认名
- **THEN** server 按现有规则生成 `_2`, `_3` 等唯一名称，并在同一个 atomic creation transaction 中创建对应 Ports
