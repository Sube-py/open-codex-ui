# Codex Iframe Embed

Open Codex UI exposes a chat-only Codex iframe at `/codex/embed`. The iframe does not
show the Codex session list or the main app navigation.

Set an embed token on the Open Codex UI server:

```bash
export YIER_CODEX_EMBED_TOKEN='change-this-embed-token'
```

Embed the chat frame with only the token in the URL:

```html
<iframe
  id="codex-frame"
  src="http://127.0.0.1:13140/codex/embed?embed_token=change-this-embed-token"
  style="width: 100%; height: 720px; border: 0"
></iframe>
```

All operational parameters are sent with `postMessage`; the iframe URL only carries
`embed_token`. Start a thread, set plan mode, create a goal, and send an initial prompt:

```js
const frame = document.querySelector('#codex-frame')

frame.contentWindow.postMessage(
  {
    type: 'yier:codex-start',
    cwd: '/Users/me/project',
    mode: 'plan',
    goal: {
      objective: 'Finish the migration',
      tokenBudget: 12000,
    },
    prompt: 'Inspect this project',
  },
  'http://127.0.0.1:13140',
)
```

Resume an existing Codex thread:

```js
frame.contentWindow.postMessage(
  {
    type: 'yier:codex-resume',
    threadId: 'thread-id-here',
    mode: 'plan',
  },
  'http://127.0.0.1:13140',
)
```

`mode`, `goal`, and `prompt` are optional on both start and resume. The iframe
selects the thread, applies mode and goal, then sends the prompt. `cwd` is resolved
by the backend as the Codex working directory. Optional `commandId` values are
echoed in `yier:codex-command-result` responses.

The parent can also send these commands after a thread is active:

- `yier:codex-send-prompt`: `prompt` plus optional model, reasoning, attachment,
  and permission fields
- `yier:codex-steer-prompt`: `prompt`
- `yier:codex-enqueue-followup`: `prompt`
- `yier:codex-remove-followup`: `messageId`
- `yier:codex-interrupt-turn`
- `yier:codex-compact-thread`
- `yier:codex-set-mode`: `mode` (`build` or `plan`)
- `yier:codex-set-goal`: `objective`, optional `tokenBudget`
- `yier:codex-update-goal-status`: `status`
- `yier:codex-clear-goal`
- `yier:codex-submit-user-input`: `requestId`, `response`
- `yier:codex-rename-thread`: `name`
- `yier:codex-archive-thread`
- `yier:codex-fork-thread`

If authentication is enabled, the iframe page is public, but the Codex WebSocket
still requires a valid `embed_token` unless the browser already has an
authenticated Open Codex UI session.

The iframe posts lifecycle messages to its parent window:

```js
window.addEventListener('message', (event) => {
  if (event.data?.type === 'yier:codex-ready') {
    console.log('Codex iframe is ready')
  }
  if (event.data?.type === 'yier:codex-thread-created') {
    console.log(event.data.threadId, event.data.cwd, event.data.mode)
  }
  if (event.data?.type === 'yier:codex-thread-resumed') {
    console.log(event.data.threadId, event.data.cwd, event.data.mode)
  }
  if (event.data?.type === 'yier:codex-prompt-sent') {
    console.log(event.data.threadId, event.data.cwd, event.data.mode)
  }
  if (event.data?.type === 'yier:codex-command-result') {
    console.log(event.data.commandId, event.data.command, event.data.ok)
  }
  if (event.data?.type === 'yier:codex-turn-state') {
    console.log(event.data.threadId, event.data.turn)
  }
  if (event.data?.type === 'yier:codex-goal-state') {
    console.log(event.data.threadId, event.data.goal, event.data.completedGoal)
  }
  if (event.data?.type === 'yier:codex-mode-changed') {
    console.log(event.data.threadId, event.data.mode)
  }
  if (event.data?.type === 'yier:codex-user-input-request') {
    console.log(event.data.threadId, event.data.request)
  }
  if (event.data?.type === 'yier:codex-error') {
    console.error(event.data.message)
  }
})
```

The iframe also emits the compatibility event `yier:codex-status` and the queue
event `yier:codex-followups-changed`. Goal completion is reported by
`yier:codex-goal-state`; turn completion is reported independently by
`yier:codex-turn-state`.
