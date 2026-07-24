# S8 agent 插座（静态末位件）

## Why

静态验收关已过（2026-07-17 彩排二轮），静态线只余 S8：agent 调用插座的前端闭环。目标＝「免费模型跑一个玩具 task，会话/diff/验收/落图全链前端可见，输出不作数」——把 agent 从 CLI 幕后请到画布上，同时消掉 run agent 与 run 括号两套并行测量真相。规格权威来源：`docs/assembly.md`「agent 插座子任务」＋`docs/frontend.md` S8 节（含 2026-07-18 grill 增补）。

## What Changes

- **前端内嵌干活 agent 会话**：统一 ChatNode 壳（图聊/核对讨论/干活会话一张脸），干活会话＝工具调用卡片（默认折叠）＋一键放大全屏抽屉；opencode 非交互续聊，`--format json` 事件流边到边转；转录自持（每场一文件、挂载恢复；词表 `user_msg / agent_text / tool_call / tool_result / status / error`）。
- **交互契约**：task 右键「派工」＋ChatDock 自由起；一问一答＋打字排队（轮末自动发）＋停止按钮（杀当轮、如实标中断；**run 括号留人收口**，doctor stale 检查兜底）。护栏 v1＝测量不拦（无批准流）。
- **run agent 骑 run 括号**：wrapper 私有快照/diff 退役，改 `run begin → 调 CLI → run end` 薄编排（`workspace.py` 同源测量，全系统一条测量路径）。**BREAKING**（内部）：`changes.json` 平面文件路径让位于括号测量产物。
- **`--actor` 贯通**：会话/CLI 子进程注入 `SIMULANKA_ACTOR`，CLI 缺省 actor 读环境——agent 会话里跑的写图命令自动带正确身份过写权闸。
- **锚定会话 UI**：讨论/核对会话迁入同一 ChatNode 壳挂批次锚（一批一场/写权闸/checkpoint 机制全保留，DiscussPanel 不复活）。

## Capabilities

### New Capabilities

- `agent-session`：前端内嵌干活 agent 会话——server 起停/续聊/事件流/转录持久化/停止，与统一 ChatNode 壳的交互契约（派工入口、排队、叫停收口、锚定会话挂批次锚）。
- `run-agent-bracket`：`run agent` 骑 run 括号——薄编排、同源测量、detached 同构、acceptance 时机沿既定（end/finalize）。
- `actor-passthrough`：`SIMULANKA_ACTOR` 环境注入与 CLI 缺省 actor 解析，operator/agent 身份贯通写权闸。

### Modified Capabilities

（无——openspec specs 目前为空，S8 是试点第一单。）

## Impact

- **后端**：`server/`（会话端点＋SSE/流式转发）、`agent/harness.py`（复用续聊）、`agent/wrapper.py`（骑括号改造）、`runner/bracket.py`（不动或微调）、`cli/`（actor env 缺省）。
- **前端**：`ChatNode`/`ChatDock`（工具卡片、放大态、派工入口、排队/停止）、右键菜单。
- **不动**：kernel 写权矩阵、契约检查、转录之外的图状态机制。验收跑免费模型（deepseek-v4-flash-free），零 API 花销。
