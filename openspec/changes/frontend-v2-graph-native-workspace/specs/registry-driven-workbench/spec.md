## MODIFIED Requirements

### Requirement: 声明式通用卡片和 Inspector
前端 SHALL 用 PresentationSpec 的受控字段、badge、text、palette 与 formatter key 渲染通用卡片和 Inspector。缺少 PresentationSpec 时 MUST 显示 type/name/raw attrs 的通用降级，不得白屏。默认工作区 MUST NOT 要求 Inspector 常驻；完整 Inspector SHALL 只在用户明确打开时出现。

#### Scenario: 新 Profile 无定制展示
- **WHEN** Registry 包含一个没有 PresentationSpec 的 Profile
- **THEN** 画布显示通用节点卡，用户可按需打开 Inspector 查看全部 attrs

### Requirement: 动作菜单由 affordances 驱动
节点、边、端口及多选菜单 SHALL 渲染 server 返回的 affordances。核心菜单 MUST NOT 为 task、model、module 或其他领域 type 设置专属动作分支。前端 MAY 将最常用的当前可用 affordance 投影为对象附近的轻量 contextual controls，但 MUST NOT 绕过 server resolver。

#### Scenario: task 节点菜单
- **WHEN** 用户右键 task 节点
- **THEN** 菜单仅显示其当前 affordances，不出现硬编码派工入口

#### Scenario: 选择普通节点
- **WHEN** 用户单击一个有可用 affordances 的节点
- **THEN** UI 可显示轻量 `Ask / Trace / Inspect` 对象动作；其他写入/领域动作仍来自 server affordances 或 affordance-driven overflow，不得由节点类型硬编码

## ADDED Requirements

### Requirement: Canvas-first 默认工作区
默认工作区 SHALL 让 Graph Canvas 成为主要可见表面；TopBar 与 Activity Bar MUST 保持轻量，Inspector、Session transcript、Registry 等辅助面 SHALL 默认关闭或折叠，并可由用户显式打开。

#### Scenario: 打开项目
- **WHEN** 用户进入一个已有项目且没有恢复中的显式面板状态
- **THEN** 页面主要显示 Graph Canvas，不自动展开 Inspector 或长对话面板

### Requirement: Node/Port 基础交互采用成熟 node-editor 范式
前端 SHOULD 以 ComfyUI/LiteGraph 的成熟交互作为 Node/Port/connection 基线，而 MUST NOT 为像素视觉风格重新定义基础拓扑编辑语法。input Port SHOULD 独立排列在节点左侧，output Port SHOULD 独立排列在右侧；Node 尺寸 SHALL 足以容纳实际 Port 数量；拖线、目标命中与可连接反馈 SHOULD 优先复用原生 LiteGraph 行为。

#### Scenario: 节点拥有多个 Port
- **WHEN** 一个 Node 有 4 个 input Port 和 3 个 output Port
- **THEN** UI 显示 7 个独立的 Port handle/row/anchor，不将同侧多个 Port 合并、堆叠到同一位置或用单一聚合 handle 替代

### Requirement: Node 信息密度随 zoom 渐进展开
前端 SHALL 根据 Canvas zoom 采用稳定的信息密度层级，而 MUST NOT 在所有缩放级别显示同样的卡片内容。Port handle MUST 独立于这些层级始终保留；zoom 只控制 Port label、卡片字段和其他文字细节。

#### Scenario: 远距离浏览
- **WHEN** zoom 处于 overview 区间
- **THEN** Node 显示足以识别的名称/类型以及每一个真实 input/output Port handle；Port 名称和非必要字段隐藏

#### Scenario: 工作距离浏览
- **WHEN** zoom 进入 working 区间
- **THEN** 全部真实 Port handle 继续独立可见，UI MAY 根据可读性显示短 label 或关键状态，但不得合并 Port

#### Scenario: 近距离查看
- **WHEN** zoom 进入 detail 区间
- **THEN** Node 显示 Port 名称/方向与 PresentationSpec 选择的关键字段

### Requirement: Port 是节点正常视觉语义的一部分
所有 zoom 下，前端 SHALL 使用真实 Graph Port 数据表达节点输入与输出。每个 Port MUST 保持独立 handle、row、anchor 与 hit target；input Port SHOULD 位于节点左侧，output Port SHOULD 位于右侧。zoom MAY 隐藏 Port 名称、type、shape 等文字，但 MUST NOT 隐藏、合并或堆叠真实 Port。连接 eligibility 仍由 Registry/Edge Profile 与 server 最终校验决定。

#### Scenario: Experiment 有多个输入输出
- **WHEN** 一个节点存在 `data/config` 输入和 `result/log` 输出
- **THEN** 在任意 zoom 下都能看见 4 个独立 Port handle；detail zoom 再显示对应 Port 名称和语义，用户可从兼容 Port 建立连接

### Requirement: 对象交互使用稳定的 Ask / Trace / Inspect 语法
Node、Edge、Port 的轻量 object interaction SHALL 使用一致且不混淆的产品语义：`Ask` 表示把 exact Ref 显式加入 Agent context；`Trace` 表示调用系统已有的确定性 provenance/lineage 能力，不调用 Agent；`Inspect` 表示查看对象本身的结构、接口、attrs 或状态。`Trace` MUST 只在该对象存在可验证的系统 trace 能力时出现，不得为了视觉一致性用 Agent 推测替代。

#### Scenario: Node 同时支持 Agent 与 provenance
- **WHEN** 用户选择一个既可 `context.attach` 又可读取 provenance 的 Node
- **THEN** UI 提供 `Ask / Trace / Inspect`；Ask 进入 pending Agent RefSet，Trace 展示系统查询得到的 upstream graph evidence，Inspect 展开该 Node 的接口和详情

#### Scenario: Edge 没有独立 provenance resolver
- **WHEN** 用户选择一条可附加给 Agent、但没有确定性 edge provenance 查询能力的 Edge
- **THEN** UI 提供 `Ask / Inspect`，不得显示一个实际由 Agent 解释或猜测实现的假 `Trace`

#### Scenario: Inspect Port
- **WHEN** 用户在 Node Interface 中 Inspect 一个 Port
- **THEN** UI 显示该 Port 的 direction、type、observed shape/confidence、id 与可访问 attrs；Inspect 本身不改变连接或 semantic graph

### Requirement: 选择对象先显示轻量上下文
单击 Node/Edge/Port SHALL 优先产生局部高亮与轻量 contextual controls，而不是自动展开完整 Inspector 或切换到独立模式。用户 MUST 可以显式 Inspect 完整详情。对象专属写动作（例如 Edge Keep/Dismiss/verdict）SHOULD 与通用 `Ask / Trace / Inspect` 层级分开，并继续由 server affordances 控制。

#### Scenario: 选择 Edge
- **WHEN** 用户单击一条 Edge
- **THEN** Edge 与端点关系被突出，先提供 `Ask / Inspect` 等对象级动作；Keep/Dismiss/Needs attention 等 Edge 专属动作保持在 affordance-driven review 层，完整详情只在用户要求时出现
