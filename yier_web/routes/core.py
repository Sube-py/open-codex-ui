from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from litestar import Controller, Request, get, post, put
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from litestar.response import Response, ServerSentEvent
from litestar.response.sse import ServerSentEventMessage
from litestar.status_codes import HTTP_400_BAD_REQUEST

from yier_web.config import MCPValidationError
from yier_web.event_stream import EventStreamItem
from yier_web.schemas import (
    AuthLoginRequest,
    AuthConfigResponse,
    AuthSessionResponse,
    HealthResponse,
    LLMHealth,
    MCPConfigResponse,
    MCPHealth,
    SaveAllowedRootsRequest,
    SaveAppSettingsRequest,
    SaveAuthConfigRequest,
    SaveLLMRequest,
    SaveMCPConfigRequest,
    SaveSpeechConfigRequest,
    SpeechModelDownloadRequest,
    SpeechModelDownloadResponse,
    SelectDirectoryRequest,
    SelectDirectoryResponse,
)
from yier_web.speech import SpeechRecognizerConfig
from yier_web.speech_models import SpeechModelDownloadStatus

EVENT_STREAM_PING_INTERVAL_SECONDS = 15.0


def _service(state: State, name: str) -> Any:
    return getattr(state, name)


def _speech_download_response(
    status: SpeechModelDownloadStatus,
) -> SpeechModelDownloadResponse:
    return SpeechModelDownloadResponse(
        state=status.state,
        downloaded_bytes=status.downloaded_bytes,
        total_bytes=status.total_bytes,
        error=status.error,
        model_dir=status.model_dir,
    )


def _shutdown_event(state: State) -> asyncio.Event | None:
    shutdown_event = getattr(state, "shutdown_event", None)
    if isinstance(shutdown_event, asyncio.Event):
        return shutdown_event
    return None


async def _wait_for_event_stream_item(
    subscriber: asyncio.Queue[EventStreamItem],
    shutdown_event: asyncio.Event | None,
    timeout: float,
) -> tuple[EventStreamItem | None, bool]:
    subscriber_task = asyncio.create_task(subscriber.get())
    shutdown_task: asyncio.Task[bool] | None = None
    wait_tasks: list[asyncio.Task[Any]] = [subscriber_task]

    if shutdown_event is not None:
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        wait_tasks.append(shutdown_task)

    try:
        done, pending = await asyncio.wait(
            wait_tasks,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass

        if not done:
            return None, False

        if shutdown_task is not None and shutdown_task in done:
            return None, True

        return subscriber_task.result(), False
    finally:
        if not subscriber_task.done():
            subscriber_task.cancel()
            try:
                await subscriber_task
            except asyncio.CancelledError:
                pass
        if shutdown_task is not None and not shutdown_task.done():
            shutdown_task.cancel()
            try:
                await shutdown_task
            except asyncio.CancelledError:
                pass


wait_for_event_stream_item = _wait_for_event_stream_item


class AuthController(Controller):
    path = "/auth"

    @get("/session")
    async def get_auth_session(
        self,
        request: Request[Any, Any, Any],
        state: State,
    ) -> AuthSessionResponse:
        payload = _service(state, "auth_service").session_payload(request)
        return AuthSessionResponse(**payload)

    @post("/login")
    async def login(
        self,
        data: AuthLoginRequest,
        request: Request[Any, Any, Any],
        state: State,
    ) -> Response:
        auth_service = _service(state, "auth_service")
        if not auth_service.verify_login_password(data.password):
            raise HTTPException(status_code=401, detail="Invalid password.")
        return auth_service.build_login_response(request)

    @post("/logout")
    async def logout(self, request: Request[Any, Any, Any], state: State) -> Response:
        return _service(state, "auth_service").build_logout_response(request)


class HealthController(Controller):
    @get("/health")
    async def health(self, state: State) -> HealthResponse:
        config_service = _service(state, "config_service")
        frontend_service = _service(state, "frontend_service")
        frontend = await frontend_service.get_status()
        settings = config_service.load_web_settings()
        runtime: dict[str, Any] = {}
        failing_servers = [
            name
            for name, entry in runtime.items()
            if entry.status in {"failed", "needs_auth", "needs_client_registration"}
        ]
        mcp_ready = not failing_servers
        return HealthResponse(
            frontend=frontend,
            llm=LLMHealth(
                ready=True,
                detail=None,
            ),
            mcp=MCPHealth(
                ready=mcp_ready,
                detail=None
                if mcp_ready
                else f"Problematic MCP servers: {', '.join(failing_servers)}",
                runtime=runtime,
            ),
            backends=config_service.build_backend_health(),
            allowed_roots=settings.allowed_roots,
        )


class ConfigController(Controller):
    path = "/config"

    @get()
    async def get_config(self, state: State) -> Response:
        config_service = _service(state, "config_service")
        runtime: dict[str, Any] = {}
        return Response(content=config_service.build_public_config(runtime).model_dump())

    @get("/auth")
    async def get_auth_config(self, state: State) -> AuthConfigResponse:
        return _service(state, "auth_service").public_config()

    @put("/auth")
    async def save_auth_config(
        self,
        data: SaveAuthConfigRequest,
        request: Request[Any, Any, Any],
        state: State,
    ) -> Response:
        auth_service = _service(state, "auth_service")
        try:
            config = auth_service.save_config(data)
        except ValueError as exc:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        return auth_service.build_authenticated_response(
            request,
            config.model_dump(),
        )

    @get("/speech")
    async def get_speech_config(self, state: State) -> Response:
        return Response(content=_service(state, "speech_service").public_config().model_dump())

    @put("/speech")
    async def save_speech_config(
        self,
        data: SaveSpeechConfigRequest,
        state: State,
    ) -> Response:
        config_service = _service(state, "config_service")
        config_service.save_speech_settings(data)
        speech_service = _service(state, "speech_service")
        speech_service.reconfigure(SpeechRecognizerConfig.from_settings(config_service))
        return Response(content=speech_service.public_config().model_dump())

    @get("/speech/model-download")
    async def get_speech_model_download_status(
        self,
        state: State,
    ) -> SpeechModelDownloadResponse:
        status = _service(state, "speech_model_download_manager").status()
        return _speech_download_response(status)

    @post("/speech/model-download")
    async def start_speech_model_download(
        self,
        data: SpeechModelDownloadRequest,
        state: State,
    ) -> SpeechModelDownloadResponse:
        status = _service(state, "speech_model_download_manager").start(data.proxy)
        return _speech_download_response(status)

    @put("/llm")
    async def save_llm_config(self, data: SaveLLMRequest, state: State) -> Response:
        config_service = _service(state, "config_service")
        config_service.save_llm_settings(data)
        runtime: dict[str, Any] = {}
        return Response(content=config_service.build_public_config(runtime).model_dump())

    @put("/roots")
    async def save_allowed_roots_config(
        self,
        data: SaveAllowedRootsRequest,
        state: State,
    ) -> Response:
        config_service = _service(state, "config_service")
        config_service.save_allowed_roots(data.allowed_roots)
        runtime: dict[str, Any] = {}
        return Response(content=config_service.build_public_config(runtime).model_dump())

    @put("/app")
    async def save_app_config(self, data: SaveAppSettingsRequest, state: State) -> Response:
        config_service = _service(state, "config_service")
        config_service.save_app_settings(data)
        runtime: dict[str, Any] = {}
        return Response(content=config_service.build_public_config(runtime).model_dump())

    @get("/mcp")
    async def get_mcp_config(self, state: State) -> MCPConfigResponse:
        config_service = _service(state, "config_service")
        return MCPConfigResponse(
            mcp_servers=config_service.load_mcp_servers(),
            runtime={},
        )

    @put("/mcp")
    async def save_mcp_config(
        self,
        data: SaveMCPConfigRequest,
        state: State,
    ) -> MCPConfigResponse:
        config_service = _service(state, "config_service")
        try:
            config_service.save_mcp_servers(data.mcp_servers)
        except MCPValidationError as exc:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return MCPConfigResponse(
            mcp_servers=config_service.load_mcp_servers(),
            runtime={},
        )

    @post("/mcp/reload")
    async def reload_mcp_config(self, state: State) -> MCPConfigResponse:
        config_service = _service(state, "config_service")
        return MCPConfigResponse(
            mcp_servers=config_service.load_mcp_servers(),
            runtime={},
        )


class SystemController(Controller):
    path = "/system"

    @post("/select-directory")
    async def select_directory(
        self,
        data: SelectDirectoryRequest,
        state: State,
    ) -> SelectDirectoryResponse:
        selected_path = await asyncio.to_thread(
            _service(state, "directory_picker_service").select_directory,
            data.initial_path,
        )
        return SelectDirectoryResponse(
            selected=bool(selected_path),
            project_path=selected_path or "",
        )


class EventsController(Controller):
    path = "/events"

    @get("/stream")
    async def stream_events(self, state: State) -> ServerSentEvent:
        event_broker = _service(state, "event_broker")
        shutdown_event = _shutdown_event(state)

        async def event_stream() -> AsyncIterator[ServerSentEventMessage]:
            subscriber = event_broker.subscribe()
            try:
                yield ServerSentEventMessage(
                    event="connected",
                    data=json.dumps({"status": "ok"}, ensure_ascii=False),
                )
                while True:
                    item, shutting_down = await _wait_for_event_stream_item(
                        subscriber,
                        shutdown_event,
                        timeout=EVENT_STREAM_PING_INTERVAL_SECONDS,
                    )
                    if shutting_down:
                        break
                    if item is None:
                        yield ServerSentEventMessage(
                            event="ping",
                            data=json.dumps({"status": "alive"}, ensure_ascii=False),
                        )
                        continue

                    yield ServerSentEventMessage(
                        event=item.event,
                        data=json.dumps(item.data, ensure_ascii=False),
                    )
            finally:
                event_broker.unsubscribe(subscriber)

        return ServerSentEvent(event_stream())
