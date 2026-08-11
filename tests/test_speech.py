from __future__ import annotations

from array import array
import json
from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

from yier_web.app import AppServices, create_app
from yier_web.auth import AuthService
from yier_web.config import AppConfigService
from yier_web.event_stream import EventStreamBroker
from yier_web.frontend import FrontendService
from yier_web.speech import (
    SpeechRecognitionService,
    SpeechRecognitionUnavailable,
    SpeechRecognizerConfig,
)
from yier_web.schemas import SaveSpeechConfigRequest


class FakeCodexIpcManager:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class FakeDirectoryPickerService:
    def select_directory(self, initial_path: str | None = None) -> str | None:
        return initial_path


class FakeOnlineStream:
    def __init__(self) -> None:
        self.samples: list[float] = []
        self.decoded = False
        self.finished = False

    def accept_waveform(self, sample_rate: int, samples: Any) -> None:
        assert sample_rate == 16_000
        self.samples.extend(samples)
        self.decoded = False

    def input_finished(self) -> None:
        self.finished = True
        self.decoded = False


class FakeOnlineRecognizer:
    def create_stream(self) -> FakeOnlineStream:
        return FakeOnlineStream()

    def is_ready(self, stream: FakeOnlineStream) -> bool:
        return bool(stream.samples) and not stream.decoded

    def decode_stream(self, stream: FakeOnlineStream) -> None:
        stream.decoded = True

    def get_result(self, stream: FakeOnlineStream) -> str:
        return "你好世界" if stream.finished else "你好"

    def is_endpoint(self, stream: FakeOnlineStream) -> bool:
        return False

    def reset(self, stream: FakeOnlineStream) -> None:
        stream.samples = []
        stream.decoded = False


def build_speech_client(
    tmp_path: Path,
    speech_service: SpeechRecognitionService,
) -> TestClient[Any]:
    static_root = tmp_path / "static"
    static_root.mkdir(parents=True)
    (static_root / "index.html").write_text("<html></html>", encoding="utf-8")
    config_service = AppConfigService(
        project_root=tmp_path / "project",
        home_dir=tmp_path / "home",
    )
    app = create_app(
        services=AppServices(
            config_service=config_service,
            codex_ipc_manager=FakeCodexIpcManager(),  # type: ignore[arg-type]
            event_broker=EventStreamBroker(),
            frontend_service=FrontendService(dist_root=static_root),
            directory_picker_service=FakeDirectoryPickerService(),
            auth_service=AuthService(config_service),
            speech_service=speech_service,
        )
    )
    return TestClient(app)


def test_speech_websocket_streams_partial_and_final_transcripts(tmp_path: Path) -> None:
    service = SpeechRecognitionService(recognizer=FakeOnlineRecognizer())

    with build_speech_client(tmp_path, service) as client:
        with client.websocket_connect("/api/speech/ws") as socket:
            assert socket.receive_json() == {
                "type": "ready",
                "sample_rate": 16_000,
                "encoding": "float32le",
            }
            samples = array("f", [0.1, -0.1, 0.2, -0.2])
            socket.send_bytes(samples.tobytes())
            assert socket.receive_json() == {"type": "partial", "text": "你好"}
            socket.send_json({"type": "finish"})
            assert socket.receive_json() == {"type": "final", "text": "你好世界"}


def test_speech_websocket_reports_missing_model_directory(tmp_path: Path) -> None:
    service = SpeechRecognitionService(
        config=SpeechRecognizerConfig(model_dir=tmp_path / "missing-model")
    )

    with build_speech_client(tmp_path, service) as client:
        with client.websocket_connect("/api/speech/ws") as socket:
            message = socket.receive_json()

    assert message["type"] == "error"
    assert message["code"] == "unavailable"
    assert "model directory not found" in message["message"]


def test_speech_websocket_requires_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YIER_AUTH_PASSWORD", "secret")
    service = SpeechRecognitionService(recognizer=FakeOnlineRecognizer())

    with build_speech_client(tmp_path, service) as client:
        with client.websocket_connect("/api/speech/ws") as socket:
            message = socket.receive_json()

    assert message == {
        "type": "error",
        "code": "unauthorized",
        "message": "Authentication is required for voice input.",
    }


def test_speech_session_rejects_non_float32_audio() -> None:
    session = SpeechRecognitionService(
        recognizer=FakeOnlineRecognizer()
    ).create_session()

    with pytest.raises(ValueError) as exc_info:
        session.accept_audio(b"not-float32")

    assert str(exc_info.value) == "Audio chunks must contain float32 PCM samples."


def test_speech_service_retries_model_loading_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SpeechRecognitionService()
    recognizer = FakeOnlineRecognizer()
    load_attempts = 0

    def load_recognizer() -> FakeOnlineRecognizer:
        nonlocal load_attempts
        load_attempts += 1
        if load_attempts == 1:
            raise RuntimeError("model is still downloading")
        return recognizer

    monkeypatch.setattr(service, "_load_recognizer", load_recognizer)

    with pytest.raises(SpeechRecognitionUnavailable, match="model is still downloading"):
        service.create_session()

    assert service.create_session() is not None
    assert load_attempts == 2


def test_speech_settings_persist_and_reconfigure_the_running_service(
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "configured-model"
    model_dir.mkdir()
    for name in ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx"):
        (model_dir / name).write_text("model", encoding="utf-8")
    service = SpeechRecognitionService(
        config=SpeechRecognizerConfig(model_dir=tmp_path / "missing-model"),
        recognizer=FakeOnlineRecognizer(),
    )

    with build_speech_client(tmp_path, service) as client:
        initial_response = client.get("/api/config/speech")
        assert initial_response.status_code == 200
        assert initial_response.json()["status"] == "missing"

        save_response = client.put(
            "/api/config/speech",
            json={
                "model_dir": str(model_dir),
                "provider": "cpu",
                "num_threads": 4,
            },
        )
        assert save_response.status_code == 200
        assert save_response.json() == {
            "model_dir": str(model_dir),
            "provider": "cpu",
            "num_threads": 4,
            "status": "ready",
            "detail": "Model files are ready.",
            "model_dir_source": "settings",
            "provider_source": "settings",
            "num_threads_source": "settings",
        }
        assert service.config.model_dir == model_dir
        assert service.config.provider == "cpu"
        assert service.config.num_threads == 4
        assert service.create_session() is not None

        settings_path = tmp_path / "home" / ".yier" / "web" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert settings["speech"] == {
            "model_dir": str(model_dir),
            "provider": "cpu",
            "num_threads": 4,
        }


def test_speech_environment_variables_override_stored_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_service = AppConfigService(
        project_root=tmp_path / "project",
        home_dir=tmp_path / "home",
    )
    config_service.save_speech_settings(
        SaveSpeechConfigRequest(
            model_dir="~/stored-model",
            provider="cpu",
            num_threads=2,
        )
    )
    monkeypatch.setenv("YIER_SHERPA_ONNX_MODEL_DIR", str(tmp_path / "env-model"))
    monkeypatch.setenv("YIER_SHERPA_ONNX_PROVIDER", "coreml")
    monkeypatch.setenv("YIER_SHERPA_ONNX_NUM_THREADS", "6")

    config = SpeechRecognizerConfig.from_settings(config_service)

    assert config.model_dir == tmp_path / "env-model"
    assert config.provider == "coreml"
    assert config.num_threads == 6
    assert config.model_dir_source == "environment"
    assert config.provider_source == "environment"
    assert config.num_threads_source == "environment"
