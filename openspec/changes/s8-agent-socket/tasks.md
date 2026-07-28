## 0. 用户可目验门

- [ ] U1 通用会话：不选择节点也可直接发消息；首条消息懒创建会话；界面没有派工、讨论/干活或开始实验模式
- [ ] U2 增量上下文：任意 node/edge/port 可附加、预览；同一未变化 bundle 第二轮不重发；无附加时用户消息保持原样
- [ ] U3 原生续接：Codex 首轮拿到 thread id，第二轮走原生 resume；转录不 replay；Provider 报告的 cached_input_tokens 可检查
- [ ] U4 会话管理：刷新恢复、会话列表、切换、fork、归档、暂停/已中断和能力降级全程前端可见
- [ ] U5 可替换 Provider：OpenCode 与 Codex 复用同一 SessionEvent、storage 和 ChatNode，无 Provider-name 前端分支

## 1. 已有可复用地基

- [x] 1.1 CLI actor 解析序：显式 `--actor` > `SIMULANKA_ACTOR` > `user`
- [x] 1.2 归一事件词表与 OpenCode 样本锁；未知事件降级不中断
- [x] 1.3 Session JSONL 边流边追加与单场 history 端点
- [x] 1.4 ChatNode 流式文本、折叠工具卡片和同组件全屏展示
- [x] 1.5 `/session` vite proxy 与 server 最小 create/message 路径

## 2. Provider Adapter

- [x] 2.1 定义 ProviderCapabilities、ProviderAdapter、ProviderTurn/TurnHandle 合同与 Adapter registry
- [x] 2.2 将现有 OpenCode 参数构造、原生续聊和事件 normalize 收进 OpenCode Adapter，保持既有样本行为
- [x] 2.3 实现 Codex Adapter：`codex exec --json`、thread.started、`exec resume <id> --json`、文本/工具/状态事件
- [x] 2.4 映射 Codex turn.completed usage，保留 cached_input_tokens 缺失与存在两种诚实状态
- [x] 2.5 样本锁原生续接命令，证明第二轮不含 transcript replay，仅含本轮消息和新增 supplement
- [ ] 2.6 Provider 能力驱动 interrupt；一 Session 同时最多一个活动 TurnHandle

## 3. Supplemental Context

- [x] 3.1 定义有序去重 RefSet 与不可变 ContextBundle 模型（schema/compiler version、refs、graph version、payload、omissions、digest）
- [x] 3.2 实现 node/edge/port 解析和确定性 canonical serializer；未知/失效引用显式报错或 omission
- [x] 3.3 将 bundle 内容寻址写入 `.simulanka/agent/contexts/<digest>.json`，重复内容复用
- [x] 3.4 按 native session id 记录 sent digests；相同未变化 bundle 跳过，新 digest 增量发送
- [x] 3.5 实现上下文 preview API，返回最终 payload、来源、send/skip 与 omissions
- [x] 3.6 instruction/reference 分区；图 attrs、文件和工具内容默认作为带来源的不可信 reference
- [x] 3.7 测试无 supplement 时原消息逐字不变、重复 bundle 不重发、变化 bundle 新增量、canonical bytes 稳定

## 4. 通用 Session 后端

- [x] 4.1 以领域无关 Session 替代 WorkSession/task_anchor，持久化 Provider/native id/workspace/parent/status；旧 JSONL 兼容读取
- [x] 4.2 create/message 端点改接 Adapter + supplements，首条懒创建；删除 task 专属请求契约
- [ ] 4.3 增加会话 list、history、fork、archive API；Provider/模型变更只能新建或 fork
- [ ] 4.4 增加 stop API 与活动 handle 追踪；中断保留 native id、transcript、bundle 和工作区副作用
- [ ] 4.5 server 重启后将无 handle 的遗留 running 会话显示为 orphaned/interrupted
- [ ] 4.6 legacy discussion 端点迁到通用 Session 兼容层，不再拥有独立 transcript 或前端 mode

## 5. 统一前端会话壳

- [x] 5.1 API DTO 收敛为 Session、ProviderCapabilities、ContextPreview 和统一 SessionEvent
- [x] 5.2 App 状态收敛为 sessions/active_session_id/pending_refs/events，删除 discussionMessages/workMessages/activeChatKind
- [ ] 5.3 ChatDock 增加 pending refs 标签、移除/固定和 preview；支持 node/edge/port 与跨层收集
- [x] 5.4 发送首条消息懒创建 Session；无 supplement 时不改变用户文本
- [ ] 5.5 删除 task 右键派工、干活标题与开始类入口；选择 task 只产生普通 RefSet
- [ ] 5.6 根据 ProviderCapabilities 显示暂停等控制；显示 running/interrupted/orphaned/native_missing/stateless
- [ ] 5.7 会话列表、刷新恢复、切换、fork、归档与 usage/cache 详情可见

## 6. 验证与交付

- [ ] 6.1 后端定向测试覆盖 OpenCode/Codex adapter、native resume、无 replay、ContextBundle 和 stop/recovery
- [ ] 6.2 前端组件/浏览器验收覆盖 U1-U5，失败与能力降级不得显示成功
- [ ] 6.3 GitNexus detect_changes 确认影响范围；ruff、mypy --strict、pytest、svelte-check、vite build 全绿
- [ ] 6.4 `openspec validate s8-agent-socket --strict` 通过并同步 authoritative docs
- [ ] 6.5 GitHub Issue 记录规格改道、实现提交、验证证据与用户目验入口
