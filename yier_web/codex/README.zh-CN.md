# Codex IPC 工作区

这个目录承载独立 `/codex` 工作区所需的 Codex 后端集成代码。

## 职责

- 根据 yier 持久化的 Codex 设置构建 `codex_bridge.CodexIpcConfig`。
- 为每个活跃 thread 保持一个长期存在的 `CodexIpcSession`。
- 通过共享 session event hub 将 Codex session 事件分发给 WebSocket、
  SSE 监听者，以及未来的外部 channel sink。
- 承载 Web 应用的 Codex-only 后端能力。

## 主要文件

- `ipc_manager.py`: 会话生命周期、workspace 列表、thread 命令与 session
  event 分发。
- `session_events.py`: Codex session event fanout 使用的 thread 订阅者与
  channel sink 注册表。

## 说明

- HTTP 与 WebSocket 路由在 `yier_web/routes/codex.py`。

## iframe 嵌入

Codex iframe 路由是 `/codex/embed?embed_token=...`。它复用 Codex
WebSocket，未登录访问需要配置 `YIER_CODEX_EMBED_TOKEN`。

- 新建会话：父窗口发送 `postMessage({ type: 'yier:codex-start', cwd, mode, goal, prompt })`
- 恢复会话：父窗口发送 `postMessage({ type: 'yier:codex-resume', threadId, mode, goal, prompt })`

URL 只传 `embed_token`，`cwd`、`threadId`、`mode`、`goal` 和 `prompt` 都通过
iframe message 传递。`mode` 支持 `build` 或 `plan`；`goal` 支持
`{ objective, tokenBudget }`。可选的 `commandId` 会原样返回到命令结果事件。

激活会话后，父窗口还可以发送：

- `yier:codex-send-prompt`、`yier:codex-steer-prompt`
- `yier:codex-enqueue-followup`、`yier:codex-remove-followup`
- `yier:codex-interrupt-turn`、`yier:codex-compact-thread`
- `yier:codex-set-mode`
- `yier:codex-set-goal`、`yier:codex-update-goal-status`、`yier:codex-clear-goal`
- `yier:codex-submit-user-input`
- `yier:codex-rename-thread`、`yier:codex-archive-thread`、`yier:codex-fork-thread`

iframe 会向父窗口发送：

- `yier:codex-ready`
- `yier:codex-thread-created`
- `yier:codex-thread-resumed`
- `yier:codex-prompt-sent`
- `yier:codex-command-result`
- `yier:codex-status`
- `yier:codex-turn-state`
- `yier:codex-goal-state`
- `yier:codex-mode-changed`
- `yier:codex-user-input-request`
- `yier:codex-followups-changed`
- `yier:codex-error`

turn 完成和 goal 完成是两个独立事件，分别通过 `yier:codex-turn-state` 和
`yier:codex-goal-state` 通知。
