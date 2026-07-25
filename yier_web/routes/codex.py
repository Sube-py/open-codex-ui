from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import os
import string
from pathlib import Path
from typing import Any, cast

from litestar import Controller, get, post, put, websocket
from litestar.connection import WebSocket
from litestar.datastructures import State
from litestar.exceptions import HTTPException, WebSocketDisconnect
from litestar.response import File
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from yier_web.codex.ipc_manager import CodexIpcManager, CodexSubscriberQueue
from yier_web.codex.ws_commands import (
    CodexWsCommandContext,
    CodexWsCommandStrategyFactory,
)
from yier_web.auth import AuthService
from yier_web.schemas import (
    ArchiveCodexSessionResponse,
    CodexFilesystemEntry,
    CodexFilesystemEntryKind,
    CodexFilesystemResponse,
    CodexRemoteConnectionPayload,
    CodexRemoteConnectionApiKeyLoginPayload,
    CodexRemoteConnectionResponse,
    CodexRemoteConnectionTestResponse,
    CodexRemoteConnectionsResponse,
    CodexThreadCreateRequest,
    CodexThreadCreateResponse,
    CodexThreadNameRequest,
    CodexThreadStateResponse,
    CodexWorkspaceResponse,
)


def _codex_manager(state: State) -> CodexIpcManager:
    manager = getattr(state, "codex_ipc_manager", None)
    if manager is None:
        raise RuntimeError("Codex IPC manager is not configured.")
    return cast(CodexIpcManager, manager)


def _auth_service(state: State) -> AuthService:
    auth_service = getattr(state, "auth_service", None)
    if auth_service is None:
        raise RuntimeError("Auth service is not configured.")
    return cast(AuthService, auth_service)


def _filesystem_roots() -> list[CodexFilesystemEntry]:
    if os.name == "nt":
        return [
            CodexFilesystemEntry(
                name=f"{letter}:",
                path=str(Path(f"{letter}:/")),
                kind="directory",
                readable=True,
            )
            for letter in string.ascii_uppercase
            if Path(f"{letter}:/").exists()
        ]
    return [
        CodexFilesystemEntry(
            name="/",
            path=str(Path("/")),
            kind="directory",
            readable=True,
        )
    ]


def _entry_from_dir_entry(entry: os.DirEntry[str]) -> CodexFilesystemEntry:
    path = Path(entry.path)
    kind: CodexFilesystemEntryKind = "other"
    readable = True
    try:
        if entry.is_dir(follow_symlinks=False):
            kind = "directory"
            try:
                os.scandir(entry.path).close()
            except OSError:
                readable = False
        elif entry.is_file(follow_symlinks=False):
            kind = "file"
        else:
            kind = "other"
    except OSError:
        readable = False
    return CodexFilesystemEntry(
        name=entry.name,
        path=str(path),
        kind=kind,
        extension=path.suffix.lower() if kind == "file" else "",
        readable=readable,
    )


def _sort_filesystem_entries(
    entries: list[CodexFilesystemEntry],
) -> list[CodexFilesystemEntry]:
    return sorted(
        entries,
        key=lambda entry: (
            0 if entry.kind == "directory" else 1 if entry.kind == "file" else 2,
            entry.name.casefold(),
        ),
    )


def _list_host_filesystem(path: str | None) -> CodexFilesystemResponse:
    requested_path = Path(path).expanduser() if path else Path.cwd()
    try:
        directory = requested_path.resolve()
    except OSError as exc:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Unable to resolve path: {requested_path}",
        ) from exc

    if not directory.exists():
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Path not found: {directory}",
        )
    if not directory.is_dir():
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {directory}",
        )

    try:
        with os.scandir(directory) as iterator:
            entries = [_entry_from_dir_entry(entry) for entry in iterator]
    except PermissionError as exc:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {directory}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Unable to read directory: {directory}",
        ) from exc

    parent_path = None if directory.parent == directory else str(directory.parent)
    return CodexFilesystemResponse(
        path=str(directory),
        parent_path=parent_path,
        roots=_filesystem_roots(),
        entries=_sort_filesystem_entries(entries),
    )


def _host_image_response(path: str, *, download: bool = False) -> File:
    requested_path = Path(path).expanduser()
    try:
        image_path = requested_path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Image not found: {requested_path}",
        ) from exc

    if not image_path.is_file():
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Path is not a file: {image_path}",
        )

    media_type, _ = mimetypes.guess_type(image_path.name)
    allowed_image_types = {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
    }
    if media_type not in allowed_image_types:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Path is not a supported image: {image_path}",
        )

    return File(
        path=image_path,
        filename=image_path.name,
        media_type=media_type,
        content_disposition_type="attachment" if download else "inline",
    )


class CodexController(Controller):
    path = "/codex"
    ws_command_factory = CodexWsCommandStrategyFactory()

    @get("/workspace")
    async def get_workspace(self, state: State) -> CodexWorkspaceResponse:
        return await _codex_manager(state).workspace()

    @get("/remote-connections")
    async def get_remote_connections(
        self,
        state: State,
    ) -> CodexRemoteConnectionsResponse:
        return _codex_manager(state).remote_connections()

    @post("/remote-connections")
    async def create_remote_connection(
        self,
        data: CodexRemoteConnectionPayload,
        state: State,
    ) -> CodexRemoteConnectionResponse:
        manager = _codex_manager(state)
        previous_active_id = (
            manager.config_service.load_web_settings().codex.active_remote_connection_id
        )
        connection = manager.config_service.save_codex_remote_connection(data)
        current_active_id = (
            manager.config_service.load_web_settings().codex.active_remote_connection_id
        )
        if current_active_id != previous_active_id:
            await manager.activate_remote_connection(current_active_id)
        return CodexRemoteConnectionResponse(connection=connection)

    @put("/remote-connections/{connection_id:str}")
    async def update_remote_connection(
        self,
        connection_id: str,
        data: CodexRemoteConnectionPayload,
        state: State,
    ) -> CodexRemoteConnectionResponse:
        manager = _codex_manager(state)
        previous_active_id = (
            manager.config_service.load_web_settings().codex.active_remote_connection_id
        )
        connection = manager.config_service.save_codex_remote_connection(
            data,
            connection_id=connection_id,
        )
        current_active_id = (
            manager.config_service.load_web_settings().codex.active_remote_connection_id
        )
        await manager.restart_remote_connection(connection.id)
        if current_active_id != previous_active_id:
            await manager.activate_remote_connection(current_active_id)
        return CodexRemoteConnectionResponse(connection=connection)

    @post("/remote-connections/{connection_id:str}/delete")
    async def delete_remote_connection(
        self,
        connection_id: str,
        state: State,
    ) -> dict[str, bool]:
        manager = _codex_manager(state)
        was_active = (
            manager.config_service.load_web_settings().codex.active_remote_connection_id
            == connection_id
        )
        await manager.disconnect_remote_connection(connection_id)
        manager.config_service.delete_codex_remote_connection(connection_id)
        if was_active:
            await manager.activate_remote_connection("")
        return {"ok": True}

    @post("/remote-connections/{connection_id:str}/activate")
    async def activate_remote_connection(
        self,
        connection_id: str,
        state: State,
    ) -> dict[str, bool]:
        await _codex_manager(state).activate_remote_connection(connection_id)
        return {"ok": True}

    @post("/remote-connections/activate-local")
    async def activate_local_connection(self, state: State) -> dict[str, bool]:
        await _codex_manager(state).activate_remote_connection("")
        return {"ok": True}

    @post("/remote-connections/{connection_id:str}/restart")
    async def restart_remote_connection(
        self,
        connection_id: str,
        state: State,
    ) -> dict[str, bool]:
        await _codex_manager(state).restart_remote_connection(connection_id)
        return {"ok": True}

    @post("/remote-connections/{connection_id:str}/install")
    async def install_remote_codex(
        self,
        connection_id: str,
        state: State,
    ) -> CodexRemoteConnectionTestResponse:
        return await _codex_manager(state).install_remote_codex(connection_id)

    @post("/remote-connections/{connection_id:str}/login-api-key")
    async def login_remote_api_key(
        self,
        connection_id: str,
        data: CodexRemoteConnectionApiKeyLoginPayload,
        state: State,
    ) -> CodexRemoteConnectionTestResponse:
        return await _codex_manager(state).login_remote_api_key(
            connection_id,
            data.api_key,
        )

    @post("/remote-connections/{connection_id:str}/test")
    async def test_remote_connection(
        self,
        connection_id: str,
        state: State,
    ) -> CodexRemoteConnectionTestResponse:
        return await _codex_manager(state).test_remote_connection(connection_id)

    @get("/filesystem")
    async def get_filesystem(self, path: str | None = None) -> CodexFilesystemResponse:
        return _list_host_filesystem(path)

    @get("/image")
    async def get_image(self, path: str, download: bool = False) -> File:
        return _host_image_response(path, download=download)

    @get("/threads/{thread_id:str}/state")
    async def get_thread_state(
        self,
        thread_id: str,
        state: State,
        host_id: str | None = None,
    ) -> CodexThreadStateResponse:
        manager = _codex_manager(state)
        thread_state = await manager.get_thread_state(thread_id, host_id=host_id)
        if thread_state is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail="Codex thread state not found.",
            )
        return CodexThreadStateResponse(thread_id=thread_id, state=thread_state)

    @post("/threads")
    async def create_thread(
        self,
        data: CodexThreadCreateRequest,
        state: State,
    ) -> CodexThreadCreateResponse:
        payload = await _codex_manager(state).start_thread(
            project_path=data.project_path,
            host_id=data.host_id,
        )
        return CodexThreadCreateResponse(
            thread_id=str(payload["thread_id"]),
            host_id=str(payload.get("host_id") or "local"),
            state=payload.get("state")
            if isinstance(payload.get("state"), dict)
            else None,
        )

    @post("/threads/{thread_id:str}/archive")
    async def archive_thread(
        self,
        thread_id: str,
        state: State,
    ) -> ArchiveCodexSessionResponse:
        await _codex_manager(state).archive_thread(thread_id)
        return ArchiveCodexSessionResponse(thread_id=thread_id)

    @post("/threads/{thread_id:str}/unarchive")
    async def unarchive_thread(
        self,
        thread_id: str,
        state: State,
    ) -> dict[str, bool]:
        await _codex_manager(state).unarchive_thread(thread_id)
        return {"ok": True}

    @put("/threads/{thread_id:str}/name")
    async def rename_thread(
        self,
        thread_id: str,
        data: CodexThreadNameRequest,
        state: State,
    ) -> dict[str, bool]:
        if not data.name:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="name is required.",
            )
        await _codex_manager(state).rename_thread(thread_id, data.name)
        return {"ok": True}

    @websocket("/ws")
    async def websocket_handler(self, socket: WebSocket) -> None:
        manager = _codex_manager(socket.app.state)
        await socket.accept()
        if not _auth_service(socket.app.state).is_codex_websocket_authorized(socket):
            await socket.send_json(
                {
                    "type": "error",
                    "code": "unauthorized",
                    "message": "Authentication or a valid Codex embed token is required.",
                }
            )
            await socket.close(code=1008, reason="Codex WebSocket unauthorized.")
            return

        outbox: CodexSubscriberQueue = asyncio.Queue()
        subscribed_thread_ids: set[str] = set()

        await outbox.put(
            {
                "type": "connection_ready",
                "payload": {"ok": True},
            }
        )

        receive_task: asyncio.Task[Any] = asyncio.create_task(socket.receive_json())
        send_task: asyncio.Task[dict[str, Any]] = asyncio.create_task(outbox.get())

        try:
            while True:
                done, _pending = await asyncio.wait(
                    {receive_task, send_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if receive_task in done:
                    incoming = receive_task.result()
                    receive_task = asyncio.create_task(socket.receive_json())
                    await self._handle_ws_message(
                        manager=manager,
                        message=incoming,
                        outbox=outbox,
                        subscribed_thread_ids=subscribed_thread_ids,
                    )

                if send_task in done:
                    outbound = send_task.result()
                    await socket.send_json(outbound)
                    send_task = asyncio.create_task(outbox.get())
        except WebSocketDisconnect:
            pass
        finally:
            for task in (receive_task, send_task):
                if task.done():
                    continue
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for thread_id in subscribed_thread_ids:
                await manager.unsubscribe(thread_id, outbox)

    async def _handle_ws_message(
        self,
        *,
        manager: CodexIpcManager,
        message: Any,
        outbox: CodexSubscriberQueue,
        subscribed_thread_ids: set[str],
    ) -> None:
        request_id = None
        try:
            if not isinstance(message, dict):
                raise ValueError("WebSocket message must be an object.")
            request_id = message.get("id")
            if not isinstance(request_id, str) or not request_id:
                request_id = None
            message_type = message.get("type")
            if not isinstance(message_type, str) or not message_type:
                raise ValueError("WebSocket message type is required.")
            payload = message.get("payload")
            if not isinstance(payload, dict):
                payload = {}

            result = await self._execute_ws_command(
                manager=manager,
                message_type=message_type,
                payload=payload,
                outbox=outbox,
                subscribed_thread_ids=subscribed_thread_ids,
            )
            await outbox.put(
                {
                    "id": request_id,
                    "type": "ack",
                    "ok": True,
                    "payload": result,
                }
            )
        except Exception as exc:  # noqa: BLE001
            await outbox.put(
                {
                    "id": request_id,
                    "type": "error",
                    "code": "bad_request",
                    "message": str(exc),
                }
            )

    async def _execute_ws_command(
        self,
        *,
        manager: CodexIpcManager,
        message_type: str,
        payload: dict[str, Any],
        outbox: CodexSubscriberQueue,
        subscribed_thread_ids: set[str],
    ) -> dict[str, Any]:
        strategy = self.ws_command_factory.get(message_type)
        return await strategy.execute(
            CodexWsCommandContext(
                manager=manager,
                payload=payload,
                outbox=outbox,
                subscribed_thread_ids=subscribed_thread_ids,
            )
        )
