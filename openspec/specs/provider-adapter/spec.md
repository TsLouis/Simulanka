# provider-adapter Specification

## Purpose
TBD - created by archiving change s8-agent-socket. Update Purpose after archive.
## Requirements
### Requirement: Provider 能力合同
每个 Provider Adapter SHALL 声明 `native_resume`、`native_fork`、`interrupt`、`tool_events` 和 `usage` 能力，并实现新建轮次、原生续接、事件归一及其声明支持的控制动作。前端 SHALL 根据能力声明显示或隐藏控制，不按 Provider 名称分支。

#### Scenario: 能力驱动暂停
- **WHEN** Adapter 声明 interrupt=false
- **THEN** 前端不显示可执行暂停控制，但其他会话功能保持可用

### Requirement: Provider 原生配置保持有效
Adapter 默认 SHALL 继承 Provider 原生用户配置、项目指令、skills、MCP、workspace、sandbox 和 approval 行为。平台 MUST NOT 用自建系统 prompt 或默认参数覆盖这些配置；确需覆盖时必须由用户显式配置并可见。

#### Scenario: Codex 项目含 AGENTS.md
- **WHEN** Codex Adapter 在该项目启动会话
- **THEN** Codex 按原生规则加载 AGENTS.md，Simulanka 不复制或重写其内容

### Requirement: Codex 原生 JSONL 与 resume
Codex Adapter SHALL 以 `codex exec --json` 启动首轮，从 `thread.started` 获取 native session id，并以 `codex exec resume <SESSION_ID> --json` 续接后续轮。Adapter MUST NOT 通过 transcript replay 模拟续聊。

#### Scenario: Codex 第二轮
- **WHEN** 首轮已记录 Codex thread id
- **THEN** 第二轮命令使用该 id 的原生 resume，且输入只含本轮用户消息和新增 supplemental context

### Requirement: Provider 事件隔离
每个 Adapter SHALL 在单一边界内把 Provider 原始事件转换为 SessionEvent。Provider 格式变化 MUST NOT 要求修改 ChatNode 或通用 Session storage。

#### Scenario: 新增 Provider
- **WHEN** 实现一个满足合同的新 Provider Adapter
- **THEN** 无需修改前端事件类型与通用会话生命周期即可显示其文本、工具和状态

### Requirement: 活动 TurnHandle 可取消
支持 interrupt 的 Adapter SHALL 返回可取消 TurnHandle；Session runtime SHALL 以平台 session id 追踪活动 handle，并确保一场会话同一时刻至多一个 turn running。

#### Scenario: 并发发送
- **WHEN** 同一 Session 已有 running turn 又收到发送请求
- **THEN** server 拒绝第二个并发 turn 或把它留作显式草稿，不并行调用 Provider

