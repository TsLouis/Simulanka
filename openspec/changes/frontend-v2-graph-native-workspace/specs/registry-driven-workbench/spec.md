## MODIFIED Requirements

### Requirement: 声明式通用卡片和 Inspector
前端 SHALL 用 PresentationSpec 的受控字段、badge、text、palette 与 formatter key 渲染通用卡片和 Inspector。缺少 PresentationSpec 时 MUST 显示 type/name/raw attrs 的通用降级，不得白屏。默认工作区 MUST NOT 要求 Inspector 常驻；完整 Inspector SHALL 只在用户明确打开时出现。

#### Scenario: 新 Profile 无定制展示
- **WHEN** Registry 包含一个没有 PresentationSpec 的 Profile
- **THEN** 画布显示通用节点卡，用户可按需打开 Inspector 查看全部 attrs

### Requirement: 动作菜单由 affordances 驱动
节点、边、端口及多选菜单 SHALL 渲染 server 返回的 affordances。核心菜单 MUST NOT 为 task、model、module 或其他领域 type 设置专属动作分支。前端 MAY 将最常用的当前可用 affordance 投影为对象附近的轻量 contextual controls，但 MUST NOT 绕过 server resolver。

#### Scenario: 选择普通节点
- **WHEN** 用户单击一个有可用 affordances 的节点
- **THEN** UI 可显示轻量 `Ask / Open / more` 控件，more 中的动作仍由 server affordances 决定

## ADDED Requirements

### Requirement: Canvas-first 默认工作区
默认工作区 SHALL 让 Graph Canvas 成为主要可见表面；TopBar 与 Activity Bar MUST 保持轻量，Inspector、Session transcript、Registry 等辅助面 SHALL 默认关闭或折叠，并可由用户显式打开。

#### Scenario: 打开项目
- **WHEN** 用户进入一个已有项目且没有恢复中的显式面板状态
- **THEN** 页面主要显示 Graph Canvas，不自动展开 Inspector 或长对话面板

### Requirement: Node 信息密度随 zoom 渐进展开
前端 SHALL 根据 Canvas zoom 采用稳定的信息密度层级，而 MUST NOT 在所有缩放级别显示同样的卡片内容。层级切换 SHOULD 使用稳定阈值或 hysteresis，避免轻微缩放造成反复闪烁。

#### Scenario: 远距离浏览
- **WHEN** zoom 处于 overview 区间
- **THEN** Node 仅显示足以识别的图标/类型与名称，Port 名称和非必要字段隐藏

#### Scenario: 工作距离浏览
- **WHEN** zoom 进入 working 区间
- **THEN** Node 显示真实可连接 input/output Port handle，但可继续省略长属性文本

#### Scenario: 近距离查看
- **WHEN** zoom 进入 detail 区间
- **THEN** Node 显示 Port 名称/方向与 PresentationSpec 选择的关键字段

### Requirement: Port 是节点正常视觉语义的一部分
working/detail zoom 下，前端 SHALL 使用真实 Graph Port 数据表达节点输入与输出；input Port SHOULD 位于节点左侧，output Port SHOULD 位于右侧，且连接 eligibility 仍由 Registry/Edge Profile 与 server 最终校验决定。远距离隐藏 Port 只属于视觉降噪，不得改变图语义。

#### Scenario: Experiment 有多个输入输出
- **WHEN** 一个节点存在 `data/config` 输入和 `result/log` 输出且用户放大到 detail 区间
- **THEN** 这些 Port 以对应方向和名称展示，用户可从兼容 Port 建立连接

### Requirement: 选择对象先显示轻量上下文
单击 Node/Edge/Port SHALL 优先产生局部高亮与轻量 contextual controls，而不是自动展开完整 Inspector 或切换到独立模式。用户 MUST 可以显式打开完整详情。

#### Scenario: 选择 Edge
- **WHEN** 用户单击一条 Edge
- **THEN** Edge 与端点关系被突出，附近出现轻量可用动作；完整详情只在用户要求时出现
