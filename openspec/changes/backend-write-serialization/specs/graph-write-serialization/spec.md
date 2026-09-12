## Purpose

定义同一主机上合作写者对同一项目的串行图提交行为，覆盖版本前提、服务端状态检查、线程与进程竞争、锁生命周期及维护入口，同时明确其与崩溃恢复和 UI/会话状态的边界。

## ADDED Requirements

### Requirement: 同一项目的提交串行执行
系统 SHALL 在同一写入边界内完成版本检查、图状态校验、实体变更、event、manifest 与提交后的 checkpoint。不同线程或进程 MUST NOT 同时执行这些步骤；项目路径的符号链接别名 MUST 共用该边界。

#### Scenario: 两个进程提交同一 base
- **WHEN** 两个进程向同一项目提交 base_graph_version=v 的有效 intent
- **THEN** 一个提交为 v+1，另一个得到 VersionConflict 且不写入它的实体或 event

#### Scenario: 冲突后重试
- **WHEN** 冲突者读取最新版本并重新提交有效 intent
- **THEN** 后续提交版本与事件连续，content_hash 与实体一致且 doctor 不报告本次竞争造成的损坏

### Requirement: 即时提交在边界内读取版本
不携带调用方版本前提的即时提交 SHALL 在获得写入边界后读取版本；显式版本前提 MUST 保留，系统不得自动覆盖它来掩盖冲突。

#### Scenario: 两个即时提交
- **WHEN** 两个独立写者提交各自有效的即时修改
- **THEN** 两个修改按顺序保留并获得不同的连续版本

### Requirement: 服务端状态决策与图提交共享边界
图写动作 SHALL 在同一写入边界内重新读取目标、执行既有 actor/state policy 和提交；写入串行化 MUST NOT 放宽已有 affordance、Registry 或 write matrix。

#### Scenario: 竞争接受同一建议
- **WHEN** 两个 HTTP/Agent 写者竞争修改同一 proposed edge，前一操作改变了后一动作的适用状态
- **THEN** 后一动作依据最新状态执行或按原政策拒绝，不使用等待前的政策判定

### Requirement: 维护写者使用同一顺序
初始化、迁移、bundle 导入及独立 checkpoint 操作 SHALL 与同项目图提交互斥，存在性检查、迁移计划生成和图写入不得跨越该边界。

#### Scenario: 同时初始化或导入同一路径
- **WHEN** 多个进程尝试初始化或导入同一目标
- **THEN** 后执行者看到先执行者完成后的状态，并保持既有幂等或非空拒绝合同，不覆盖已完成项目

#### Scenario: 竞争迁移
- **WHEN** 两个进程尝试同一版本迁移
- **THEN** 至多一个执行非空迁移，另一个在锁内重新计划且不重复生成迁移 event

### Requirement: 锁生命周期可重入且失败不放行
同线程嵌套调用 SHALL 可重入，不同项目 SHALL 可独立提交。不能获取有效 OS 锁时 MUST 不进入写区。异常退出或持有者进程死亡后 MUST 允许其他写者重新获取锁，无需删除锁文件；fork 子进程 MUST NOT 继承父进程的重入资格。

#### Scenario: 校验失败或进程死亡
- **WHEN** 持有者在首次图写入前抛错或被终止
- **THEN** 后续写者可正常获取锁并提交，图仍保持原先一致状态

#### Scenario: 嵌套 scaffold 与 checkpoint
- **WHEN** 初始化或图提交内部再次调用受保护的写入入口
- **THEN** 操作完成，不因同线程重复获取而死锁

### Requirement: 锁与数据及交互状态分离
锁文件 MUST NOT 进入 graph content_hash、bundle 或 embedded checkpoint。系统 MUST NOT 为 Provider 执行、用户思考、临时 UI attention 或 Companion 位置持有图写锁，也 MUST NOT 将串行写入宣称为多文件崩溃原子性或业务 Undo。

#### Scenario: 模型运行期间的人工操作
- **WHEN** 一个 Session 正等待 Provider 或用户输入，另一个写者进行有效图修改
- **THEN** 该图修改不因整个 Session 的存续而阻塞

#### Scenario: 写入中途进程终止
- **WHEN** 进程在部分实体已落盘后退出
- **THEN** 锁可以释放，但系统不据此宣称该次提交已完整恢复或可被安全 Undo
