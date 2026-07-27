# agent-session — 前端内嵌干活 agent 会话

## ADDED Requirements

### Requirement: 用户只用浏览器完成验收
S8 的用户验收 SHALL 从 task 派工开始，到查看会话、工具调用、run、diff、契约验收与写权拒绝结束，全程只使用前端。CLI、转录文件与服务端日志 MAY 作为实现诊断或机器证据，但 MUST NOT 成为用户理解状态、完成收口或判断结果的必经步骤。用户动作后前端 MUST 立即呈现已接收、运行中、待发送、正在停止、已中断、完成或失败中的明确状态，不得以无反馈等待冒充流式交互。

#### Scenario: 浏览器内完成一次玩具 task
- **WHEN** 用户从 task 卡片右键派工，并在会话内让免费模型完成玩具 task
- **THEN** 用户无需打开终端即可看到会话进展、工具调用、run 状态、文件 diff、acceptance 结果及画布落图

#### Scenario: 慢模型仍有即时反馈
- **WHEN** agent 尚未产出第一段模型文本
- **THEN** 前端立即显示请求已接收与当前运行状态，页面和画布保持可交互

### Requirement: 会话轮次即流
server SHALL 提供 `POST /session/{id}/message`：接收用户消息后起 opencode 续聊子进程（`--format json`），并以 StreamingResponse 逐行返回**归一事件**（NDJSON，词表 `user_msg / agent_text / tool_call / tool_result / status / error`）；opencode 原始事件 MUST 经 server 侧薄展示适配器翻译，前端只认归一词表。

#### Scenario: 一轮干活流式可见
- **WHEN** 用户在 ChatNode 发出消息且 agent 在该轮调用了工具
- **THEN** 前端按到达顺序渲染 `agent_text`（流式文本）与 `tool_call/tool_result`（卡片，默认折叠），轮末收到 `status: done`

#### Scenario: 适配器隔离格式漂移
- **WHEN** opencode 输出了词表外的未知事件类型
- **THEN** 适配器丢弃或降级为 `status` 事件，流不中断、不向前端泄漏原始格式

### Requirement: 转录自持与挂载恢复
server SHALL 把每场会话的归一事件边流边追加到 `.simulanka/agent/sessions/<session_id>.jsonl`（每场一文件），并提供 `GET /session/{id}/history`；前端挂载 ChatNode 时 MUST 用 history 恢复完整消息流。图聊/核对讨论会话 SHALL 迁入同一转录机制。

#### Scenario: 刷新不丢会话
- **WHEN** 用户在会话进行若干轮后刷新页面并重新打开该 ChatNode
- **THEN** 完整历史（含工具卡片）从转录文件恢复显示

### Requirement: 停止按钮与叫停收口
server SHALL 提供 `POST /session/{id}/stop`：杀当轮子进程组并向转录追加 `status: interrupted`。叫停 MUST NOT 自动收 run 括号或回滚工作区；ChatNode SHALL 在会话内检出未配对的 `run begin` 时提示「run 还开着」，并提供「结束并测量」与「暂不处理」两个前端动作。用户选择前者时由前端调用同源 run end 能力；用户不得被要求转到 CLI 收口。

#### Scenario: 中途叫停
- **WHEN** agent 干活中用户点停止
- **THEN** 当轮进程被杀、消息流出现「已中断」标记，盘上已发生的改动保持原样

#### Scenario: 叫停后括号提示
- **WHEN** 被叫停的会话此前已 `run begin` 且未 `run end`
- **THEN** ChatNode 显示该 run 仍开着的提示及「结束并测量 / 暂不处理」动作，不自动测量、不自动标状态

### Requirement: 排队与一问一答
轮进行中输入框 SHALL 保持可输入；用户消息 SHALL 排队并在当轮结束后自动发出。轮进行中 MUST NOT 向 agent 注入消息（无头轨道，一问一答制）。

#### Scenario: 轮中打字排队
- **WHEN** agent 干活中用户输入并发送一条消息
- **THEN** 消息进入队列显示待发状态，当轮 `status: done` 后自动作为下一轮发出

### Requirement: 统一壳与派工入口
干活/图聊/核对讨论会话 SHALL 共用 ChatNode 壳（差异只在卡片类型与 agent 配置），并提供一键放大全屏抽屉（同组件展示态）。task 节点右键 SHALL 提供「派工」入口：新开干活会话并预填 server 渲染的 task 卡片级锚定戳；ChatDock SHALL 可自由起干活会话。锚定（核对/讨论）会话 SHALL 挂批次锚，一批一场/写权闸/checkpoint 机制不变。

#### Scenario: 从 task 派工
- **WHEN** 用户在 task 节点右键选「派工」并发出首条消息
- **THEN** 会话首轮上下文携带该 task 的卡片级锚定戳（id/name/契约摘要），agent 能复述任务对象

### Requirement: run 结果前端可追溯
干活会话产生的 run SHALL 在前端显示状态与 task 关联，并提供可直接检查的文件 diff、acceptance 命令及结果、`out_of_scope` 结果、写权闸拒绝理由与 actor 记账。原始 attrs MAY 继续存在于 inspector，但 MUST NOT 是用户理解这些结果的唯一方式。

#### Scenario: 用户检查完成结果
- **WHEN** agent 完成或失败并关闭 run
- **THEN** 用户可从 ChatNode 或画布 run 卡片进入结构化结果视图，辨认修改文件、契约裁定及其原因

#### Scenario: 失败不伪装成功
- **WHEN** 工具失败、写权闸拒绝、事件格式未知或 acceptance 不通过
- **THEN** 对应失败进入消息流或结构化结果视图，页面不中断且不得显示成成功
