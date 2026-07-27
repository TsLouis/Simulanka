## Why

Simulanka 的物理图已经统一为 Node/Edge/Port，但类型、卡片、颜色、创建目录和动作仍分别硬编码在 kernel、server 与前端；新增一个非科研场景必须修改核心代码。平台需要一个版本化、可组合的 Profile/Capability 注册表，使科研、模型、文件和未来领域成为可安装语义包，而不是内核身份。

## What Changes

- 保持 Node/Edge/Port 持久化 schema 不变，将现有 `type` 字段正式定义为 Profile key。
- 扩展 `NodeTypeSpec`/`EdgeTypeSpec` 为版本化 Profile contract：单一主 Profile、可展开的基础 Profile、正交 capabilities、字段约定、父子/端点/端口约束和可选只读 validator。
- **BREAKING（内部 API）**：kernel、doctor、server 和 importer 不再直接 import 全局 `NODE_TYPES/EDGE_TYPES/PORT_TYPES` 常量，统一从一个不可变 Registry 实例解析。
- 将 capability 与权限分开：结构能力说明“可以做什么”，策略按 actor、来源和状态决定“当前允许什么”；服务端返回最终 affordances。
- 新增 ActionSpec 与服务端 action resolver；前端菜单按 affordances 渲染，不再以 `node.type` 或 Provider 名称分支。
- 将 PresentationSpec 和 TemplateSpec 从类型语义中分离：通用渲染器消费声明式卡片/主题；Conv2d 等模板只是实例蓝图。
- 新增 registry descriptor API，前端创建目录、Inspector、卡片、主题与连接候选均以 server 注册表为单一来源，并保留未知 Profile 的通用降级展示。
- 现有 `directory/model/module/file/question/...` key 在本阶段保持不变；Registry 支持 namespaced key 和 alias，但不为命名美观重写历史图。
- v1 只组合仓内可信、确定的领域包；不加载任意第三方 Python 插件。以一个非科研示例包证明扩展闭包。
- registry version 升级并提供无实体重写的迁移步骤；schema version 保持不变。

## Capabilities

### New Capabilities

- `graph-profile-registry`: Node/Edge/Port Profile、继承展开、capability、约束、版本、alias 与确定组合。
- `capability-action-resolution`: 基于 capability、actor policy、实体状态和执行器支持计算服务端权威 affordances。
- `registry-driven-workbench`: 前端通过 registry descriptors 驱动创建目录、卡片、主题、Inspector 与动作菜单，并对未知 Profile 诚实降级。

### Modified Capabilities

（无；主规格目录尚无已归档 capability。）

## Impact

- 冻结边界：`schema/entities.py` 的物理字段不变；`registry/`、`kernel/validator.py`、`kernel/doctor.py` 与 registry migration 会改变。
- 服务端：graph payload/registry descriptor/affordance resolver；现有类型专属 rename/delete/trust 规则迁入 profile policy 或领域服务。
- 前端：`templates.ts`、`cards.ts`、`theme.ts`、`ContextMenu`、`NodeInspector` 和 LiteGraph adapter 的类型表退役为声明式 descriptor。
- 导入器与领域包：Torch、filesystem、research、runtime 以可信内置包注册；实例模板与类型契约分离。
- 文档：`overview.md`、`kernel.md`、`frontend.md` 的“科研内核”表述改为“通用平台 + 领域包”。
