# Codex IPC Workspace

This package contains the Codex-specific backend integration for the standalone
`/codex` workspace.

## Responsibilities

- Build `codex_bridge.CodexIpcConfig` from stored yier Codex settings.
- Keep one long-lived `CodexIpcSession` per active thread.
- Fan out Codex session events to WebSocket subscribers, SSE listeners, and
  future channel sinks through a shared session event hub.
- Own the Codex-only backend surface for the web app.

## Main Files

- `ipc_manager.py`: session lifecycle, workspace listing, thread commands, and
- session event fanout state.
- `session_events.py`: thread subscriber and channel sink registry for Codex
  session event fanout.

## Notes

- HTTP and WebSocket routes live in `yier_web/routes/codex.py`.

## Iframe Embed

The Codex embed route is `/codex/embed?embed_token=...`. It reuses the Codex
WebSocket and requires `YIER_CODEX_EMBED_TOKEN` for unauthenticated access.

- New thread: parent sends `postMessage({ type: 'yier:codex-start', cwd, mode, goal, prompt })`
- Resume thread: parent sends `postMessage({ type: 'yier:codex-resume', threadId, mode, goal, prompt })`

Only `embed_token` belongs in the URL. `cwd`, `threadId`, `mode`, `goal`, and
`prompt` are passed through iframe messages. Mode accepts `build` or `plan`; goal
accepts `{ objective, tokenBudget }`. Optional `commandId` values are echoed in
command result events.

After a thread is active, the parent can also send prompt, steer, follow-up,
interrupt, compact, mode, goal lifecycle, user-input response, rename, archive,
and fork commands. The iframe sends these events to the parent:

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

Turn completion and goal completion are independent and are reported by
`yier:codex-turn-state` and `yier:codex-goal-state`, respectively.
