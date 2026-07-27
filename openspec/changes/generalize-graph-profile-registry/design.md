## Context

Simulanka 的磁盘实体已经只有 Node/Edge/Port 三种，Node 的 `type` 也是普通字符串；真正的领域耦合发生在读取和展示阶段：

- `registry/builtin.py` 把结构、文件、模型、研究和运行类型放在同一个常量表；
- validator 与 doctor 直接 import 全局常量；
- trust、server rename/delete policy、cards、theme、templates 和 ContextMenu 各自维护类型集合；
- 前端复制 `allow_parents`，server 422 才是最终硬闸。

早期设计档案已经为 `attrs_model` 和可选只读 validator 留过接口，manifest 也分别维护 `schema_version` 与 `registry_version`。因此本 change 可以不改 Node/Edge/Port 物理 schema，只完成 registry v2 和消费者迁移。

该改造触及 frozen registry contract，并横跨 kernel、server、frontend；实现前必须以本设计、delta specs、GitNexus impact 和交叉审查为边界。

## Goals / Non-Goals

**Goals:**

- 新增 Profile、Template 或领域包时，不修改 kernel validator 与核心前端组件。
- 一个物理 Node 对应一个主 Profile；正交特性由 capabilities 组合。
- registry、策略、展示和模板各有单一权威，不再复制类型表。
- 服务端计算 actor/state-aware affordances，前端只负责呈现。
- 保持现有持久化 type key 和图数据可读，迁移不重写实体。
- 未知或缺少 Presentation 的 Profile 仍可用通用卡片与 Inspector 检查。

**Non-Goals:**

- 不建设第三方 Python 插件加载器、市场或远程代码执行。
- 不在 v1 为所有 attrs 建闭合强类型 schema；领域字段仍允许演化。
- 不把工作流、会话或 Agent prompt 定义成 Profile。
- 不为了 namespacing 重命名现有 type/edge key。
- 不在本 change 内重写 research provenance 算法或改变既有图语义。

## Decisions

### 1. Registry 是不可变组合对象

应用启动时把可信领域包组合为一个 `Registry`：

```text
Registry
  node_profiles
  edge_profiles
  port_types
  actions
  presentations
  templates
  aliases
  version
  descriptor_digest
```

默认包按固定顺序显式注册，例如 core、filesystem、ml/torch、research、runtime。重复 key、未知 base、继承环、未声明 capability、悬空 presentation/action executor 在启动时 fail closed。运行期间 Registry 不变，避免 validator、doctor 和 UI 看到不同语义。

首版仍在仓内用 Python dataclass 构造可信 Registry；descriptor API 输出纯数据。外部声明式包等真实用例出现后再开，不预先加载任意代码。

### 2. 一个主 Profile + 单继承展开 + capability 组合

Node 持久化字段保持：

```text
id, type, name, parent_id, attrs, created_at, created_by
```

`type` 即主 Profile key。`NodeProfileSpec` 包含：

- `key`
- 可选单一 `extends`
- `capabilities`
- parent rule
- 开放式 attrs contract 与可选只读 validator
- presentation/template references

Registry 加载时将 extends 链展开成一个扁平 resolved profile。只允许单一 base，避免菱形继承与冲突合并；横向复用由 capabilities 表达。

Capability 只有在至少影响一项时才成立：validator 约束、action eligibility、context/presentation 行为。颜色、分类和任意 tag 不得冒充 capability。

### 3. Edge 与 Port 使用同一 Profile 思路

`EdgeProfileSpec` 声明是否需要 ports、方向要求，以及端点 predicate。predicate 可以要求：

- 指定 profile key 集；
- profile 具备全部指定 capabilities；
- `ANY`。

复杂领域不变量可挂只读 validator，但不可在 validator 内写图。Port type 继续是 registry 字符串 key；后续若需要复杂端口 schema，再独立演进。

### 4. Capability 与权限/状态策略分离

Capability 只回答“结构上有没有这种能力”；它不授予权限。

```text
available affordance
  = ActionSpec target predicate
  ∩ actor policy
  ∩ entity/source/state policy
  ∩ executor capability
```

`ActionSpec` 声明 action id、目标 RefSet predicate、输入 schema、executor family 和展示标签。服务端 resolver 返回 `{id,label,enabled,reason,input_schema}`，执行端点再次以同一 resolver 校验，防止前端陈旧或绕过。

统一 action envelope 只用于 API/交互；底层执行仍分为 GraphCommand、SessionCommand 和 ProjectionCommand，不能把外部副作用伪装成 PatchIntent 原子事务。

### 5. PresentationSpec 与 TemplateSpec 分离

Profile 定义语义；PresentationSpec 定义声明式展示：

- card fields / text / badge；
- palette token；
- Inspector field groups；
- icon/category；
- generic fallback。

v1 Presentation DSL 只包含受控字段选择与格式化器 key，不加载任意前端脚本。复杂领域组件必须另开受审查扩展点。

TemplateSpec 是实例蓝图：profile key、默认 attrs、默认 ports、目录分类。Conv2d、Linear 等属于 Template，不是新 Profile。

### 6. Server 是 descriptor 与 affordance 的唯一权威

新增 registry descriptor API，包含 version/digest、resolved profiles、edge rules、presentations、templates 和 action metadata。Graph payload 对每个实体增加 resolved capabilities 与 affordances；保留 `type` 供身份和兼容。

前端不得复制 allow_parents、类型删除集合或 action eligibility。创建目录按 server descriptor 与当前 container affordance 过滤；真正执行仍由 server 重验。

### 7. 领域专属计算通过包扩展，不回流核心

research trust/provenance、filesystem binding、Torch importer 等仍是领域服务，但其适用对象通过 Registry capability/profile predicate 解析，不再维护散落的 type 常量。

例如 trust badge 可由 `trust_subject` capability 决定；provenance 的具体边遍历仍属于 research package。这样不会把所有领域算法压成一个万能 DSL。

### 8. Registry v2 不改实体

`REGISTRY_VERSION` 从 1 升至 2，并注册 1→2 migration。由于现有 type/edge/port key 不变，迁移只更新 manifest 版本并记录事件；不重写实体文件。Registry descriptor 自带 digest，便于前后端发现运行期描述不一致。

namespaced key 与 alias 从 v2 可用，但现有短 key 继续是 canonical 或兼容 alias；真实冲突出现前不做批量改名。

## Risks / Trade-offs

- [Capability 数量失控] → 只允许影响 validation/action/context/presentation 的能力；新增 capability 必须有消费者与测试。
- [声明式 Presentation 变成另一门前端语言] → v1 限定字段、badge、text、palette 和已注册 formatter，不支持任意表达式。
- [服务端 affordance 与执行端点漂移] → 两者调用同一 resolver；端点不得复制判断。
- [GitNexus 低估表驱动改造] → 按文件和行为矩阵补人工搜索；提交前 detect_changes + 全量质量门。
- [未知 Profile 导致图不可读] → doctor 报错，但 view/Inspector 用 raw type/name/attrs 通用降级，不白屏、不丢实体。
- [迁移后旧代码无法读取 v2] → registry/schema 版本不匹配沿现有机制阻塞写；回滚需同时回滚 manifest checkpoint。
- [内置领域包仍需改仓库] → v1 先证明 Registry 闭包，不提前承担第三方代码加载的安全与兼容成本。

## Migration Plan

1. 新增 Registry/ResolvedProfile/ActionSpec 数据模型和组合校验，先用兼容 facade 导出旧常量。
2. validator、doctor、trust 与 server policy 注入同一 Registry；加入 registry v1→v2 migration。
3. 提供 descriptor/affordance API，并用服务端测试锁定旧类型语义。
4. 前端先接 descriptor 和通用 fallback，再逐项迁移 templates/cards/theme/menu/Inspector。
5. 删除前端 allow_parents 与 type-action 镜像；删除后端旧常量直接依赖。
6. 用非科研测试/演示包证明新增 Profile/Template 无需改 kernel 或核心前端。
7. 更新 authoritative docs 并完成用户目验。

每一步保持旧 key 可读；在 facade 删除前可回滚到旧消费者。

## Open Questions

- 外部声明式 Profile 包的发现、签名与信任模型留给真实分发用例，本 change 只留下纯数据 descriptor 边界。
- namespaced canonical key 的批量迁移留到发生真实命名冲突时决定。
