# AGENTS.md

## Repo Conventions

- Python string formatting should prefer f-strings.
- Use `Path` for filesystem operations instead of raw string paths where practical.
- Commit messages must be written in English.
- Commit messages must not mention Codex, Claude, or collaboration tooling.

## Environment

- This repo uses `uv`, not a manually managed virtualenv workflow.
- Python dependencies are resolved from `pyproject.toml`.
- Use `uv run ...` for Python commands.
- Do not assume `python` is available on `$PATH`; in this environment `uv run python ...` is the reliable path.
- Frontend commands run from `web` and use `pnpm`.

## Common Commands

- Backend tests:
  `uv run --all-packages pytest`
- Python compile sanity check:
  `uv run python -m compileall yier_web`
- Frontend unit tests:
  `cd web && pnpm test:unit`
- Frontend type-check:
  `cd web && pnpm type-check`
- Frontend production build:
  `cd web && pnpm build`

## Workspace Layout

- Main backend app code lives in `yier_web`.
- Frontend app code lives in `web/src`.

## Architecture Conventions

- Prefer appropriate design patterns when they make behavior clearer or reduce conditional complexity, especially for command dispatch, state transitions, adapters, factories, strategies, and cross-boundary integrations.
- Keep modules highly cohesive and loosely coupled across both backend and frontend code. A module should own one clear responsibility and expose narrow interfaces.
- Split growing files into focused modules instead of accumulating unrelated concerns in one place. This applies to Python services/routes/managers and Vue composables/components/views alike.
- Keep each source file under roughly 500 lines where practical. If a file approaches that size, look for a natural boundary to extract before adding more behavior.

## Frontend Conventions

- Use tailwindcss for styling.
- Frontend structure should prefer module-based splitting:
  - page-level or workspace-level UI should live in a `views` layer
  - module-specific subparts should stay close to that module
  - truly reusable UI pieces should go into [`web/src/components`](/Users/sube/me/yier/web/src/components)
- Do not treat `components` as the default destination for every new Vue file. Shared pieces go to `components`; feature and page composition should be split by module.
- If a piece of UI state has long-term product meaning, persist it through the backend config surface when appropriate instead of leaving it only in local component state.
- If a piece of UI state affects first paint or workspace routing, do not rely only on async `/api/config` hydration plus a hardcoded default. Provide a boot-safe strategy such as:
  - a loading guard that avoids rendering the wrong surface before hydration
  - or a small local bootstrap cache that is reconciled after config loads
- When using local bootstrap cache for UX, keep the backend config as the durable source of truth and treat the cache only as a first-paint hint.

## Codex IPC Notes

- Codex behavior is implemented through the published `open-codex-bridge` package.
- The standalone Codex workspace is served from `/codex` and `/api/codex/ws`.
- Codex thread state and commands belong in
  [`yier_web/codex/ipc_manager.py`](/Users/sube/me/yier/yier_web/codex/ipc_manager.py)
  and [`yier_web/routes/codex.py`](/Users/sube/me/yier/yier_web/routes/codex.py).
- Keep one `CodexIpcSession` per active Codex thread so UI subscription changes
  do not stop running turns.
- When changing Codex behavior, update manager/controller tests in
  [`tests/test_codex_ipc_manager.py`](/Users/sube/me/yier/tests/test_codex_ipc_manager.py)
  and frontend tests under [`web/src/codex`](/Users/sube/me/yier/web/src/codex).
