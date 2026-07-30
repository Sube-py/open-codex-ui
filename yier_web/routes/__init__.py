from yier_web.routes.codex import CodexController
from yier_web.routes.core import (
    AuthController,
    ConfigController,
    EventsController,
    HealthController,
    SystemController,
)
from yier_web.routes.speech import SpeechController

__all__ = [
    "AuthController",
    "CodexController",
    "ConfigController",
    "EventsController",
    "HealthController",
    "SpeechController",
    "SystemController",
]
