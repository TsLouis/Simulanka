# run-agent-bracket — run agent 骑 run 括号

## ADDED Requirements

### Requirement: 单一测量路径
`run agent` SHALL 改为 `run begin → 调用 agent CLI → run end` 的薄编排：快照/diff/时长/契约检查全部走 S1 共享测量（`workspace.py` / `runner/bracket.py` 同源）。wrapper 私有快照与 `changes.json` SHALL 退役（BREAKING 内部，无外部消费者）。

#### Scenario: 同步 run agent 走括号
- **WHEN** `run agent <agent> --task <task>` 同步执行完成
- **THEN** 产生的 run 节点与人肉 `run begin/end` 的 run 结构一致（同一套 diff 路径清单、契约镜像、fulfills 边、acceptance 落章），不存在第二套 diff 产物

#### Scenario: detached 同构
- **WHEN** `run agent --detach` 异步执行
- **THEN** wrapper script 在起点调 begin、finalize 时调 end（acceptance 沿既定 finalize 时机），惰性 reconcile 行为不变

### Requirement: 契约检查语义不变
骑括号改造 MUST NOT 改变既定裁定序：`out_of_scope > acceptance_failed`；挂 task 时镜像契约与 `fulfills` 边照旧。

#### Scenario: 越界写落章
- **WHEN** agent 在 run 中写了 `allowed_outputs` 之外的路径
- **THEN** run end 如实落 `out_of_scope`（与人肉括号路径同一判定代码）
