# S8 agent 插座 — tasks

## 1. actor 贯通（最小、先行）

- [ ] 1.1 CLI actor 解析序：显式 `--actor` > `SIMULANKA_ACTOR` env > `user`（含单测）
- [ ] 1.2 operator 机械写命令核对 `--actor` 收齐（task create 等），事件日志记账验证
- [ ] 1.3 `run agent` 起 agent CLI 时注入 `SIMULANKA_ACTOR=agent`

## 2. 会话后端（转录 + 事件流）

- [ ] 2.1 归一事件词表 types + opencode 薄展示适配器（样本锁测试，未知事件降级不中断）
- [ ] 2.2 转录自持：`.simulanka/agent/sessions/<id>.jsonl` 边流边追加 + `GET /session/{id}/history`
- [ ] 2.3 `POST /session/{id}/message`：起续聊子进程（注入 `SIMULANKA_ACTOR=agent`）→ StreamingResponse NDJSON
- [ ] 2.4 `POST /session/{id}/stop`：杀当轮进程组 + 追加 `status: interrupted`
- [ ] 2.5 图聊/讨论会话迁入同一转录机制（`discussion.json` 降为索引指针）
- [ ] 2.6 vite proxy 加正则键 `'^/session(/|$)'`（第三坑规矩）

## 3. 会话前端（统一壳）

- [ ] 3.1 ChatNode 接流式 NDJSON（fetch + ReadableStream；滚动只用 afterUpdate＋计数 gate）
- [ ] 3.2 工具调用卡片（默认折叠、点开详情）+ 放大全屏抽屉（同组件展示态）
- [ ] 3.3 排队输入（轮中可打字、轮末自动发）+ 停止按钮
- [ ] 3.4 挂载恢复走 history 端点（刷新不丢，验证工具卡片还原）
- [ ] 3.5 task 右键「派工」：server 渲染 task 卡片级锚定戳预填首轮上下文
- [ ] 3.6 叫停收口提示：检出未配对 `run begin` → 「run 还开着」提示（不自动收）
- [ ] 3.7 锚定会话迁壳：讨论/核对会话挂批次锚走同一 ChatNode（一批一场/写权闸/checkpoint 不变）

## 4. run agent 骑括号（Codex 线）

- [ ] 4.1 规格出单：issue 通报 Codex（wrapper 改薄编排、changes.json 退役、detached 同构、判定序不变）
- [ ] 4.2 wrapper 改造合入（Codex 施工、交叉审）：同步/detached 双路走 begin→invoke→end
- [ ] 4.3 回归验证：run agent 产出的 run 与人肉括号结构一致（diff/契约/fulfills/acceptance 同源）

## 5. 验收（静态末位关）

- [ ] 5.1 玩具 task 定义（免费模型 deepseek-v4-flash-free；契约含 allowed_outputs + acceptance）
- [ ] 5.2 全链彩排：派工 → 会话流式 → agent 自己 run begin/end → diff/验收/落图 SSE 上画布，全程前端可见
- [ ] 5.3 三件套全绿（ruff / mypy --strict / pytest）+ svelte-check + vite build
- [ ] 5.4 docs 状态翻牌：overview 清单 S8 ✅、assembly/frontend 🔲 摘除；memory 落账
