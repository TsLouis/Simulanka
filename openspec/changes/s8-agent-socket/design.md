# S8 agent 插座 — design

## Context

静态线余 S8（grill 收口 2026-07-18，定案见 `docs/assembly.md`「agent 插座子任务」＋`docs/frontend.md` S8 节）。现状：`agent/harness.py` 已会 opencode 非交互续聊（讨论线底座）；`ChatDock`/`ChatNode` 已是消息面（图聊会话真跑过）；`runner/bracket.py` + `workspace.py` 是 S1 落的共享测量；`agent/wrapper.py` 仍自带私有快照/diff（两套测量真相）；会话转录只存指针（07-16 已定自持规格，未施工）。死端：PTY 透传主路线。

## Goals / Non-Goals

**Goals:**

- 玩具 task 全链前端可见：派工 → 会话流式 → agent 自己 `run begin/end` 打卡 → diff/验收/落图经 SSE 上画布。
- 一条测量路径（run agent 骑括号）；一套会话壳（ChatNode）；一套转录机制（所有会话共用）。
- actor 身份贯通写权闸（env 注入，agent 会话里的 CLI 写图自动带正确身份）。

**Non-Goals:**

- 批准流/命令拦截（护栏 v1＝测量不拦，批准流挂动态线）；PTY 透传；多会话调度；轮内插话（无头轨道一问一答）；agent 输出质量（不作数）；皮肤；手稿层（S9）。

## Decisions

1. **轮次传输＝POST 即流**：`POST /session/{id}/message` 起子进程（opencode 续聊，`--format json`），以 StreamingResponse 逐行回 NDJSON 事件；前端 fetch + ReadableStream 渲染。不开第二条全局 SSE、不上 WebSocket——单轮单流最简，画布刷新仍走现有 `/events`。工作会话不设人为超时（长工具轮合法），断连=会话文件仍在、挂载恢复。
- 2. **事件词表归一**：`{type: user_msg|agent_text|tool_call|tool_result|status|error, …}`——opencode 原始事件由**薄展示适配器**（server 侧，每 harness 一个）翻译；opencode 格式已漂移过一次（07-14），适配器是隔离层，前端只认归一词表。
3. **转录自持**：`.simulanka/agent/sessions/<session_id>.jsonl` 每场一文件、事件边流边追加（server 写，含 anchor/applied 字段沿 07-16 规格）；`GET /session/{id}/history` 挂载恢复。讨论/图聊会话同机制迁入（`discussion.json` 指针保留为索引）。
4. **停止**：`POST /session/{id}/stop` → 杀当轮进程组 → 追加 `status: interrupted`。run 括号**留人收口**：ChatNode 检出会话内 `run begin` 未配对时提示「run r-xx 还开着」，人选 `run end` 或放着（doctor stale 兜底）。排队＝纯前端（输入不锁、轮末自动发）。
5. **actor 贯通**：server 起会话子进程注入 `SIMULANKA_ACTOR=agent`；CLI actor 解析序＝显式 `--actor` > env > 缺省 user。operator 贯通同机制（人侧机械命令加 `--actor operator`）。
6. **run agent 骑括号**：wrapper 改 `begin → invoke CLI → end` 薄编排，测量全走 `workspace.py` 同源；detached 同构（wrapper script 内 begin/end）；acceptance 时机沿既定（end/finalize）。wrapper 私有快照与 `changes.json` 退役（BREAKING 内部）。
7. **壳统一**：干活/图聊/核对讨论都是 ChatNode；工具调用卡片默认折叠、点开看详情；放大态＝同组件 CSS 展示态（非第二套壳）；锚定会话＝挂批次锚的同壳会话（一批一场/写权闸/checkpoint 全保留）。
8. **派工入口**：task 节点右键「派工」→ ChatNode 预填锚定戳（server 渲染 task 卡片级上下文，07-16 锚定戳规格的最小先行件：v1 只做 task 卡）；ChatDock 也可自由起干活会话。不立新按钮。

## Risks / Trade-offs

- [opencode JSON 再漂移] → 适配器单点隔离＋harness 测试锁样本；漂移只坏展示不坏写权（写图走 CLI）。
- [vite proxy 前缀吞路由] → 新路由 `/session` 必须用正则键 `'^/session(/|$)'`（第三次坑的既定规矩）。
- [Svelte 5 tick 地雷] → 流式滚动只用 `afterUpdate`＋计数 gate（铁律：`$:` 里禁 tick()）。
- [半成品盘上残留] → 有意为之：叫停不回滚（真实工作区），测量归系统、收口归人；worktree-per-run 流程天然限爆炸半径。
- [免费模型慢/笨] → 验收判据是「链路可见」不是「输出好」；输出不作数写进验收。

## Open Questions

- 玩具 task 具体定义（哪个仓、什么契约）——验收时现定，不阻塞施工。
