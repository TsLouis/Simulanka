## ADDED Requirements

### Requirement: Capability 不等于权限
系统 MUST 将 Profile capability 与 actor/state/source policy 分离。实体具备 capability 只能使 ActionSpec 成为候选，不能绕过写权、投影只读、锁或其他策略。

#### Scenario: projected 节点具备 annotatable
- **WHEN** 节点结构上可注释但当前被用户锁定
- **THEN** resolver 返回该动作 disabled 及锁定理由，执行端点同样拒绝

### Requirement: 服务端权威 affordance resolver
服务端 SHALL 依据 ActionSpec target predicate、actor policy、实体状态和 executor capability 返回 affordances。每个 affordance SHALL 含 action id、label、enabled、reason 和输入 schema；执行端点 MUST 用同一 resolver 重新校验。

#### Scenario: 陈旧前端提交已禁用动作
- **WHEN** 前端读取菜单后实体状态变化并提交旧动作
- **THEN** server 重新解析并拒绝，返回当前禁用理由

### Requirement: ActionSpec 面向 capability 和 RefSet
ActionSpec SHALL 以 RefSet 数量/实体种类/Profile capability predicate 描述适用目标，而不是要求前端判断具体 type 字符串。多选动作 MUST 能表达“所有目标具备”或“至少一个目标具备”的规则。

#### Scenario: 任意 contextualizable 选择集
- **WHEN** 多个不同 Profile 都具备 contextualizable capability
- **THEN** 同一“附加到上下文”动作可作用于整个 RefSet

### Requirement: 统一外壳不合并执行边界
Action API MAY 使用统一 envelope，但 ActionSpec MUST 指明 GraphCommand、SessionCommand 或 ProjectionCommand executor family。外部副作用 MUST NOT 被描述为 PatchIntent 原子事务。

#### Scenario: 文件导入动作
- **WHEN** 用户执行同时读取外部文件并更新图的 ProjectionCommand
- **THEN** 系统按 projection receipt/恢复语义执行，不把文件读取伪装为单个 graph op

### Requirement: 客户端不得复制动作资格
核心前端 MUST 依据 server affordances 渲染动作；不得用 `node.type === ...`、Provider 名称或本地 allowlist 决定动作是否存在。客户端 MAY 为响应速度缓存 descriptor，但 server 始终是最终权威。

#### Scenario: 新 Profile 复用 rename capability
- **WHEN** 新 Profile 满足 rename ActionSpec 且策略允许
- **THEN** 前端自动显示重命名，无需增加该 Profile 的条件分支

### Requirement: 拒绝原因可见
disabled affordance 或执行时拒绝 SHALL 提供人可读 reason 和稳定 reason code，前端 SHALL 能直接展示。

#### Scenario: 来源投影不可删除
- **WHEN** 用户查看 projected immutable 节点的删除动作
- **THEN** 菜单显示禁用及原因，而不是隐藏后让用户猜测
