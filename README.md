<p align="center">
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/brand/open-codex-ui-logo.svg" alt="Open Codex UI" width="520">
</p>

# Open Codex UI

A remote-friendly web workspace for continuing Codex sessions from desktop and
mobile browsers.

> [!IMPORTANT]
> **Non-commercial use only.** This project is provided solely for learning,
> research, personal use, and other non-commercial purposes. Commercial use
> requires prior written permission from the copyright holder.

## Preview

<p align="center">
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/screenshots/open-codex-ui-desktop.png" alt="Open Codex UI desktop workspace">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/screenshots/open-codex-ui-mobile-chat.png" alt="Open Codex UI mobile chat" width="300">
  &nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/Sube-py/open-codex-ui/main/web/public/screenshots/open-codex-ui-mobile-projects.png" alt="Open Codex UI mobile project drawer" width="300">
</p>

## Quick Start

Run the packaged application through Node.js:

```bash
npx open-codex-ui
```

The npm launcher reuses an existing `uvx`, or installs `uv` from Astral's
official installer into its own cache. You can also run the Python package
directly with [`uv`](https://docs.astral.sh/uv/):

```bash
uvx open-codex-ui
```

Open `http://127.0.0.1:13140` on the local machine. The wheel already contains
the compiled frontend. The server listens on `0.0.0.0` by default so it can be
reached from other devices on the network. To restrict it to the local machine:

```bash
uvx open-codex-ui serve --host 127.0.0.1 --port 13140
```

Codex WebSocket subscriptions use turn, item, and streaming-text deltas,
latest-state coalescing, and negotiated gzip binary frames for larger messages.
Clients that do not request gzip continue to receive regular JSON frames.

## Background Service

Install the command persistently and register login startup:

```bash
npx open-codex-ui daemon install
# or
uvx open-codex-ui daemon install
```

This installs `open-codex-ui` into uv's user bin directory and uses the native
service manager for the current platform. The background service listens on
`0.0.0.0` by default so it can be reached from other devices on the network.
Use `--host 127.0.0.1` to restrict it to the local machine.

| Platform | Service                                 |
| -------- | --------------------------------------- |
| macOS    | LaunchAgent in `~/Library/LaunchAgents` |
| Linux    | `systemd --user` service                |
| Windows  | Current-user Task Scheduler task        |

After opening a new shell, manage the service directly:

```bash
open-codex-ui daemon status
open-codex-ui daemon stop
open-codex-ui daemon start
open-codex-ui daemon uninstall
```

The service starts when the user logs in. Runtime state, retained environment,
and logs live under `~/.yier/web/`. Run `daemon install` again to update its
host, port, or captured environment; use `update` for application versions.

## Cloudflare Tunnel

Start Open Codex UI first, then expose the default local address with an
ephemeral Quick Tunnel:

```bash
open-codex-ui tunnel start
open-codex-ui tunnel status
open-codex-ui tunnel stop
```

For a tunnel already configured in the Cloudflare dashboard, provide an API
token that can read the account's tunnel configuration and connector token:

```bash
export CF_TOKEN='your-cloudflare-api-token'
open-codex-ui tunnel start --mode managed-remote --name my-tunnel
```

The named-tunnel flow discovers its public hostname and local origin from
Cloudflare. Set `CF_ACCOUNT_ID` or pass `--account-id` when account discovery
is unavailable. You can bypass the API with an existing connector token file:

```bash
open-codex-ui tunnel start --mode managed-remote \
  --token-file ~/.cloudflared/my-tunnel.token \
  --hostname codex.example.com
```

Locally managed cloudflared configurations are also supported:

```bash
open-codex-ui tunnel start --mode managed-local
open-codex-ui tunnel start --mode managed-local --config ~/.cloudflared/config.yml
```

Tunnel state and logs are stored under `~/.yier/web/`. API and connector tokens
are never persisted there or included in the cloudflared command line. Tunnel
processes are independent from the login service, and `tunnel stop` only stops
the cloudflared process started by Open Codex UI.

> [!WARNING]
> A tunnel exposes Open Codex UI to the public Internet. Configure application
> authentication or Cloudflare Access before sharing the public URL.

## Updating

Update a persistent installation to the latest stable release:

```bash
open-codex-ui update
# or
npx open-codex-ui update
```

If the login service is running, it is restarted after the update. Plain
`uvx` and `npx` runs resolve their release when launched, so the command makes
no persistent changes when no uv tool installation exists.

## Authentication

Authentication is disabled unless a password variable is configured:

```bash
export YIER_AUTH_PASSWORD='change-this-password'
uvx open-codex-ui daemon install --host 0.0.0.0
```

For a hashed password:

```bash
uv run --with open-codex-ui python -c "from yier_web.auth import hash_password; print(hash_password('change-this-password'))"
export YIER_AUTH_PASSWORD_HASH='paste-generated-hash-here'
```

| Variable                      | Purpose                                   |
| ----------------------------- | ----------------------------------------- |
| `YIER_AUTH_PASSWORD`          | Plain login password                      |
| `YIER_AUTH_PASSWORD_HASH`     | Hashed login password                     |
| `YIER_AUTH_SECRET`            | Additional session-cookie signing secret  |
| `YIER_AUTH_SESSION_TTL_HOURS` | Session lifetime; defaults to `168` hours |
| `YIER_CODEX_EMBED_TOKEN`      | Token for unauthenticated iframe access   |

`daemon install` retains `HOME`, `PATH`, `CODEX_HOME`, and current `YIER_*`
variables in a user-only environment file so they remain available after login.

## Voice Input

The Codex composer can stream microphone audio to a local sherpa-onnx
transducer model. The default model directory is
`~/.yier/models/sherpa-onnx`. A bilingual Chinese-English streaming Zipformer
can be installed with:

```bash
open-codex-ui speech install
```

The installer supports interrupted-download resumption, verifies the archive,
extracts it safely, and atomically activates the model. Standard `HTTPS_PROXY`
and `ALL_PROXY` environment variables are honored:

```bash
HTTPS_PROXY=http://127.0.0.1:7890 open-codex-ui speech install
open-codex-ui speech status
open-codex-ui speech install --force
open-codex-ui speech remove
```

The model is stored outside the Python environment, so it remains available
after `uv tool` upgrades or reinstalls. The directory must contain
`tokens.txt`, `encoder*.onnx`, `decoder*.onnx`, and `joiner*.onnx`.

Override the runtime configuration when needed:

| Variable                        | Purpose                                      |
| ------------------------------- | -------------------------------------------- |
| `YIER_SHERPA_ONNX_MODEL_DIR`    | Streaming transducer model directory         |
| `YIER_SHERPA_ONNX_PROVIDER`     | sherpa-onnx execution provider; default `cpu` |
| `YIER_SHERPA_ONNX_NUM_THREADS`  | Decoder threads; default `2`                 |

Model directory, execution provider, and decoder thread count can also be
managed from **Settings → Voice**. They are persisted in
`~/.yier/web/settings.json`; the environment variables above take precedence
over the corresponding saved values.

Remote mobile browsers require HTTPS for microphone permission. Localhost is
also treated as a secure context by modern browsers.

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

The application remains at `http://127.0.0.1:13140`; the backend proxies
frontend traffic to the Vite server on port `5173`.

| Command                                | Purpose                                                     |
| -------------------------------------- | ----------------------------------------------------------- |
| `pnpm --dir web dev`                   | Start Vite                                                  |
| `uv run python main.py --debug --reload` | Start the development backend                             |
| `pnpm --dir web build`                 | Type-check and build frontend assets into `yier_web/static` |
| `uv run open-codex-ui`                 | Run the source checkout in production mode                  |
| `uv run pytest`                        | Run backend tests                                           |
| `uv run python -m compileall yier_web` | Check Python compilation                                    |
| `pnpm --dir web test:unit`             | Run frontend unit tests                                     |
| `pnpm --dir web type-check`            | Run frontend type checking                                  |

To test the production build from source:

```bash
pnpm --dir web build
uv run open-codex-ui
```

Codex integration is provided by the published
[`open-codex-bridge`](https://pypi.org/project/open-codex-bridge/) package.

## Iframe Embedding

See [IFRAME.md](./IFRAME.md) for iframe authentication, setup, and the
`postMessage` API.

## License

Copyright 2026 Sube (zhangluguang). Licensed under the
[PolyForm Noncommercial License 1.0.0](./LICENSE). Commercial use is not
permitted without separate written authorization from the copyright holder.
