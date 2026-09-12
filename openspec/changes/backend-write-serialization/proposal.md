## Why

Issue #9：`apply_patch` 的版本读取、校验和多文件写入没有共同的跨进程边界，两个写者可能同时通过同一版本检查。PR #15 引入更频繁的图上协作，Keep/Dismiss、Port 连接与 Agent 提交必须共享可靠的写入顺序。

## What Changes

- 用项目级、可重入的 OS advisory lock 串行化图提交；版本检查、状态校验、实体写入、event、manifest 和提交后的 checkpoint 均在同一临界区内。
- `apply_patch_now` 在锁内读取当前版本；显式 PatchIntent 继续按原版本拒绝冲突，由调用方重读后重试。
- 初始化、迁移、bundle 导入及独立 checkpoint 入口遵守同一边界；锁文件不进入 bundle、图 hash 或 checkpoint。
- 增加独立进程竞争、线程竞争、失败释放、退出释放、嵌套提交与 HTTP/库交错测试。
- 更新后端设计以对齐 PR #15：区分图提交、Session sidecar 和临时 UI；说明 Draft 状态与来源、显式 context 及后续 recovery/Undo 的边界。

## Capabilities

### New Capabilities

- `graph-write-serialization`: 定义同一项目的协作写入顺序、版本冲突及锁生命周期。

### Modified Capabilities

无。现有 Registry、actor、affordance、Session 和 supplemental-context 合同保持兼容。

## Impact

- `kernel/apply.py`、`kernel/migration.py`、`kernel/bundle.py`、`layout/project.py`、`storage/checkpoint.py`、`server/app.py` 的纯图动作及 `server/agent_ops.py`，新增 storage 写锁模块与针对性测试。
- HTTP 与 CLI 经现有 kernel 入口获得串行提交；不改 API 路由、DTO、实体 schema 或 frozen write matrix。
- `docs/kernel.md` 由本 Issue 独占更新；PR #15 的前端文件和 `docs/frontend.md` 保持由 #14 管理。
- 使用标准库 OS 文件锁，无新增第三方依赖。范围为同一主机、支持 advisory lock 的本地文件系统；网络文件系统与跨主机协调不在本次保证内。
- #10 继续负责写入中途崩溃恢复；#11/#12 的后续设计应沿用 GraphCommand / SessionCommand / ProjectionCommand 的既有执行边界。串行写入不等于多文件 crash atomicity、读取快照或业务 Undo。
