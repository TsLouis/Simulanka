## 0. 用户可目验门

- [ ] U1 Registry 可见：前端可查看当前 registry version/digest、Profiles、capabilities 和 Templates，现有图展示不回退
- [ ] U2 非科研扩展：加载 software service 示例后，可创建、连接、选择、检查和执行通用动作，核心 kernel/frontend 无 service 名称分支
- [ ] U3 能力驱动动作：task/model/module 等菜单不再硬编码；启用、禁用和拒绝原因来自 server affordances
- [ ] U4 声明式展示：现有研究/模型卡片保持信息密度；无 PresentationSpec 的未知 Profile 使用通用卡片和 raw attrs Inspector
- [ ] U5 兼容迁移：registry v1→v2 不重写实体，现有项目 migrate 后 doctor/导入/前端行为保持一致

## 1. Registry v2 核心

- [x] 1.1 定义 CapabilitySpec、NodeProfileSpec、EdgeProfileSpec、ResolvedProfile、PresentationSpec、TemplateSpec 与 Registry
- [x] 1.2 实现确定组合、单继承展开、alias 解析、descriptor digest 和运行期不可变
- [x] 1.3 对重复 key、未知 base、继承/alias 环、无消费者 capability、悬空引用 fail closed
- [x] 1.4 用兼容 facade 暂时导出旧 NODE_TYPES/EDGE_TYPES/PORT_TYPES，锁定现有类型和边约束
- [x] 1.5 增加非科研 software service 测试/演示包，证明无 kernel 分支扩展

## 2. Kernel、doctor 与迁移

- [x] 2.1 validator 注入 Registry，Node parent、Edge endpoint/port 与 Port type 走 resolved rules
- [x] 2.2 doctor 使用同一 Registry；未知 Profile 报错但只读 view 不丢实体
- [x] 2.3 支持开放式 attrs contract 与可选只读 validator，验证 validator 无写副作用
- [x] 2.4 REGISTRY_VERSION 升至 2，注册 v1→v2 仅 manifest/event migration，证明实体文件逐字不改
- [x] 2.5 更新 kernel/CLI/importer 调用点，移除对旧全局常量的直接依赖

## 3. 内置领域包

- [x] 3.1 将 core containment/data_flow 与通用 capabilities 注册为 core package
- [x] 3.2 将 filesystem、ml/torch、research、runtime 类型和 edge rules 分入可信内置包
- [x] 3.3 将 Conv/Linear/运算等实例目录迁为 TemplateSpec，不扩大 Profile 数量
- [x] 3.4 trust badge 适用面改读 capability；research provenance 算法保持领域扩展且回归不变
- [x] 3.5 server rename/delete/source policy 改读 capability + state policy，不再维护 type allowlist

## 4. Action 与 descriptor 服务

- [x] 4.1 定义 ActionSpec、RefSet predicate、executor family、reason code 和 Affordance DTO
- [x] 4.2 实现服务端 resolver：target capability ∩ actor policy ∩ state/source policy ∩ executor support
- [x] 4.3 执行端点复用同一 resolver 重验，测试陈旧客户端和绕过请求
- [x] 4.4 增加 Registry descriptor API（version/digest/profiles/edges/presentations/templates/actions）
- [x] 4.5 graph/view payload 增加 resolved capabilities、unknown_profile 与 affordances
- [ ] 4.6 descriptor 与 graph API 覆盖禁用原因、未知 Profile 和非科研示例

## 5. Registry 驱动前端

- [ ] 5.1 定义 descriptor/affordance DTO、缓存与 digest 失配刷新
- [ ] 5.2 添加节点目录改用 Profiles/Templates + create affordance，删除前端 ALLOW_PARENTS
- [ ] 5.3 cards/theme/Inspector 改读 PresentationSpec；实现稳定 generic fallback
- [ ] 5.4 ContextMenu/EdgeMenu/多选菜单改为 affordances，删除 task 派工和 module/model delete 分支
- [ ] 5.5 连接候选按 Edge Profile descriptor 预过滤，server 422/reason 保持硬闸
- [ ] 5.6 浏览器演示 software service Profile 的创建、连接、选择、Inspector 和通用动作

## 6. 验证、文档与复核

- [ ] 6.1 Registry/validator/doctor/migration/action resolver 定向测试全绿
- [ ] 6.2 前端组件、svelte-check、TypeScript 和 vite build 全绿；未知 Profile 不白屏
- [ ] 6.3 GitNexus impact/detect_changes 核对 frozen contract 与实际 affected flows
- [ ] 6.4 ruff、mypy --strict、pytest 全绿并记录精确命令/计数
- [ ] 6.5 更新 overview.md、kernel.md、frontend.md；同一时段由本 change 独占这些文档
- [ ] 6.6 `openspec validate generalize-graph-profile-registry --strict` 通过，完成 Codex 最终 diff 复核并记录证据
- [ ] 6.7 用户按 U1-U5 目验后再同步/归档
