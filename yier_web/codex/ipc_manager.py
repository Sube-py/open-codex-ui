from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import shlex
import tomllib
from typing import Callable

from codex_bridge import (
    AppServerConfig,
    CodexIpcConfig,
    CodexIpcSession,
    JsonDict,
    SshConnectionConfig,
    SshWebsocketAppServerConfig,
    materialize_conversation_state,
)
from openai_codex.generated.v2_all import (
    AbsolutePathBuf,
    ActiveThreadStatus,
    CustomSessionSource,
    IdleThreadStatus,
    NotLoadedThreadStatus,
    SessionSource,
    SessionSourceValue,
    SkillsListResponse,
    SubAgentSessionSource,
    SystemErrorThreadStatus,
    Thread,
    ThreadListResponse,
    ThreadStatus,
)
from yier_web.config import AppConfigService
from yier_web.codex.session_events import (
    CodexSessionEvent,
    CodexSessionEventHub,
    CodexSessionEventQueue,
    CodexSessionEventProjector,
    CodexSessionEventSink,
    Unsubscribe,
)
from yier_web.codex.turn_sync import TurnEventProjector
from yier_web.event_stream import EventStreamBroker
from yier_web.schemas import (
    CodexFilesystemEntry,
    CodexFilesystemResponse,
    CodexNativeSessionSummary,
    CodexProjectGroup,
    CodexRecentThreadsPage,
    CodexRemoteConnection,
    CodexRemoteConnectionStatus,
    CodexRemoteConnectionTestResponse,
    CodexRemoteConnectionsResponse,
    CodexWorkspaceResponse,
    StoredCodexSettings,
)

logger = logging.getLogger(__name__)
CODEX_POSIX_INSTALL_URL = "https://chatgpt.com/codex/install.sh"
CODEX_CONFIG_FILE = "config.toml"
CODEX_PROJECT_THREAD_PAGE_SIZE = 100
CODEX_RECENT_THREAD_PAGE_SIZE = 20

CodexSubscriberQueue = CodexSessionEventQueue
CodexSessionFactory = Callable[..., CodexIpcSession]


@dataclass(slots=True)
class ManagedCodexThread:
    session: CodexIpcSession
    watcher_task: asyncio.Task[None]
    event_watcher_task: asyncio.Task[None] | None = None
    state: JsonDict | None = None


@dataclass(slots=True)
class WorkspaceHostThreads:
    projects: ThreadListResponse
    recents: ThreadListResponse
    recent_next_cursor: str | None = None


def _compact_text(value: object, *, limit: int = 72) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return ""
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 3]}..."


def _thread_status(status: ThreadStatus) -> str:
    match status.root:
        case NotLoadedThreadStatus(type=status_type):
            return status_type
        case IdleThreadStatus(type=status_type):
            return status_type
        case SystemErrorThreadStatus(type=status_type):
            return status_type
        case ActiveThreadStatus(type=status_type):
            return status_type


def _thread_source(source: SessionSource) -> str:
    match source.root:
        case SessionSourceValue() as source_value:
            return source_value.value
        case CustomSessionSource(custom=custom):
            return custom
        case SubAgentSessionSource():
            return "subAgent"


def _project_from_cwd(cwd: AbsolutePathBuf) -> tuple[str, str]:
    path = Path(cwd.root).expanduser()
    project = path.name or cwd.root
    return (project, str(path))


def _summary_used_at(summary: CodexNativeSessionSummary) -> float:
    return summary.updated_at or summary.started_at


def _codex_home(home_dir: Path | None = None) -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return (home_dir or Path.home()).expanduser() / ".codex"


def _load_codex_home_config(codex_home: Path) -> JsonDict:
    config_path = codex_home / CODEX_CONFIG_FILE
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        logger.warning("Unable to parse %s: %s", config_path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _config_string(config: JsonDict, key: str) -> str | None:
    value = config.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _thread_summary(
    thread: Thread, *, host_id: str = "local"
) -> CodexNativeSessionSummary:
    cwd = thread.cwd.root
    project, project_path = _project_from_cwd(thread.cwd)
    if host_id == "local":
        project_path = str(Path(project_path).resolve())
    name = _compact_text(thread.name)
    preview = _compact_text(thread.preview, limit=120)
    title = name or preview or thread.id
    return CodexNativeSessionSummary(
        thread_id=thread.id,
        host_id=host_id,
        title=title,
        preview=preview or title,
        updated_at=float(thread.updated_at),
        started_at=float(thread.created_at),
        status=_thread_status(thread.status),
        cwd=cwd,
        project=project,
        project_path=project_path,
        source=_thread_source(thread.source),
        model_provider=thread.model_provider,
    )


class CodexIpcManager:
    """Owns long-lived Codex IPC sessions for the web workspace.

    The manager keeps one ``CodexIpcSession`` per active thread so UI subscription
    changes do not interrupt ongoing turns.
    """

    def __init__(
        self,
        *,
        config_service: AppConfigService,
        event_broker: EventStreamBroker,
        session_factory: CodexSessionFactory = CodexIpcSession,
    ) -> None:
        self.config_service = config_service
        self.event_broker = event_broker
        self._session_factory = session_factory
        self._threads: dict[str, ManagedCodexThread] = {}
        self._thread_hosts: dict[str, str] = {}
        self._session_events = CodexSessionEventHub()
        self._session_events.add_sink(self._publish_session_event_to_broker)
        self._workspace_sessions: dict[str, CodexIpcSession] = {}
        self._remote_connection_statuses: dict[str, CodexRemoteConnectionStatus] = {}
        self._lock = asyncio.Lock()
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False
        for managed in list(self._threads.values()):
            self._cancel_managed_watchers(managed)
        for managed in list(self._threads.values()):
            await self._wait_managed_watchers(managed)
            await managed.session.stop()
        self._threads.clear()
        self._session_events.clear_thread_subscribers()

        for session in list(self._workspace_sessions.values()):
            await session.stop()
        self._workspace_sessions.clear()

    async def workspace(self) -> CodexWorkspaceResponse:
        settings = self.config_service.load_web_settings().codex
        host_ids = [
            "local",
            *(
                self._host_id_for_connection(connection.id)
                for connection in settings.remote_connections
                if connection.auto_connect
            ),
        ]
        project_paths_by_host = {
            host_id: list(
                dict.fromkeys(
                    root_path
                    for project in settings.projects
                    if project.host_id == host_id
                    for root_path in project.root_paths
                )
            )
            for host_id in host_ids
        }
        projectless_thread_ids = set(settings.projectless_thread_ids)
        results = await asyncio.gather(
            *(
                self._list_workspace_host(
                    host_id,
                    project_paths=project_paths_by_host[host_id],
                    projectless_thread_ids=projectless_thread_ids,
                )
                for host_id in host_ids
            ),
            return_exceptions=True,
        )
        summaries: list[CodexNativeSessionSummary] = []
        recent_threads_next_cursors: dict[str, str] = {}
        for host_id, result in zip(host_ids, results, strict=True):
            connection_id = self._connection_id_from_host(host_id)
            if isinstance(result, BaseException):
                if connection_id:
                    self._set_remote_connection_status(
                        connection_id,
                        "error",
                        _compact_text(str(result), limit=180)
                        or result.__class__.__name__,
                    )
                else:
                    logger.warning("Unable to list local Codex threads: %s", result)
                continue
            if connection_id:
                self._set_remote_connection_status(
                    connection_id,
                    "connected",
                    "Connected",
                )
            summaries.extend(
                self._summaries_from_threads(result.projects, host_id=host_id)
            )
            summaries.extend(
                self._summaries_from_threads(result.recents, host_id=host_id)
            )
            if result.recent_next_cursor:
                recent_threads_next_cursors[host_id] = result.recent_next_cursor

        workspace = self._workspace_from_summaries(summaries, settings=settings)
        workspace.recent_threads_next_cursors = recent_threads_next_cursors
        remote = self.remote_connections()
        workspace.remote_connections = remote.connections
        workspace.active_remote_connection_id = remote.active_connection_id
        workspace.remote_connection_statuses = remote.statuses
        return workspace

    async def _list_workspace_host(
        self,
        host_id: str,
        *,
        project_paths: list[str],
        projectless_thread_ids: set[str],
    ) -> WorkspaceHostThreads:
        try:
            projects = (
                await asyncio.wait_for(
                    self.list_threads(host_id, cwd=project_paths), timeout=5
                )
                if project_paths
                else ThreadListResponse(data=[])
            )
            recents, next_cursor = await asyncio.wait_for(
                self._list_recent_threads_host(
                    host_id,
                    projectless_thread_ids=projectless_thread_ids,
                ),
                timeout=5,
            )
            return WorkspaceHostThreads(
                projects=projects,
                recents=recents,
                recent_next_cursor=next_cursor,
            )
        except Exception:
            await self._close_workspace_session(host_id)
            raise

    async def list_recent_threads(
        self,
        cursors: dict[str, str],
    ) -> CodexRecentThreadsPage:
        settings = self.config_service.load_web_settings().codex
        available_host_ids = {
            "local",
            *(
                self._host_id_for_connection(connection.id)
                for connection in settings.remote_connections
                if connection.auto_connect
            ),
        }
        requested_cursors = {
            host_id: cursor
            for host_id, cursor in cursors.items()
            if host_id in available_host_ids and cursor
        }
        results = await asyncio.gather(
            *(
                self._list_recent_threads_host(
                    host_id,
                    cursor=cursor,
                    projectless_thread_ids=set(settings.projectless_thread_ids),
                )
                for host_id, cursor in requested_cursors.items()
            ),
            return_exceptions=True,
        )
        threads: list[CodexNativeSessionSummary] = []
        next_cursors: dict[str, str] = {}
        for (host_id, cursor), result in zip(
            requested_cursors.items(), results, strict=True
        ):
            if isinstance(result, BaseException):
                await self._close_workspace_session(host_id)
                next_cursors[host_id] = cursor
                logger.warning(
                    "Unable to list recent Codex threads for %s: %s",
                    host_id,
                    result,
                )
                continue
            response, next_cursor = result
            threads.extend(self._summaries_from_threads(response, host_id=host_id))
            if next_cursor:
                next_cursors[host_id] = next_cursor
        threads.sort(
            key=lambda item: (
                _summary_used_at(item),
                item.started_at,
                item.thread_id,
            ),
            reverse=True,
        )
        return CodexRecentThreadsPage(threads=threads, next_cursors=next_cursors)

    def remote_connections(self) -> CodexRemoteConnectionsResponse:
        settings = self.config_service.load_web_settings().codex
        return CodexRemoteConnectionsResponse(
            connections=settings.remote_connections,
            active_connection_id=settings.active_remote_connection_id,
            statuses=self._remote_statuses_for(settings),
        )

    async def activate_remote_connection(self, connection_id: str) -> None:
        self.config_service.set_active_codex_remote_connection(connection_id)

    async def set_remote_connection_auto_connect(
        self,
        connection_id: str,
        *,
        auto_connect: bool,
    ) -> CodexRemoteConnection:
        connection = self.config_service.set_codex_remote_connection_auto_connect(
            connection_id,
            auto_connect,
        )
        host_id = self._host_id_for_connection(connection_id)
        await self._restart_host_sessions(host_id)
        if auto_connect:
            self._set_remote_connection_status(
                connection_id,
                "connecting",
                "Connecting",
            )
        else:
            self._set_remote_connection_status(
                connection_id,
                "disconnected",
                "Automatic connection is off",
            )
        return connection

    async def restart_remote_connection(self, connection_id: str) -> None:
        if self._remote_connection_by_id(connection_id) is None:
            raise ValueError("Remote connection not found.")
        self._set_remote_connection_status(
            connection_id,
            "connecting",
            "Restarting connection",
        )
        await self._restart_host_sessions(self._host_id_for_connection(connection_id))

    async def disconnect_remote_connection(self, connection_id: str) -> None:
        await self._restart_host_sessions(self._host_id_for_connection(connection_id))
        self._remote_connection_statuses.pop(connection_id, None)

    async def install_remote_codex(
        self,
        connection_id: str,
    ) -> CodexRemoteConnectionTestResponse:
        connection = self._remote_connection_by_id(connection_id)
        if connection is None:
            raise ValueError("Remote connection not found.")
        self._set_remote_connection_status(
            connection_id, "connecting", "Installing Codex"
        )
        install_script = (
            "if command -v curl >/dev/null 2>&1; then "
            f'installer_script="$(curl -fsSL {CODEX_POSIX_INSTALL_URL})" || exit; '
            "elif command -v wget >/dev/null 2>&1; then "
            f'installer_script="$(wget -qO- {CODEX_POSIX_INSTALL_URL})" || exit; '
            "else echo 'curl or wget is required to install Codex' >&2; exit 127; fi; "
            "printf '%s\\n' \"$installer_script\" | "
            "CODEX_RELEASE=latest CODEX_NON_INTERACTIVE=1 sh"
        )
        process = await asyncio.create_subprocess_exec(
            *self._ssh_base_args(connection),
            self._remote_login_shell_command(install_script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            detail = "Remote Codex install timed out."
            self._set_remote_connection_status(connection_id, "error", detail)
            return CodexRemoteConnectionTestResponse(ok=False, detail=detail)
        detail = "\n".join(
            item.decode("utf-8", errors="replace").strip()
            for item in (stdout, stderr)
            if item
        ).strip()
        ok = process.returncode == 0
        if ok:
            await self.restart_remote_connection(connection_id)
        else:
            self._set_remote_connection_status(
                connection_id,
                "error",
                detail or f"Install exited with code {process.returncode}.",
            )
        return CodexRemoteConnectionTestResponse(
            ok=ok,
            detail=detail or ("Codex installed." if ok else "Codex install failed."),
        )

    async def test_remote_connection(
        self,
        connection_id: str,
    ) -> CodexRemoteConnectionTestResponse:
        connection = self._remote_connection_by_id(connection_id)
        if connection is None:
            raise ValueError("Remote connection not found.")
        self._set_remote_connection_status(connection_id, "connecting", "Checking")
        args = self._ssh_base_args(connection)
        script = "command -v codex >/dev/null 2>&1 && codex --version"
        process = await asyncio.create_subprocess_exec(
            *args,
            self._remote_login_shell_command(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=12)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            self._set_remote_connection_status(
                connection_id,
                "error",
                "SSH connection timed out.",
            )
            return CodexRemoteConnectionTestResponse(
                ok=False,
                detail="SSH connection timed out.",
            )
        output = "\n".join(
            item.decode("utf-8", errors="replace").strip()
            for item in (stdout, stderr)
            if item
        ).strip()
        ok = process.returncode == 0
        detail = output or (
            "Codex is available on the remote host."
            if ok
            else f"SSH exited with code {process.returncode}."
        )
        self._set_remote_connection_status(
            connection_id,
            "connected" if ok else "error",
            detail,
        )
        return CodexRemoteConnectionTestResponse(ok=ok, detail=detail)

    async def list_threads(
        self,
        host_id: str = "local",
        *,
        cwd: str | list[str] | None = None,
    ) -> ThreadListResponse:
        session = await self._ensure_workspace_session(host_id)
        threads: list[Thread] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: JsonDict = {
                "archived": False,
                "limit": CODEX_PROJECT_THREAD_PAGE_SIZE,
                "sort_key": "updated_at",
                "sort_direction": "desc",
            }
            if cwd:
                params["cwd"] = cwd
            if cursor:
                params["cursor"] = cursor
            response = await session.list_threads(params)
            threads.extend(response.data)
            next_cursor = response.next_cursor
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return ThreadListResponse(data=threads)

    async def _list_recent_threads_host(
        self,
        host_id: str,
        *,
        projectless_thread_ids: set[str],
        cursor: str | None = None,
    ) -> tuple[ThreadListResponse, str | None]:
        session = await self._ensure_workspace_session(host_id)
        threads: list[Thread] = []
        current_cursor = cursor
        seen_cursors = {cursor} if cursor else set()
        while len(threads) < CODEX_RECENT_THREAD_PAGE_SIZE:
            params: JsonDict = {
                "archived": False,
                "limit": CODEX_RECENT_THREAD_PAGE_SIZE - len(threads),
                "sort_key": "updated_at",
                "sort_direction": "desc",
            }
            if current_cursor:
                params["cursor"] = current_cursor
            response = await session.list_threads(params)
            threads.extend(
                thread
                for thread in response.data
                if not thread.ephemeral and thread.id in projectless_thread_ids
            )
            next_cursor = response.next_cursor
            if not next_cursor or next_cursor in seen_cursors:
                return ThreadListResponse(data=threads), None
            if len(threads) >= CODEX_RECENT_THREAD_PAGE_SIZE:
                return ThreadListResponse(data=threads), next_cursor
            seen_cursors.add(next_cursor)
            current_cursor = next_cursor
        return ThreadListResponse(data=threads), current_cursor

    async def list_filesystem(
        self,
        *,
        host_id: str,
        path: str | None = None,
    ) -> CodexFilesystemResponse:
        resolved_host_id = self._resolve_host_id(host_id)
        connection = self._connection_for_host(resolved_host_id)
        if connection is None:
            raise ValueError("A remote host is required.")

        requested_path = path or "~"
        script = """
import json
import os
import pathlib
import sys

directory = pathlib.Path(sys.argv[1]).expanduser().resolve()
if not directory.exists():
    raise FileNotFoundError(f"Path not found: {directory}")
if not directory.is_dir():
    raise NotADirectoryError(f"Path is not a directory: {directory}")

entries = []
for child in directory.iterdir():
    try:
        kind = "directory" if child.is_dir() else "file" if child.is_file() else "other"
        readable = os.access(child, os.R_OK)
    except OSError:
        kind = "other"
        readable = False
    entries.append({
        "name": child.name,
        "path": str(child),
        "kind": kind,
        "extension": child.suffix.lower() if kind == "file" else "",
        "readable": readable,
    })
entries.sort(key=lambda item: (
    0 if item["kind"] == "directory" else 1 if item["kind"] == "file" else 2,
    item["name"].casefold(),
))
print(json.dumps({
    "path": str(directory),
    "parent_path": None if directory.parent == directory else str(directory.parent),
    "entries": entries,
}))
""".strip()
        command = f"python3 -c {shlex.quote(script)} {shlex.quote(requested_path)}"
        process = await asyncio.create_subprocess_exec(
            *self._ssh_base_args(connection, verbose=False),
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=12)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("Timed out while browsing the remote host.") from None
        if process.returncode != 0:
            detail = _compact_text(stderr.decode(errors="replace"), limit=240)
            raise RuntimeError(detail or "Unable to browse the remote host.")
        try:
            payload = json.loads(stdout.decode())
            entries = [
                CodexFilesystemEntry.model_validate(item) for item in payload["entries"]
            ]
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "The remote host returned an invalid directory listing."
            ) from exc
        return CodexFilesystemResponse(
            path=str(payload.get("path") or requested_path),
            parent_path=payload.get("parent_path"),
            roots=[
                CodexFilesystemEntry(
                    name="/",
                    path="/",
                    kind="directory",
                    readable=True,
                )
            ],
            entries=entries,
        )

    async def list_skills(
        self,
        *,
        thread_id: str | None = None,
        host_id: str | None = None,
        cwd: str | None = None,
        force_reload: bool = False,
    ) -> list[JsonDict]:
        session: CodexIpcSession
        resolved_cwd = cwd.strip() if isinstance(cwd, str) and cwd.strip() else ""
        if thread_id:
            managed = await self._ensure_thread(thread_id, host_id=host_id)
            session = managed.session
            if not resolved_cwd:
                state = managed.state or managed.session.state
                state_cwd = state.get("cwd") if isinstance(state, dict) else None
                if isinstance(state_cwd, str) and state_cwd.strip():
                    resolved_cwd = state_cwd.strip()
        else:
            session = await self._ensure_workspace_session(host_id or "local")

        codex = await session._ensure_codex()
        params: JsonDict = {}
        if resolved_cwd:
            params["cwds"] = [resolved_cwd]
        if force_reload:
            params["forceReload"] = True
        response = await codex._client.request(
            "skills/list",
            params or None,
            response_model=SkillsListResponse,
        )
        return self._flatten_skills_response(response)

    async def start_thread(
        self,
        *,
        project_path: str | None = None,
        host_id: str = "local",
    ) -> JsonDict:
        resolved_host_id = self._resolve_host_id(host_id)
        params = self._thread_start_params(
            project_path=project_path,
            host_id=resolved_host_id,
        )
        session = self._new_session(self._config(host_id=resolved_host_id))
        await session.start()
        try:
            await session.start_new_thread(params)
            thread_id = session.thread_id
            if not thread_id:
                raise RuntimeError("Codex did not return a thread id.")
            await self._register_session(thread_id, session)
            try:
                self.config_service.assign_codex_thread_project(
                    thread_id,
                    host_id=resolved_host_id,
                    cwd=str(params.get("cwd") or ""),
                )
            except OSError as exc:
                logger.warning("Unable to persist project assignment: %s", exc)
        except Exception:
            await session.stop()
            raise
        return {
            "thread_id": thread_id,
            "host_id": resolved_host_id,
            "state": self._state_with_host_id(session.state, resolved_host_id),
        }

    async def open_thread(
        self,
        thread_id: str,
        *,
        host_id: str | None = None,
    ) -> JsonDict:
        managed = await self._ensure_thread(thread_id, host_id=host_id)
        return {
            "thread_id": managed.session.thread_id,
            "state": self._state_with_host_id(
                managed.state or managed.session.state,
                managed.session.config.host_id,
            ),
        }

    async def get_thread_state(
        self,
        thread_id: str,
        *,
        host_id: str | None = None,
    ) -> JsonDict | None:
        managed = await self._ensure_thread(thread_id, host_id=host_id)
        return self._state_with_host_id(
            managed.state or managed.session.state,
            managed.session.config.host_id,
        )

    def add_session_event_sink(self, sink: CodexSessionEventSink) -> Unsubscribe:
        return self._session_events.add_sink(sink)

    async def subscribe(
        self,
        thread_id: str,
        queue: CodexSubscriberQueue,
        *,
        host_id: str | None = None,
        projector: CodexSessionEventProjector | None = None,
        replay: bool = True,
    ) -> JsonDict | None:
        first_subscription = self._session_events.subscribe_thread(
            thread_id,
            queue,
            projector=projector,
        )
        try:
            managed = await self._ensure_thread(
                thread_id,
                host_id=host_id,
                following=first_subscription,
            )
        except Exception:
            self._session_events.unsubscribe_thread(thread_id, queue)
            raise
        state = self._state_with_host_id(
            managed.state or managed.session.state,
            managed.session.config.host_id,
        )
        if replay:
            replay_events = (
                self._legacy_thread_event(
                    "thread_snapshot",
                    thread_id,
                    state=state,
                    session=managed.session,
                ),
                self._session_state_event(
                    thread_id,
                    state,
                    session=managed.session,
                ),
            )
            for event in replay_events:
                projected = projector(event) if projector is not None else event
                if projected is not None:
                    queue.put_nowait(projected)
        return state

    async def subscribe_with_turn_deltas(
        self,
        thread_id: str,
        queue: CodexSubscriberQueue,
        *,
        cached_turn_ids: list[str],
        refresh_turn_ids: list[str],
        host_id: str | None = None,
    ) -> JsonDict:
        projector = TurnEventProjector(
            cached_turn_ids,
            refresh_turn_ids,
        )
        state = await self.subscribe(
            thread_id,
            queue,
            host_id=host_id,
            projector=projector,
            replay=False,
        )
        managed = self._threads[thread_id]
        return projector.thread_payload(
            thread_id=thread_id,
            state=state,
            stream_role=managed.session.stream_role,
            queued_followups=managed.session.queued_followups,
        )

    async def unsubscribe(
        self,
        thread_id: str,
        queue: CodexSubscriberQueue,
    ) -> None:
        last_subscription = self._session_events.unsubscribe_thread(thread_id, queue)
        managed = self._threads.get(thread_id)
        if last_subscription and managed is not None:
            try:
                await managed.session.set_following(False)
            except Exception as exc:
                logger.warning(
                    "Unable to stop following Codex thread %s: %s",
                    thread_id,
                    exc,
                )

    async def send_prompt(
        self,
        thread_id: str,
        prompt: str,
        *,
        collaboration_mode: JsonDict | None = None,
        attachments: list[JsonDict] | None = None,
        approval_policy: str | None = None,
        approvals_reviewer: str | None = None,
        sandbox_policy: JsonDict | None = None,
    ) -> None:
        managed = await self._ensure_thread(thread_id)
        input_items = self._prompt_input_items(prompt.strip(), attachments or [])
        await managed.session.run_prompt(
            prompt.strip(),
            wait_for_completion=False,
            collaboration_mode=collaboration_mode,
            input_items=input_items if attachments else None,
            approval_policy=approval_policy,
            approvals_reviewer=approvals_reviewer,
            sandbox=sandbox_policy,
        )
        if collaboration_mode is not None:
            await self._apply_latest_collaboration_mode(
                thread_id,
                managed,
                collaboration_mode,
            )

    def _prompt_input_items(
        self,
        prompt: str,
        attachments: list[JsonDict],
    ) -> list[JsonDict]:
        items: list[JsonDict] = [{"type": "text", "text": prompt, "text_elements": []}]
        for attachment in attachments:
            item_type = attachment.get("type")
            if item_type in {"image", "input_image"}:
                image_url = (
                    attachment.get("imageUrl")
                    or attachment.get("image_url")
                    or attachment.get("url")
                    or attachment.get("src")
                )
                if isinstance(image_url, str) and image_url.strip():
                    items.append(
                        {
                            "type": "image",
                            "url": image_url.strip(),
                            "detail": "auto",
                        }
                    )
                continue
            if item_type in {"mention", "file"}:
                path = attachment.get("path") or attachment.get("fsPath")
                name = attachment.get("name") or attachment.get("label")
                if isinstance(path, str) and path.strip():
                    clean_path = path.strip()
                    items.append(
                        {
                            "type": "mention",
                            "name": (
                                name.strip()
                                if isinstance(name, str) and name.strip()
                                else Path(clean_path).name
                            ),
                            "path": clean_path,
                        }
                    )
                continue
            if item_type == "skill":
                path = attachment.get("path") or attachment.get("fsPath")
                name = attachment.get("name") or attachment.get("label")
                if (
                    isinstance(path, str)
                    and path.strip()
                    and isinstance(name, str)
                    and name.strip()
                ):
                    items.append(
                        {
                            "type": "skill",
                            "name": name.strip(),
                            "path": path.strip(),
                        }
                    )
        return items

    async def steer_prompt(self, thread_id: str, prompt: str) -> None:
        managed = await self._ensure_thread(thread_id)
        await managed.session.steer_prompt(prompt.strip())

    async def interrupt_turn(self, thread_id: str, turn_id: str | None = None) -> bool:
        managed = await self._ensure_thread(thread_id)
        return await managed.session.interrupt_turn(turn_id)

    async def compact_thread(self, thread_id: str) -> bool:
        managed = await self._ensure_thread(thread_id)
        return await managed.session.compact_thread()

    async def set_thread_goal(
        self,
        thread_id: str,
        *,
        objective: str | None = None,
        status: str | None = None,
        token_budget: int | None = None,
    ) -> JsonDict:
        managed = await self._ensure_thread(thread_id)
        response = await managed.session.set_thread_goal(
            objective=objective,
            status=status,
            token_budget=token_budget,
        )
        latest_state = managed.session.state
        if isinstance(latest_state, dict):
            managed.state = latest_state
            await self._fanout_thread_state(
                thread_id,
                latest_state,
                session=managed.session,
            )
        return response

    async def get_thread_goal(self, thread_id: str) -> JsonDict | None:
        managed = await self._ensure_thread(thread_id)
        goal = await managed.session.get_thread_goal()
        latest_state = managed.session.state
        if isinstance(latest_state, dict):
            managed.state = latest_state
            await self._fanout_thread_state(
                thread_id,
                latest_state,
                session=managed.session,
            )
        return goal

    async def clear_thread_goal(self, thread_id: str) -> JsonDict:
        managed = await self._ensure_thread(thread_id)
        response = await managed.session.clear_thread_goal()
        latest_state = managed.session.state
        if isinstance(latest_state, dict):
            managed.state = latest_state
            await self._fanout_thread_state(
                thread_id,
                latest_state,
                session=managed.session,
            )
        return response

    async def set_collaboration_mode(
        self,
        thread_id: str,
        collaboration_mode: JsonDict | None,
    ) -> None:
        managed = await self._ensure_thread(thread_id)
        await managed.session.set_collaboration_mode(collaboration_mode)
        await self._apply_latest_collaboration_mode(
            thread_id,
            managed,
            collaboration_mode,
        )

    async def submit_user_input_response(
        self,
        thread_id: str,
        request_id: str,
        response: JsonDict,
    ) -> bool:
        managed = await self._ensure_thread(thread_id)
        return await managed.session.submit_user_input_response(request_id, response)

    async def enqueue_followup(self, thread_id: str, prompt: str) -> JsonDict:
        managed = await self._ensure_thread(thread_id)
        return await managed.session.enqueue_followup(prompt.strip())

    async def remove_followup(self, thread_id: str, message_id: str) -> None:
        managed = await self._ensure_thread(thread_id)
        await managed.session.remove_followup(message_id)

    async def rename_thread(self, thread_id: str, name: str) -> None:
        managed = await self._ensure_thread(thread_id)
        await managed.session.set_thread_name(name.strip(), thread_id)

    async def archive_thread(self, thread_id: str) -> None:
        managed = await self._ensure_thread(thread_id)
        cwd = None
        state = managed.state or managed.session.state
        if isinstance(state, dict) and isinstance(state.get("cwd"), str):
            cwd = state["cwd"]
        await managed.session.archive_thread(thread_id, cwd=cwd)
        await self._broadcast_thread_event("thread_archived", thread_id)
        await self._close_thread(thread_id)

    async def fork_thread(
        self,
        thread_id: str,
        *,
        host_id: str | None = None,
    ) -> JsonDict:
        source_thread_id = thread_id.strip()
        if not source_thread_id:
            raise ValueError("thread_id is required.")

        source = await self._ensure_thread(source_thread_id, host_id=host_id)
        source_host_id = source.session.config.host_id or "local"
        session = self._new_session(
            self._config(
                host_id=source_host_id,
                thread_id=source_thread_id,
            )
        )
        await session.start()
        try:
            await session.fork_thread(source_thread_id)
            forked_thread_id = session.thread_id
            if not forked_thread_id:
                raise RuntimeError("Codex did not return a forked thread id.")
            managed = await self._register_session(forked_thread_id, session)
            try:
                self.config_service.copy_codex_thread_assignment(
                    source_thread_id,
                    forked_thread_id,
                )
            except OSError as exc:
                logger.warning("Unable to persist fork project assignment: %s", exc)
        except Exception:
            await session.stop()
            raise
        return {
            "thread_id": forked_thread_id,
            "host_id": source_host_id,
            "state": self._state_with_host_id(
                managed.state or managed.session.state,
                source_host_id,
            ),
        }

    async def unarchive_thread(
        self,
        thread_id: str,
        *,
        host_id: str | None = None,
    ) -> None:
        resolved_host_id = self._resolve_thread_host(thread_id, host_id)
        session = await self._ensure_workspace_session(resolved_host_id)
        await session.unarchive_thread(thread_id)
        await self._broadcast_thread_event("thread_unarchived", thread_id)

    async def _ensure_workspace_session(self, host_id: str) -> CodexIpcSession:
        resolved_host_id = self._resolve_host_id(host_id)
        existing = self._workspace_sessions.get(resolved_host_id)
        if existing is not None:
            return existing
        session = self._new_session(self._config(host_id=resolved_host_id))
        self._workspace_sessions[resolved_host_id] = session
        try:
            await session.start()
        except Exception:
            self._workspace_sessions.pop(resolved_host_id, None)
            with contextlib.suppress(Exception):
                await session.stop()
            raise
        return session

    async def _close_workspace_session(self, host_id: str) -> None:
        session = self._workspace_sessions.pop(host_id, None)
        if session is not None:
            with contextlib.suppress(Exception):
                await session.stop()

    def _flatten_skills_response(self, response: SkillsListResponse) -> list[JsonDict]:
        skills: list[JsonDict] = []
        seen_paths: set[str] = set()
        for entry in response.data:
            for skill in entry.skills:
                if not skill.enabled:
                    continue
                path = str(
                    skill.path.root if hasattr(skill.path, "root") else skill.path
                )
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)
                interface = (
                    skill.interface.model_dump(mode="json", by_alias=True)
                    if skill.interface is not None
                    else None
                )
                short_description = skill.short_description
                if not short_description and skill.interface is not None:
                    short_description = skill.interface.short_description
                display_name = skill.name
                if skill.interface is not None and skill.interface.display_name:
                    display_name = skill.interface.display_name
                skills.append(
                    {
                        "name": skill.name,
                        "display_name": display_name,
                        "description": skill.description,
                        "short_description": short_description,
                        "path": path,
                        "scope": skill.scope.value
                        if hasattr(skill.scope, "value")
                        else str(skill.scope),
                        "enabled": skill.enabled,
                        "interface": interface,
                        "cwd": entry.cwd,
                    }
                )
        skills.sort(
            key=lambda item: (
                str(item.get("scope") or ""),
                str(item.get("display_name") or item.get("name") or "").lower(),
            )
        )
        return skills

    async def _ensure_thread(
        self,
        thread_id: str,
        *,
        host_id: str | None = None,
        following: bool = False,
    ) -> ManagedCodexThread:
        normalized_thread_id = thread_id.strip()
        if not normalized_thread_id:
            raise ValueError("thread_id is required.")
        managed = self._threads.get(normalized_thread_id)
        if managed is not None:
            if following:
                await managed.session.set_following(True)
            return managed

        async with self._lock:
            managed = self._threads.get(normalized_thread_id)
            if managed is not None:
                if following:
                    await managed.session.set_following(True)
                return managed
            resolved_host_id = self._resolve_thread_host(
                normalized_thread_id,
                host_id,
            )
            session = self._new_session(
                self._config(
                    host_id=resolved_host_id,
                    thread_id=normalized_thread_id,
                )
            )
            await session.start()
            try:
                if following:
                    await session.set_following(True)
                await session.hydrate_initial_state()
            except Exception:
                await session.stop()
                raise
            return await self._register_session(normalized_thread_id, session)

    async def _register_session(
        self,
        thread_id: str,
        session: CodexIpcSession,
    ) -> ManagedCodexThread:
        existing = self._threads.get(thread_id)
        if existing is not None:
            if existing.session is not session:
                await session.stop()
            return existing

        watcher_task = asyncio.create_task(
            self._watch_thread(thread_id, session),
            name=f"open-codex-bridge-watch:{thread_id}",
        )
        event_watcher_task = None
        if self._session_has_native_events(session):
            event_watcher_task = asyncio.create_task(
                self._watch_session_events(thread_id, session),
                name=f"open-codex-bridge-events:{thread_id}",
            )
        managed = ManagedCodexThread(
            session=session,
            watcher_task=watcher_task,
            event_watcher_task=event_watcher_task,
            state=session.state,
        )
        self._threads[thread_id] = managed
        self._thread_hosts[thread_id] = session.config.host_id or "local"
        if session.state is not None:
            await self._fanout_thread_state(thread_id, session.state, session=session)
        return managed

    async def _close_thread(self, thread_id: str) -> None:
        managed = self._threads.pop(thread_id, None)
        if managed is None:
            return
        self._cancel_managed_watchers(managed)
        await self._wait_managed_watchers(managed)
        await managed.session.stop()
        self._session_events.clear_thread(thread_id)

    async def _restart_host_sessions(self, host_id: str) -> None:
        managed_threads = [
            (thread_id, managed)
            for thread_id, managed in self._threads.items()
            if (managed.session.config.host_id or "local") == host_id
        ]
        for _, managed in managed_threads:
            self._cancel_managed_watchers(managed)
        for thread_id, managed in managed_threads:
            await self._wait_managed_watchers(managed)
            await managed.session.stop()
            self._threads.pop(thread_id, None)
            self._session_events.clear_thread(thread_id)
        await self._close_workspace_session(host_id)

    async def _watch_thread(
        self,
        thread_id: str,
        session: CodexIpcSession,
    ) -> None:
        async for state in session.watch_state(replay=True):
            managed = self._threads.get(thread_id)
            if managed is not None:
                managed.state = state
            await self._fanout_thread_state(thread_id, state, session=session)

    async def _watch_session_events(
        self,
        thread_id: str,
        session: CodexIpcSession,
    ) -> None:
        async for event in session.watch_session_events():  # type: ignore[attr-defined]
            payload = self._native_session_event(thread_id, event)
            await self._session_events.publish_thread_event(thread_id, payload)

    def _session_has_native_events(self, session: CodexIpcSession) -> bool:
        return callable(getattr(session, "watch_session_events", None))

    def _cancel_managed_watchers(self, managed: ManagedCodexThread) -> None:
        managed.watcher_task.cancel()
        if managed.event_watcher_task is not None:
            managed.event_watcher_task.cancel()

    async def _wait_managed_watchers(self, managed: ManagedCodexThread) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await managed.watcher_task
        if managed.event_watcher_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await managed.event_watcher_task

    async def _fanout_thread_state(
        self,
        thread_id: str,
        state: JsonDict | None,
        *,
        session: CodexIpcSession,
    ) -> None:
        state_with_host = self._state_with_host_id(state, session.config.host_id)
        payload = {
            "thread_id": thread_id,
            "state": state_with_host,
            "stream_role": session.stream_role,
            "queued_followups": session.queued_followups,
        }
        await self._session_events.publish_to_thread_subscribers(
            thread_id,
            {
                "type": "thread_state",
                "payload": payload,
            },
        )
        if not self._session_has_native_events(session):
            await self._session_events.publish_thread_event(
                thread_id,
                self._session_state_event(
                    thread_id,
                    state_with_host,
                    session=session,
                ),
            )
        await self.event_broker.publish(
            "codex_thread_state",
            payload,
        )

    def _legacy_thread_event(
        self,
        event_type: str,
        thread_id: str,
        *,
        state: JsonDict | None,
        session: CodexIpcSession,
    ) -> CodexSessionEvent:
        return {
            "type": event_type,
            "payload": {
                "thread_id": thread_id,
                "state": state,
                "stream_role": session.stream_role,
                "queued_followups": session.queued_followups,
            },
        }

    def _session_state_event(
        self,
        thread_id: str,
        state: JsonDict | None,
        *,
        session: CodexIpcSession,
    ) -> CodexSessionEvent:
        return {
            "type": "codex_session_event",
            "payload": {
                "thread_id": thread_id,
                "method": "thread-stream-state-changed",
                "params": {
                    "conversationId": thread_id,
                    "type": "snapshot",
                    "state": state,
                    "streamRole": session.stream_role,
                    "queuedFollowups": session.queued_followups,
                },
            },
        }

    def _native_session_event(
        self,
        thread_id: str,
        event: JsonDict,
    ) -> CodexSessionEvent:
        params = event.get("params")
        return {
            "type": "codex_session_event",
            "payload": {
                "thread_id": thread_id,
                "method": event.get("method"),
                "params": params if isinstance(params, dict) else {},
                "source_client_id": event.get("sourceClientId"),
                "version": event.get("version"),
            },
        }

    async def _publish_session_event_to_broker(
        self,
        event: CodexSessionEvent,
    ) -> None:
        if event.get("type") != "codex_session_event":
            return
        payload = event.get("payload")
        await self.event_broker.publish(
            "codex_session_event",
            payload if isinstance(payload, dict) else {},
        )

    def _state_with_host_id(
        self,
        state: JsonDict | None,
        host_id: str,
    ) -> JsonDict | None:
        if not isinstance(state, dict):
            return state
        materialized = materialize_conversation_state(state)
        if not isinstance(materialized, dict):
            return materialized
        if isinstance(materialized.get("hostId"), str) and materialized["hostId"]:
            return materialized
        return {**materialized, "hostId": host_id or "local"}

    async def _apply_latest_collaboration_mode(
        self,
        thread_id: str,
        managed: ManagedCodexThread,
        collaboration_mode: JsonDict | None,
    ) -> None:
        latest_state = managed.session.state
        if isinstance(latest_state, dict):
            managed.state = latest_state
        elif isinstance(managed.state, dict):
            latest_state = managed.state

        if not isinstance(latest_state, dict):
            return

        latest_state["latestCollaborationMode"] = (
            dict(collaboration_mode)
            if isinstance(collaboration_mode, dict)
            else {
                "mode": "default",
                "settings": {
                    "model": latest_state.get("latestModel") or "",
                    "reasoning_effort": latest_state.get("latestReasoningEffort"),
                    "developer_instructions": None,
                },
            }
        )
        await self._fanout_thread_state(
            thread_id,
            latest_state,
            session=managed.session,
        )

    async def _broadcast_thread_event(self, event_type: str, thread_id: str) -> None:
        payload = {
            "type": event_type,
            "payload": {
                "thread_id": thread_id,
            },
        }
        await self._session_events.publish_to_all_thread_subscribers(payload)
        await self._session_events.publish_global_event(
            {
                "type": "codex_session_event",
                "payload": {
                    "thread_id": thread_id,
                    "method": event_type,
                    "params": {
                        "threadId": thread_id,
                    },
                },
            }
        )
        await self.event_broker.publish(event_type, payload["payload"])

    def _config(
        self,
        *,
        host_id: str = "local",
        thread_id: str | None = None,
    ) -> CodexIpcConfig:
        settings = self.config_service.load_web_settings().codex
        resolved_host_id = self._resolve_host_id(host_id, settings=settings)
        codex_home = _codex_home(self.config_service.home_dir)
        codex_config = _load_codex_home_config(codex_home)
        is_remote = resolved_host_id != "local"
        return CodexIpcConfig(
            thread_id=thread_id,
            host_id=resolved_host_id,
            client_type="yier",
            model=None if is_remote else self._thread_model(settings, codex_config),
            reasoning_effort=(
                None if is_remote else self._reasoning_effort(settings, codex_config)
            ),
            app_server_config=self._app_server_config(
                settings,
                host_id=resolved_host_id,
                codex_home=codex_home,
            ),
            default_thread_params=self._default_thread_params(
                settings,
                codex_config,
                cwd=self._default_thread_cwd(settings, resolved_host_id),
                include_model=not is_remote,
            ),
        )

    def _new_session(self, config: CodexIpcConfig) -> CodexIpcSession:
        return self._session_factory(config, notify=self._notify)

    def _app_server_config(
        self,
        settings: StoredCodexSettings,
        *,
        host_id: str,
        codex_home: Path,
    ) -> AppServerConfig:
        remote_connection = self._connection_for_host(host_id, settings=settings)
        if remote_connection is not None:
            return self._remote_app_server_config(
                remote_connection,
                cwd=None,
                client_name="open_codex_ui",
                client_title=f"Open Codex UI ({remote_connection.display_name})",
            )

        return AppServerConfig(
            launch_args_override=None,
            cwd=str(self.config_service.project_root),
            env={"CODEX_HOME": str(codex_home)},
            client_name="open_codex_ui",
            client_title="Open Codex UI",
        )

    def _remote_app_server_config(
        self,
        connection: CodexRemoteConnection,
        *,
        cwd: str | None = None,
        client_name: str = "open_codex_ui",
        client_title: str | None = None,
    ) -> AppServerConfig:
        return AppServerConfig(
            ssh_websocket=SshWebsocketAppServerConfig(
                connection=SshConnectionConfig(
                    host=self._ssh_target(connection),
                    alias=connection.ssh_alias or None,
                    port=connection.ssh_port,
                    identity=connection.identity_file or None,
                ),
                remote_cwd="~",
            ),
            cwd=cwd,
            client_name=client_name,
            client_title=client_title or f"Open Codex UI ({connection.display_name})",
        )

    def _connection_for_host(
        self,
        host_id: str,
        *,
        settings: StoredCodexSettings | None = None,
    ) -> CodexRemoteConnection | None:
        connection_id = self._connection_id_from_host(host_id)
        if not connection_id:
            return None
        resolved_settings = settings or self.config_service.load_web_settings().codex
        for connection in resolved_settings.remote_connections:
            if connection.id == connection_id:
                return connection
        raise ValueError(f"Unknown Codex host: {host_id}")

    def _resolve_host_id(
        self,
        host_id: str | None,
        *,
        settings: StoredCodexSettings | None = None,
    ) -> str:
        normalized = host_id.strip() if isinstance(host_id, str) else ""
        if not normalized or normalized == "local":
            return "local"
        resolved = (
            normalized
            if normalized.startswith("ssh:")
            else self._host_id_for_connection(normalized)
        )
        self._connection_for_host(resolved, settings=settings)
        return resolved

    def _resolve_thread_host(
        self,
        thread_id: str,
        host_id: str | None,
    ) -> str:
        if host_id:
            return self._resolve_host_id(host_id)
        return self._thread_hosts.get(thread_id, "local")

    def _host_id_for_connection(self, connection_id: str) -> str:
        return f"ssh:{connection_id.strip()}"

    def _connection_id_from_host(self, host_id: str) -> str:
        return host_id.removeprefix("ssh:") if host_id.startswith("ssh:") else ""

    def _remote_connection_by_id(
        self,
        connection_id: str,
    ) -> CodexRemoteConnection | None:
        normalized_id = connection_id.strip()
        if not normalized_id:
            return None
        for (
            connection
        ) in self.config_service.load_web_settings().codex.remote_connections:
            if connection.id == normalized_id:
                return connection
        return None

    def _remote_statuses_for(
        self,
        settings: StoredCodexSettings,
    ) -> dict[str, CodexRemoteConnectionStatus]:
        statuses: dict[str, CodexRemoteConnectionStatus] = {}
        known_ids = {connection.id for connection in settings.remote_connections}
        for stale_id in set(self._remote_connection_statuses) - known_ids:
            self._remote_connection_statuses.pop(stale_id, None)
        for connection in settings.remote_connections:
            if not connection.auto_connect:
                statuses[connection.id] = CodexRemoteConnectionStatus(
                    status="disconnected",
                    detail="Automatic connection is off",
                )
                continue
            status = self._remote_connection_statuses.get(connection.id)
            if status is None:
                status = CodexRemoteConnectionStatus(
                    status="disconnected",
                    detail="Not connected yet",
                )
            statuses[connection.id] = status
        return statuses

    def _set_remote_connection_status(
        self,
        connection_id: str,
        status: str,
        detail: str = "",
    ) -> None:
        self._remote_connection_statuses[connection_id] = CodexRemoteConnectionStatus(
            status=status,  # type: ignore[arg-type]
            detail=detail,
        )

    def _ssh_base_args(
        self,
        connection: CodexRemoteConnection,
        *,
        use_tty: bool = False,
        verbose: bool = True,
    ) -> tuple[str, ...]:
        args = [
            "ssh",
            "-tt" if use_tty else "-T",
        ]
        if verbose:
            args.append("-v")
        args.extend(
            [
                "-o",
                "BatchMode=yes",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=12",
            ]
        )
        if connection.ssh_alias:
            args.append(connection.ssh_alias)
            return tuple(args)
        if connection.identity_file:
            args.extend(["-i", connection.identity_file])
        if connection.ssh_port is not None:
            args.extend(["-p", str(connection.ssh_port)])
        args.append(self._ssh_target(connection))
        return tuple(args)

    def _ssh_target(self, connection: CodexRemoteConnection) -> str:
        if not connection.ssh_username:
            return connection.ssh_host
        return f"{connection.ssh_username}@{connection.ssh_host}"

    def _remote_login_shell_command(self, script: str) -> str:
        path_prefix = (
            'PATH="${CODEX_INSTALL_DIR:-$HOME/.local/bin}:$PATH"; export PATH; '
        )
        return f'exec "${{SHELL:-sh}}" -l -i -c {shlex.quote(path_prefix + script)}'

    def _thread_start_params(
        self,
        *,
        project_path: str | None,
        host_id: str,
    ) -> JsonDict:
        settings = self.config_service.load_web_settings().codex
        remote_connection = self._connection_for_host(host_id, settings=settings)
        if remote_connection is not None:
            resolved_project_path = project_path or "~"
        else:
            resolved_project_path = self.config_service.resolve_project_path(
                project_path
            )
        return {"cwd": resolved_project_path}

    def _default_thread_cwd(
        self,
        settings: StoredCodexSettings,
        host_id: str,
    ) -> str:
        remote_connection = self._connection_for_host(host_id, settings=settings)
        if remote_connection is not None:
            return "~"
        return str(self.config_service.project_root)

    def _default_thread_params(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
        *,
        cwd: str,
        include_model: bool = True,
    ) -> JsonDict:
        params: JsonDict = {
            "cwd": cwd,
            "approval_policy": self._approval_policy(settings, codex_config),
            "approvals_reviewer": self._approvals_reviewer(settings, codex_config),
            "sandbox": self._sandbox_mode(settings, codex_config),
            "service_tier": self._service_tier(settings, codex_config),
            "personality": self._personality(settings, codex_config),
            "base_instructions": _config_string(codex_config, "base_instructions"),
            "developer_instructions": _config_string(
                codex_config,
                "developer_instructions",
            ),
        }
        if include_model:
            params["model"] = self._thread_model(settings, codex_config)
            params["model_provider"] = _config_string(codex_config, "model_provider")
            reasoning_effort = self._reasoning_effort(settings, codex_config)
            if reasoning_effort is not None:
                params["config"] = {"model_reasoning_effort": reasoning_effort}
        ephemeral = codex_config.get("ephemeral")
        if isinstance(ephemeral, bool):
            params["ephemeral"] = ephemeral
        return {key: value for key, value in params.items() if value is not None}

    def _thread_model(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
    ) -> str | None:
        return _config_string(codex_config, "model") or settings.model or None

    def _approval_policy(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
    ) -> str | None:
        return (
            _config_string(codex_config, "approval_policy") or settings.approval_policy
        )

    def _approvals_reviewer(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
    ) -> str | None:
        return (
            _config_string(codex_config, "approvals_reviewer")
            or settings.approvals_reviewer
        )

    def _sandbox_mode(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
    ) -> str | None:
        return _config_string(codex_config, "sandbox_mode") or settings.sandbox

    def _service_tier(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
    ) -> str | None:
        return (
            _config_string(codex_config, "service_tier")
            or settings.service_tier
            or None
        )

    def _personality(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
    ) -> str | None:
        value = _config_string(codex_config, "personality") or settings.personality
        return value if value != "none" else None

    def _reasoning_effort(
        self,
        settings: StoredCodexSettings,
        codex_config: JsonDict,
    ) -> str | None:
        value = _config_string(codex_config, "model_reasoning_effort")
        if value is None:
            value = settings.reasoning_effort.strip()
        return value if value and value != "none" else None

    def _summaries_from_threads(
        self,
        response: ThreadListResponse,
        *,
        host_id: str,
    ) -> list[CodexNativeSessionSummary]:
        summaries: list[CodexNativeSessionSummary] = []
        for thread in response.data:
            if thread.ephemeral:
                continue
            summary = _thread_summary(thread, host_id=host_id)
            self._thread_hosts[summary.thread_id] = host_id
            summaries.append(summary)
        return summaries

    def _workspace_from_summaries(
        self,
        summaries: list[CodexNativeSessionSummary],
        *,
        settings: StoredCodexSettings,
    ) -> CodexWorkspaceResponse:
        sessions_by_project: dict[str, list[CodexNativeSessionSummary]] = {
            project.id: [] for project in settings.projects
        }
        recent_threads: list[CodexNativeSessionSummary] = []
        recent_thread_keys: set[tuple[str, str]] = set()
        projects_by_id = {project.id: project for project in settings.projects}
        projectless_thread_ids = set(settings.projectless_thread_ids)
        for summary in summaries:
            assignment = settings.thread_project_assignments.get(summary.thread_id)
            project = projects_by_id.get(assignment.project_id) if assignment else None
            if project is not None and project.host_id != summary.host_id:
                project = None
            if project is None and summary.thread_id in projectless_thread_ids:
                recent_key = (summary.host_id, summary.thread_id)
                if recent_key not in recent_thread_keys:
                    recent_threads.append(summary)
                    recent_thread_keys.add(recent_key)
                continue
            if project is None:
                project = next(
                    (
                        candidate
                        for candidate in settings.projects
                        if candidate.host_id == summary.host_id
                        and summary.project_path in candidate.root_paths
                    ),
                    None,
                )
            if project is None:
                continue
            sessions_by_project[project.id].append(summary)

        project_groups: list[CodexProjectGroup] = []
        for project in settings.projects:
            sessions = sessions_by_project[project.id]
            sessions.sort(
                key=lambda item: (
                    _summary_used_at(item),
                    item.started_at,
                    item.thread_id,
                ),
                reverse=True,
            )
            project_groups.append(
                CodexProjectGroup(
                    id=project.id,
                    project=project.name or "Untitled project",
                    project_path=project.root_paths[0],
                    host_id=project.host_id,
                    kind=project.kind,
                    root_paths=project.root_paths,
                    session_count=len(sessions),
                    sessions=sessions,
                )
            )

        project_groups.sort(
            key=lambda group: (
                -(_summary_used_at(group.sessions[0]) if group.sessions else 0.0),
                group.project.lower(),
            ),
        )
        recent_threads.sort(
            key=lambda item: (
                _summary_used_at(item),
                item.started_at,
                item.thread_id,
            ),
            reverse=True,
        )
        return CodexWorkspaceResponse(
            projects=project_groups,
            recent_threads=recent_threads,
            paired_editors=[],
        )

    def _notify(self, message: str) -> None:
        logger.info("open-codex-bridge: %s", message)
