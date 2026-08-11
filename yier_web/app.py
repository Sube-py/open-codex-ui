from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
from typing import Any, AsyncIterator

from litestar import Litestar, Request, Router, get, websocket
from litestar.connection import WebSocket
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from litestar.logging import LoggingConfig
from litestar.response import Response
from litestar.status_codes import HTTP_404_NOT_FOUND

from yier_web.auth import AuthService
from yier_web.config import AppConfigService
from yier_web.codex.ipc_manager import CodexIpcManager
from yier_web.directory_picker import LocalDirectoryPickerService
from yier_web.event_stream import EventStreamBroker
from yier_web.frontend import FrontendService
from yier_web.routes import (
    AuthController,
    CodexController,
    ConfigController,
    EventsController,
    HealthController,
    SpeechController,
    SystemController,
)
from yier_web.routes.core import (
    wait_for_event_stream_item as wait_for_event_stream_item,
)
from yier_web.speech import SpeechRecognitionService, SpeechRecognizerConfig


@dataclass(slots=True)
class AppServices:
    config_service: AppConfigService
    codex_ipc_manager: CodexIpcManager
    event_broker: EventStreamBroker
    frontend_service: FrontendService
    directory_picker_service: LocalDirectoryPickerService
    auth_service: AuthService
    speech_service: SpeechRecognitionService = field(
        default_factory=SpeechRecognitionService
    )


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() not in {
        "",
        "0",
        "false",
        "no",
        "off",
    }


def _build_logging_config(*, debug: bool) -> LoggingConfig:
    return LoggingConfig(
        root={"level": "DEBUG" if debug else "INFO", "handlers": ["queue_listener"]},
        formatters={
            "standard": {
                "format": "%(asctime)s %(levelname)s %(name)s - %(message)s",
            }
        },
        loggers={
            "granian": {"level": "INFO", "handlers": ["queue_listener"]},
            "httpx": {"level": "WARNING", "handlers": ["queue_listener"]},
            "httpcore": {"level": "WARNING", "handlers": ["queue_listener"]},
            "httpcore.connection": {"level": "WARNING", "handlers": ["queue_listener"]},
            "httpcore.http11": {"level": "WARNING", "handlers": ["queue_listener"]},
        },
        log_exceptions="always",
        disable_stack_trace={HTTP_404_NOT_FOUND},
    )


def install_shutdown_signal_bridge(shutdown_event: asyncio.Event) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    if getattr(loop, "_yier_shutdown_signal_bridge_installed", False):
        return

    signal_handlers = getattr(loop, "_signal_handlers", None)
    if not isinstance(signal_handlers, dict):
        return

    installed = False
    for signum in (signal.SIGINT, signal.SIGTERM):
        existing_handle = signal_handlers.get(signum)
        if existing_handle is None or not hasattr(existing_handle, "_run"):
            continue

        def chained_handler(
            handle: Any = existing_handle,
            current_loop: asyncio.AbstractEventLoop = loop,
        ) -> None:
            shutdown_event.set()
            current_loop.call_soon(handle._run)

        try:
            loop.add_signal_handler(signum, chained_handler)
        except (NotImplementedError, RuntimeError, ValueError):
            continue
        installed = True

    if installed:
        setattr(loop, "_yier_shutdown_signal_bridge_installed", True)


def build_services(
    project_root: Path | None = None,
    home_dir: Path | None = None,
) -> AppServices:
    resolved_root = (project_root or Path.cwd()).resolve()
    config_service = AppConfigService(project_root=resolved_root, home_dir=home_dir)
    event_broker = EventStreamBroker()
    return AppServices(
        config_service=config_service,
        codex_ipc_manager=CodexIpcManager(
            config_service=config_service,
            event_broker=event_broker,
        ),
        event_broker=event_broker,
        frontend_service=FrontendService(
            debug=_env_flag("YIER_DEBUG"),
        ),
        directory_picker_service=LocalDirectoryPickerService(),
        auth_service=AuthService(config_service),
        speech_service=SpeechRecognitionService(
            config=SpeechRecognizerConfig.from_settings(config_service)
        ),
    )


api_router = Router(
    path="/api",
    route_handlers=[
        AuthController,
        HealthController,
        ConfigController,
        SystemController,
        CodexController,
        SpeechController,
        EventsController,
    ],
)


@get(path=["/", "/{path:path}"], include_in_schema=False)
async def frontend_entry(
    request: Request[Any, Any, Any], state: State, path: str = ""
) -> Response:
    if path.startswith("api/"):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND)
    return await state.frontend_service.handle_request(request, path)


@websocket(path=["/", "/{path:path}"], include_in_schema=False)
async def frontend_entry_websocket(
    socket: WebSocket,
    path: str = "",
) -> None:
    if path.startswith("api/"):
        await socket.accept()
        await socket.close(code=1008, reason="WebSocket route not found.")
        return

    await socket.app.state.frontend_service.handle_websocket(socket, path)


def create_app(
    project_root: Path | None = None,
    home_dir: Path | None = None,
    services: AppServices | None = None,
) -> Litestar:
    resolved_root = (project_root or Path.cwd()).resolve()
    debug = _env_flag("YIER_DEBUG")
    app_services = services or build_services(
        project_root=resolved_root, home_dir=home_dir
    )

    async def before_request(request: Request[Any, Any, Any]) -> Response | None:
        auth_service = app_services.auth_service
        if not auth_service.enabled:
            return None

        request_path = request.url.path
        if auth_service.is_public_path(request_path):
            return None
        if auth_service.is_authenticated(request):
            return None
        if request_path.startswith("/api/"):
            return auth_service.build_unauthorized_api_response()
        return auth_service.build_login_redirect(request)

    @asynccontextmanager
    async def lifespan(app: Litestar) -> AsyncIterator[None]:
        shutdown_event = asyncio.Event()
        install_shutdown_signal_bridge(shutdown_event)
        app.state.shutdown_event = shutdown_event
        app.state.config_service = app_services.config_service
        app.state.codex_ipc_manager = app_services.codex_ipc_manager
        app.state.event_broker = app_services.event_broker
        app.state.frontend_service = app_services.frontend_service
        app.state.directory_picker_service = app_services.directory_picker_service
        app.state.auth_service = app_services.auth_service
        app.state.speech_service = app_services.speech_service
        await app_services.codex_ipc_manager.start()
        try:
            yield
        finally:
            shutdown_event.set()
            await app_services.codex_ipc_manager.stop()

    return Litestar(
        route_handlers=[api_router, frontend_entry, frontend_entry_websocket],
        before_request=before_request,
        lifespan=[lifespan],
        debug=debug,
        logging_config=_build_logging_config(debug=debug),
    )


app = create_app()
