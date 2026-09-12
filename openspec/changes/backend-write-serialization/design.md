## Context

基线为 `main@3a3e2638b761da929499ed5545d44a5db9dc0269`。PR #15 审阅版本为 `410eaeff9035ebaf70d573171f789766c9782031`，仍是 Draft；当前 13 个变更文件只包含前端和 OpenSpec，尚未实现新的后端协议。

`apply_patch` 先读 manifest 再校验并逐个写实体，最后追加 event、更新 manifest、尝试 checkpoint。实体/manifest 使用固定临时路径，单文件 rename 不能串行化两次提交。`apply_patch_now` 的 live-version 读取也在提交之前。初始化、迁移、bundle 导入是额外的低层写者。

GitNexus 1.6.11 对该基线的 upstream 分析：`apply_patch` 14 个直接调用者、64 个三层影响符号、32 个已索引流程，`apply_patch_now` 15/33/19，均为 CRITICAL；`checkpoint` 为 CRITICAL，init/import/migrate/ensure/tag 为 LOW。FTS 不可用且全局流程索引有预算截断，故未把“没有命中”当成无影响；补充逐项检查 `save_*`、`delete_*`、`write_manifest`、`append_event` 的全部生产调用点。

## Goals / Non-Goals

**Goals:** 同一 canonical project root 的线程和独立进程共用写入顺序，嵌套写入不死锁；服务器基于当前图状态的写权检查与随后的提交也使用该边界。

**Non-Goals:** 无读取快照、崩溃回滚、SSE exactly-once、跨主机协调、任意外部文件编辑互斥或 Session 全局锁。底层 entity store 仍是内部写原语，不把单个 JSON 写锁当成事务。Registry 校验保持只读；用户冻结的 attrs/write matrix 不变。

## Decisions

### 1. Root sidecar lock, with thread reentrancy

新增 `storage/write_lock.py`，接收 `Path`，避免 layout/storage 循环导入。路径先 resolve；锁放在项目根的 `.simulanka.write.lock`，而非 `.simulanka/` 内。这样可在 init/import 的存在性检查前加锁，也不会随 checkpoint 恢复或 bundle 导入更换 inode。

进程内按 canonical root 共享 `RLock` 和嵌套深度；外层使用标准库 OS 文件锁（POSIX flock / Windows byte-range lock），内层不再次打开文件。仅竞争时等待；不能打开/锁定时向调用方抛出 OS 错误且不进入写区。正常退出、异常、进程死亡由 close/OS 释放，保留锁文件，不采用 PID 文件、unlink 解锁或“陈旧锁”删除。POSIX fork 子进程关闭继承的锁描述符并重置本地缓存，不能把父进程持有状态视为子进程重入。

选择 OS advisory lock 是为了让不同 API/CLI 进程共同协调；仅 threading.Lock 无法满足此要求。数据库迁移会大幅扩大 #9 范围。项目锁优先于实体锁，避免跨实体版本、事件及 checkpoint 的多锁顺序问题。新增项目的 root ignore 包含锁文件，已有用户 gitignore 不被覆盖。

### 2. Critical sections cover decisions and commit

- 显式 `apply_patch` 从 schema/registry/version 检查开始，到 receipt/checkpoint 完成才释放。
- `apply_patch_now` 在相同可重入边界内读版本并调用 `apply_patch`；不会无条件重试一个已经陈旧的显式 PatchIntent。
- init/import 在创建 `.simulanka/` 或判空之前锁定；迁移在生成计划之前锁定。checkpoint 的 init/add/commit/tag 也共享锁，避免嵌套 git index 竞争。
- 纯图 HTTP 写动作从读取目标和解析 state/actor affordance 开始持锁；Agent op 的政策检查与提交也持锁。这样 Keep 与另一进程的修改不能在校验后悄悄交错。
- 不把 Provider 生成、PTY、等待用户输入、Session SSE、ContextBundle 编译或外部命令执行放进图写区。多 Patch 的业务操作仍保留既有多版本/部分失败语义，锁不承诺它们可回滚。

### 3. Frontend v2 backend alignment

复用现有 executor family；“前端更轻”不要求后端增加领域会话类型，也不要求把所有交互记录成图提交。

| PR #15 交互 | 后端归属与当前约束 | #9 的处理 |
| --- | --- | --- |
| Companion 位置、zoom、临时 attention | UI/临时 projection；不修改 Node/Edge/Port、graph_version | 无图写锁；不新增 API |
| Ask node/edge/port/selection | SessionCommand + 显式 RefSet，显示 pending refs 并可预览实际 payload/omissions | 保留 S8 API；附近对象、viewport、provenance 查询不自动进入模型上下文 |
| 对象旁短解释 annotation | 后续 Session/conversation sidecar，以稳定 entity ref 关联；不是默认写 attrs/note | 本次只确定归属；持久化/重放协议需单独 OpenSpec，不把尚未实现的能力记为完成 |
| 已持久化 proposed edge 的 Keep | GraphCommand，server `edge.accept` 重新校验 proposed 状态后提交 | 目标读取、政策检查和 commit 共用锁；失败保留真实状态 |
| Dismiss suggestion | 现有 `edge.verdict(wrong, note)`；保留 proposed 实体供后续处理 | 不能当作 DELETE 或撤销；继续要求现有 note 合同 |
| Mark for attention | 现有 `edge.discuss` 写 attrs 的持久动作 | 与临时 Agent attention 分开；此动作需要图锁 |
| Why / Related | 现有 provenance 只读查询，表示真实上游链 | 不伪装成任意邻居查询或已发送 ContextBundle |
| Node 输入/输出及连线 | 真实 Port 与 Registry eligibility；out/in 及 root tunnel 规则保持 | 创建连接经 kernel 锁内校验；隐藏 Port 不改变数据 |

Draft 是展示层概念，必须区分两类：已在图中持久化但尚未接受的 proposed 实体，以及尚未提交的纯预览。`source=agent` 只表示来源，accepted edge 仍保留此来源，不能单靠 source 显示 Draft。Keep 必须依据 server 返回的 enabled affordance；存在一个 disabled 的 `edge.accept` 条目不等于当前处于 proposed 状态。PR #15 `EdgeMenu.svelte` 的 source badge 与 `!acceptAction` 分支需要前端复核。

长期衔接顺序：#9 串行提交 → #10 恢复协议/一致可见的提交边界 → #11 统一 run 收尾与结果归一 → #12 沿 GraphCommand、SessionCommand、ProjectionCommand 分服务 → #13 用真实图测量按需视图、Port 密度与上下文编译成本。服务拆分可与可靠性工作并行规划，不为像素风/面板折叠新增领域分支。

reversible auto-apply + Undo 是后续能力：当前 checkpoint 是 best effort 的整目录快照，不证明一个 action 可独立逆转。Undo 应是有版本前提、重新校验权限的补偿动作，不能 reset 整图而覆盖后来的人工作业；在 #10 与独立 Undo 规格验收前，不据此放宽写权。

### 4. Validation and explicit Codex pre-implementation review

已在未修改基线上用独立 Python 进程、版本读取后的握手屏障复现：两个 receipt 均为 1、manifest_version=1、event_versions=[1,1]，两个不同节点均已写入。随后以真实 OS 竞争验证同一 base 只能一成功一 VersionConflict；重新读取版本重试后事件应连续、hash/doctor 正确。覆盖 convenience 写入、线程、nested、不同项目、锁打开失败、持锁进程死亡、fork、init/import/migration、checkpoint 与 HTTP Keep 的交错。

Codex 设计审查结论：该方案加强既有版本与服务端状态校验的时序，不改变实体或写权合同；临界区不包含模型运行。根据高影响范围增加 server/agent-op 回归和真实进程测试后可以实施。锁释放只证明下一次能获取锁，不证明上次中途崩溃的数据完整；不得以此关闭 #10。

## Risks / Trade-offs

- [慢磁盘或 checkpoint 延长等待] → 锁仅围绕短同步写动作；现有全图 hash 优化留给 #13，不在模型执行期间持锁。
- [外部工具删锁文件或直接编辑 graph] → advisory 协议只覆盖合作写者；维护/恢复也必须遵循同一协议，禁止运行时删除或替换锁文件。
- [锁定后出现 I/O 错误] → 释放锁并传播错误；多文件部分写入仍需 #10，不自动假修复。
- [平台差异] → Linux 运行进程/线程/fork 验证；Windows 分支如无可用运行环境则明确记录未实测，不扩大为跨主机保证。
- [前端将轻量标签误读为权限或状态] → 提供上述映射与 PR 反馈，并保留 actor/status/reason 的详情通路。

## Migration Plan

无需 schema/registry bump。停掉同一项目的旧写进程后升级全部写者；混用旧版写者无法被 advisory lock 保护。锁文件首次写入时创建；升级不重写现有图。回退程序前同样停止写者，保留惰性锁文件即可，不需要删文件“解锁”。
