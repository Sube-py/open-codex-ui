# Open Codex UI npm launcher

Run the packaged Open Codex UI application through Node.js:

```bash
npx open-codex-ui
npx open-codex-ui serve --host 0.0.0.0 --port 13140
npx open-codex-ui daemon install
npx open-codex-ui update
```

This package is a small launcher, not a second implementation. It forwards all
arguments to the matching Python release through `uvx`. If `uvx` is not already
available, the launcher downloads and runs the official installer from
[`astral.sh/uv`](https://astral.sh/uv/) and keeps the binaries in its own cache
directory without changing the user's `PATH`.

Set `OPEN_CODEX_UI_UVX` to use a specific `uvx` executable, or
`OPEN_CODEX_UI_UV_DIR` to override the private installation directory.

The application source, documentation, and issue tracker are in the
[Open Codex UI repository](https://github.com/Sube-py/open-codex-ui).

## License

Licensed under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/).

Required Notice: Copyright 2026 Sube (zhangluguang).

Required Notice: Commercial use requires separate written permission from the copyright holder.
