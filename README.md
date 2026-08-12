<p align="center">
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/brand/open-codex-ui-logo.svg" alt="Open Codex UI" width="520">
</p>

# Open Codex UI

Open Codex UI is a browser workspace for continuing Codex work wherever you
are. It gives your existing Codex sessions a practical home across desktop and
mobile devices, without asking you to leave the Codex ecosystem behind.

Use it beside ChatGPT Desktop when that is where a task begins, then keep the
same work moving from a browser, phone, tablet, or another computer. It is an
independent project and is not affiliated with OpenAI or ChatGPT.

> [!IMPORTANT]
> **Non-commercial use only.** This project is provided solely for learning,
> research, personal use, and other non-commercial purposes. Commercial use
> requires prior written permission from the copyright holder.

## What It Gives You

- **A familiar Codex workspace**: browse projects and recent threads, resume
  prior work, create new sessions, and keep the conversation history available
  from one responsive interface.
- **Continuity with your Codex setup**: work with the sessions, projects, and
  local Codex installation you already use rather than adopting another agent
  runtime or conversation format.
- **SSH remote workspaces**: connect a remote machine, select its project
  directories, and work with Codex where the code and tools actually live.
  Existing `~/.ssh/config` hosts can be discovered from the UI.
- **Voice input**: dictate prompts in the composer with local streaming speech
  recognition. The bundled workflow supports a bilingual Chinese-English
  sherpa-onnx model and keeps model configuration in Settings.
- **A mobile-friendly experience**: session navigation, project switching, and
  chat remain usable on a phone or tablet, so a running task is not tied to a
  desk.
- **Private or shareable access**: use it on your local network, expose it
  through a Cloudflare Tunnel, and protect a shared instance with application
  authentication.

## Preview

<p align="center">
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/screenshots/open-codex-ui-desktop.png" alt="Open Codex UI desktop workspace">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/screenshots/open-codex-ui-mobile-chat.png" alt="Open Codex UI mobile chat" width="300">
  &nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/screenshots/open-codex-ui-mobile-projects.png" alt="Open Codex UI mobile project drawer" width="300">
</p>

## Start Here

Launch the packaged app with Node.js:

```bash
npx open-codex-ui
```

Or use [`uv`](https://docs.astral.sh/uv/) directly:

```bash
uvx open-codex-ui
```

Open `http://127.0.0.1:13140`, then add a project or resume a recent Codex
thread. The server listens on `0.0.0.0` by default, making it reachable from
other devices on your local network. For a local-only instance:

```bash
uvx open-codex-ui serve --host 127.0.0.1 --port 13140
```

## Work From Anywhere

### Remote Machines Over SSH

Add an SSH connection from the sidebar, verify that Codex is available on the
remote host, and create remote projects from its filesystem. Connections can
use a hostname, user, port, identity file, or an alias already defined in
`~/.ssh/config`.

### Mobile and Voice

The layout is built for narrow screens as well as desktop. On supported
browsers, hold the microphone control in the composer to dictate a prompt.
Install the local speech model once:

```bash
open-codex-ui speech install
```

Model location, execution provider, and decoder threads are configurable from
**Settings -> Voice**. Remote mobile browsers need HTTPS for microphone access;
`localhost` is treated as secure by modern browsers.

### Share Securely

For a temporary public URL, start a Cloudflare Quick Tunnel:

```bash
open-codex-ui tunnel start
```

For an always-on personal workspace, install the login service:

```bash
open-codex-ui daemon install
```

Turn on password protection from **Settings -> Authentication** before exposing
the app beyond a trusted network. The UI stores the password as a hash and
persists its settings under `~/.yier/web/settings.json`.

> [!WARNING]
> A public tunnel exposes the workspace to the Internet. Enable application
> authentication or Cloudflare Access before sharing its URL.

## Configuration Notes

Most personal configuration is available from Settings and is stored in
`~/.yier/web/settings.json`. Environment variables remain useful for
deployment, automation, and settings that should take precedence over the UI.

| Variable | Use |
| --- | --- |
| `YIER_AUTH_PASSWORD` | Login password for a managed deployment |
| `YIER_AUTH_PASSWORD_HASH` | Hashed login password instead of plaintext |
| `YIER_AUTH_SECRET` | Session-cookie signing secret |
| `YIER_AUTH_SESSION_TTL_HOURS` | Login duration, defaulting to 168 hours |
| `YIER_CODEX_EMBED_TOKEN` | Token for unauthenticated iframe embedding |
| `YIER_SHERPA_ONNX_MODEL_DIR` | Local speech model directory |
| `YIER_SHERPA_ONNX_PROVIDER` | sherpa-onnx execution provider |
| `YIER_SHERPA_ONNX_NUM_THREADS` | Speech decoder thread count |

`daemon install` preserves the relevant `YIER_*` variables, `HOME`, `PATH`,
and `CODEX_HOME` in its user-only environment file. See [IFRAME.md](./IFRAME.md)
for iframe authentication, setup, and the `postMessage` API.

## Development

Source development requires Python 3.12+, Node.js 20+, `uv`, and `pnpm`:

```bash
uv sync
pnpm --dir web install
```

Start the frontend and backend in separate terminals:

```bash
pnpm --dir web dev
uv run python main.py --debug --reload --host 127.0.0.1 --port 13140
```

Useful checks:

```bash
uv run --all-packages pytest
pnpm --dir web test:unit
pnpm --dir web type-check
pnpm --dir web build
```

Codex integration is provided by the published
[`open-codex-bridge`](https://pypi.org/project/open-codex-bridge/) package.

## License

Copyright 2026 Sube (zhangluguang). Licensed under the
[PolyForm Noncommercial License 1.0.0](./LICENSE). Commercial use is not
permitted without separate written authorization from the copyright holder.
