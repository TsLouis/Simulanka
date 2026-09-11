# registry-driven-workbench Specification

## Purpose
定义由服务端 Registry descriptor 和 affordance 驱动的前端创建、展示、Inspector、动作菜单与连接候选行为，以及未知 Profile 的通用降级。

## Requirements

### Requirement: Registry descriptor API
server SHALL 提供带 version 和 digest 的 Registry descriptor，包含 resolved Profiles、Edge rules、capabilities、PresentationSpec、TemplateSpec 与 ActionSpec 展示元数据。前端 MUST 以它作为创建、展示和动作发现的单一语义来源。

#### Scenario: 前后端 descriptor 不一致
- **WHEN** 前端缓存 digest 与 server 当前 digest 不同
- **THEN** 前端重新加载 descriptor 后再允许创建/编辑动作

### Requirement: Profile 与 Template 分离
创建目录 SHALL 区分 Profile 和实例 Template。Template MUST 引用一个 Profile 并只提供默认 name/attrs/ports/category；新增 Conv2d 等实例蓝图不得创建新的 Node Profile。

#### Scenario: 新增 Torch 模块模板
- **WHEN** 注册一个新的 ConvNeXtBlock Template
- **THEN** 创建节点仍使用 module Profile，kernel registry 不增加 ConvNeXtBlock type

### Requirement: 声明式通用卡片和 Inspector
前端 SHALL 用 PresentationSpec 的受控字段、badge、text、palette 与 formatter key 渲染通用卡片和 Inspector。缺少 PresentationSpec 时 MUST 显示 type/name/raw attrs 的通用降级，不得白屏。

#### Scenario: 新 Profile 无定制展示
- **WHEN** Registry 包含一个没有 PresentationSpec 的 Profile
- **THEN** 画布显示通用节点卡，Inspector 可查看全部 attrs

### Requirement: 创建目录由 Registry 和 affordance 驱动
添加节点菜单 SHALL 从 server descriptor 的 Profiles/Templates 与当前容器 create affordance 生成。前端 MUST NOT 镜像 allow_parents；server 执行时 SHALL 重验。

#### Scenario: 新容器 capability
- **WHEN** 新 Profile 声明 container 且允许某 Template
- **THEN** 该 Template 在该容器中自动可选，无需修改 templates.ts 父类型表

### Requirement: 动作菜单由 affordances 驱动
节点、边、端口及多选菜单 SHALL 渲染 server 返回的 affordances。核心菜单 MUST NOT 为 task、model、module 或其他领域 type 设置专属动作分支。

#### Scenario: task 节点菜单
- **WHEN** 用户右键 task 节点
- **THEN** 菜单仅显示其当前 affordances，不出现硬编码派工入口

### Requirement: 连接候选由 Edge Profile 规则驱动
前端 MAY 根据 descriptor 预过滤可连接端点和 edge types，但 server SHALL 以同一 Registry 规则最终校验。未知或不兼容连接 MUST 有可见拒绝原因。

#### Scenario: capability 驱动语义边
- **WHEN** 新 Edge Profile 要求 source 具备 evidence_like、target 具备 assertion_like
- **THEN** 前端可发现兼容候选，server 对不满足者拒绝

### Requirement: 非科研 Profile 可目验
验收环境 SHALL 加载至少一个非科研示例 Profile/Template，并通过同一创建、卡片、Inspector、连接、选择和动作菜单路径展示；核心前端不得包含该 Profile 名称分支。

#### Scenario: software service 示例
- **WHEN** 用户从目录创建 service 节点并选择它
- **THEN** 节点按 descriptor 展示、Inspector 可读、兼容动作出现，且与研究节点复用同一组件
