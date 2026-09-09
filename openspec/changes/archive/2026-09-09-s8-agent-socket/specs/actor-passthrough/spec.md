# actor-passthrough — actor 身份贯通

## ADDED Requirements

### Requirement: CLI 缺省 actor 读环境
CLI 写图命令的 actor 解析序 SHALL 为：显式 `--actor` > 环境变量 `SIMULANKA_ACTOR` > 缺省 `user`。server 起任意 Provider 会话子进程时 SHALL 注入 `SIMULANKA_ACTOR=agent`。

#### Scenario: agent 会话内写图自动带身份
- **WHEN** 任意 Provider 会话里的 agent 执行 simulanka 写图命令（未显式传 --actor）
- **THEN** 落图事件的 actor 为 `agent`，写权矩阵按 agent 身份把闸（如人裁不可覆盖）

#### Scenario: 显式覆盖优先
- **WHEN** 环境有 `SIMULANKA_ACTOR=agent` 但命令显式传 `--actor operator`
- **THEN** 以 `operator` 记账

### Requirement: operator 机械写命令贯通
CLI 写命令 SHALL 接受 `--actor operator` 并在事件日志如实记账；不引入新权限档（写权矩阵词表不变）。

#### Scenario: 操作员建 task
- **WHEN** 以 `--actor operator` 执行 task create
- **THEN** 事件日志 actor=operator，图上铭章与 user 路径可区分
