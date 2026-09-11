# graph-profile-registry Specification

## Purpose
定义版本化、确定组合且运行期不可变的 Node、Edge 与 Port Profile Registry，以及 capability、约束、alias、迁移和未知 Profile 处理规则。

## Requirements

### Requirement: type 是单一主 Profile key
Node、Edge 与 Port 的现有持久化字段 SHALL 保持兼容；Node/Edge 的 `type` SHALL 被 Registry 解释为唯一主 Profile key。Capability MUST 由 resolved Profile 计算，不得复制进实体 attrs 作为权威。

#### Scenario: 读取现有节点
- **WHEN** Registry v2 读取 type=`hypothesis` 的现有 Node
- **THEN** 实体无需重写即可解析到 hypothesis Profile 及其 capabilities

### Requirement: Registry 确定组合且运行期不可变
应用 SHALL 从显式可信领域包确定性组合唯一 Registry。重复 key、未知 base、继承环、未声明 capability 或悬空引用 MUST 在启动时失败；Registry 在进程生命周期内 MUST 不可变。

#### Scenario: 两个包注册同一 key
- **WHEN** 两个领域包都注册 `module`
- **THEN** Registry 构建失败并指出冲突来源，不采用后注册覆盖

#### Scenario: Profile 继承成环
- **WHEN** Profile A extends B 且 B extends A
- **THEN** Registry 构建失败且不启动写服务

### Requirement: 单继承展开和 capability 组合
Node Profile MAY 声明至多一个 base Profile，并 SHALL 在 Registry 构建时展开为扁平 resolved contract。横向能力 SHALL 通过显式 capability 集合组合；运行期 MUST 不执行多继承解析。

#### Scenario: model 继承 component
- **WHEN** `model` extends `component` 并新增 `projected`
- **THEN** resolved model 同时具有 component 的字段/约束和 projected capability

### Requirement: Capability 必须有平台语义
Capability 注册 SHALL 指明至少一个 validation、action、context 或 presentation 消费者。无消费者的装饰性分类 MUST 作为 tag/category，而不是 capability。

#### Scenario: 注册纯颜色 capability
- **WHEN** 领域包声明只决定蓝色外观且无其他消费者的 capability
- **THEN** Registry 校验拒绝或要求改为 Presentation token

### Requirement: Profile 约束驱动 kernel 校验
Node parent、Edge endpoint/port direction、Port type 与开放式 attrs contract SHALL 从同一 Registry 解析。kernel apply 与 doctor MUST 使用同一 resolved rules；可选 validator MUST 只读且不得写图。

#### Scenario: 建立不兼容父子关系
- **WHEN** create_node 的 parent 不满足 Profile parent rule
- **THEN** kernel 在提交前拒绝，doctor 对盘上同类异常报告相同语义

#### Scenario: attrs 包含扩展字段
- **WHEN** Profile 未声明 closed attrs 且节点带领域扩展字段
- **THEN** kernel 保留该字段，不因未列出而拒绝

### Requirement: Registry 版本和 alias
Registry SHALL 提供 version、descriptor digest、canonical keys 与 aliases。alias 解析 MUST 确定且无环；v1→v2 migration MUST 保持现有实体 type key 和内容不变。

#### Scenario: 项目从 registry v1 升级
- **WHEN** 用户执行 graph migrate
- **THEN** manifest registry_version 更新并记录 migration event，节点/边/端口文件逐字不因本迁移改写

### Requirement: 未知 Profile 诚实处理
写路径 MUST 拒绝未知 Profile；doctor MUST 报告未知 Profile。只读 view MUST 仍返回 raw id/type/name/attrs，使前端可用通用降级展示，不得丢弃或崩溃。

#### Scenario: 图中存在已卸载领域 Profile
- **WHEN** 当前 Registry 不再包含某实体的 type
- **THEN** doctor 报错，view 仍返回实体并标记 unknown_profile

### Requirement: 新领域包不修改内核
新增可信领域 Profile/Edge/Profile templates SHALL 只需注册领域包和测试，不得要求修改 kernel validator、doctor 分支或核心 Node/Edge/Port schema。

#### Scenario: 增加非科研 service Profile
- **WHEN** 测试 Registry 加载一个 software service Profile
- **THEN** 它可通过通用 create/validate/view 路径工作，kernel 核心文件无需增加 service 分支
