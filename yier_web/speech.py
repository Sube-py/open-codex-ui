from __future__ import annotations

from array import array
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import threading
from typing import TYPE_CHECKING, Any

from yier_web.schemas import SpeechConfigResponse

if TYPE_CHECKING:
    from yier_web.config import AppConfigService


SPEECH_SAMPLE_RATE = 16_000
DEFAULT_MODEL_DIR = Path("~/.yier/models/sherpa-onnx")


class SpeechRecognitionUnavailable(RuntimeError):
    """Raised when streaming speech recognition cannot be initialized."""


@dataclass(frozen=True, slots=True)
class SpeechRecognizerConfig:
    model_dir: Path
    provider: str = "cpu"
    num_threads: int = 2
    model_dir_source: str = "default"
    provider_source: str = "default"
    num_threads_source: str = "default"

    @classmethod
    def from_env(cls) -> "SpeechRecognizerConfig":
        raw_model_dir = os.getenv("YIER_SHERPA_ONNX_MODEL_DIR", "").strip()
        model_dir = Path(raw_model_dir) if raw_model_dir else DEFAULT_MODEL_DIR
        return cls(
            model_dir=model_dir.expanduser().resolve(),
            provider=os.getenv("YIER_SHERPA_ONNX_PROVIDER", "cpu").strip() or "cpu",
            num_threads=_positive_env_int("YIER_SHERPA_ONNX_NUM_THREADS", 2),
            model_dir_source="environment" if raw_model_dir else "default",
            provider_source=(
                "environment"
                if os.getenv("YIER_SHERPA_ONNX_PROVIDER", "").strip()
                else "default"
            ),
            num_threads_source=(
                "environment"
                if os.getenv("YIER_SHERPA_ONNX_NUM_THREADS", "").strip()
                else "default"
            ),
        )

    @classmethod
    def from_settings(cls, config_service: AppConfigService) -> "SpeechRecognizerConfig":
        settings = config_service.load_web_settings().speech
        raw_model_dir = os.getenv("YIER_SHERPA_ONNX_MODEL_DIR", "").strip()
        raw_provider = os.getenv("YIER_SHERPA_ONNX_PROVIDER", "").strip()
        raw_num_threads = os.getenv("YIER_SHERPA_ONNX_NUM_THREADS", "").strip()
        return cls(
            model_dir=(
                Path(raw_model_dir).expanduser().resolve()
                if raw_model_dir
                else config_service.resolve_speech_model_path(settings.model_dir)
            ),
            provider=raw_provider or settings.provider or "cpu",
            num_threads=(
                _positive_env_int("YIER_SHERPA_ONNX_NUM_THREADS", 2)
                if raw_num_threads
                else settings.num_threads
            ),
            model_dir_source="environment" if raw_model_dir else "settings",
            provider_source="environment" if raw_provider else "settings",
            num_threads_source="environment" if raw_num_threads else "settings",
        )


class SpeechRecognitionSession:
    def __init__(
        self,
        recognizer: Any,
        recognizer_lock: threading.Lock,
    ) -> None:
        self._recognizer = recognizer
        self._recognizer_lock = recognizer_lock
        with self._recognizer_lock:
            self._stream = recognizer.create_stream()
        self._segments: list[str] = []
        self._finished = False

    def accept_audio(self, payload: bytes) -> str:
        if self._finished:
            raise RuntimeError("The speech recognition stream is already finished.")
        if len(payload) % 4:
            raise ValueError("Audio chunks must contain float32 PCM samples.")

        samples = array("f")
        samples.frombytes(payload)
        if sys.byteorder != "little":
            samples.byteswap()

        with self._recognizer_lock:
            self._stream.accept_waveform(SPEECH_SAMPLE_RATE, samples)
            self._decode_ready_frames()
            current = self._current_result()
            if self._recognizer.is_endpoint(self._stream):
                self._commit(current)
                self._recognizer.reset(self._stream)
                current = ""
            return _join_transcript(self._segments, current)

    def finish(self) -> str:
        if self._finished:
            return _join_transcript(self._segments)
        self._finished = True

        with self._recognizer_lock:
            self._stream.input_finished()
            self._decode_ready_frames()
            self._commit(self._current_result())
            return _join_transcript(self._segments)

    def _decode_ready_frames(self) -> None:
        while self._recognizer.is_ready(self._stream):
            self._recognizer.decode_stream(self._stream)

    def _current_result(self) -> str:
        return str(self._recognizer.get_result(self._stream)).strip()

    def _commit(self, text: str) -> None:
        normalized = text.strip()
        if normalized:
            self._segments.append(normalized)


class SpeechRecognitionService:
    def __init__(
        self,
        config: SpeechRecognizerConfig | None = None,
        *,
        recognizer: Any | None = None,
    ) -> None:
        self.config = config or SpeechRecognizerConfig.from_env()
        self._recognizer = recognizer
        self._has_injected_recognizer = recognizer is not None
        self._recognizer_lock = threading.Lock()
        self._load_lock = threading.Lock()

    def reconfigure(self, config: SpeechRecognizerConfig) -> None:
        with self._load_lock:
            self.config = config
            if not self._has_injected_recognizer:
                self._recognizer = None

    def public_config(self) -> SpeechConfigResponse:
        status, detail = self._model_status()
        return SpeechConfigResponse(
            model_dir=str(self.config.model_dir),
            provider=self.config.provider,
            num_threads=self.config.num_threads,
            status=status,
            detail=detail,
            model_dir_source=self.config.model_dir_source,
            provider_source=self.config.provider_source,
            num_threads_source=self.config.num_threads_source,
        )

    def create_session(self) -> SpeechRecognitionSession:
        recognizer = self._get_recognizer()
        return SpeechRecognitionSession(recognizer, self._recognizer_lock)

    def _get_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer

        with self._load_lock:
            if self._recognizer is not None:
                return self._recognizer
            try:
                self._recognizer = self._load_recognizer()
            except Exception as exc:  # noqa: BLE001
                raise SpeechRecognitionUnavailable(str(exc)) from exc
            return self._recognizer

    def _load_recognizer(self) -> Any:
        model_dir = self.config.model_dir
        tokens, encoder, decoder, joiner = _model_files(model_dir)

        try:
            import sherpa_onnx
        except ImportError as exc:
            raise SpeechRecognitionUnavailable(
                "sherpa-onnx is not installed or its native runtime could not be loaded."
            ) from exc

        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(tokens),
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            num_threads=self.config.num_threads,
            sample_rate=SPEECH_SAMPLE_RATE,
            feature_dim=80,
            enable_endpoint_detection=True,
            decoding_method="greedy_search",
            provider=self.config.provider,
        )

    def _model_status(self) -> tuple[str, str]:
        try:
            _model_files(self.config.model_dir)
        except SpeechRecognitionUnavailable as exc:
            return "missing", str(exc)
        return "ready", "Model files are ready."


def _find_model_file(model_dir: Path, prefix: str) -> Path:
    exact = model_dir / f"{prefix}.onnx"
    if exact.is_file():
        return exact

    candidates = sorted(
        model_dir.glob(f"{prefix}*.onnx"),
        key=lambda path: ("int8" in path.name.lower(), len(path.name), path.name),
    )
    if candidates:
        return candidates[0]
    raise SpeechRecognitionUnavailable(
        f"No {prefix}*.onnx model file found in {model_dir}"
    )


def _model_files(model_dir: Path) -> tuple[Path, Path, Path, Path]:
    if not model_dir.is_dir():
        raise SpeechRecognitionUnavailable(
            f"sherpa-onnx model directory not found: {model_dir}"
        )

    tokens = model_dir / "tokens.txt"
    if not tokens.is_file():
        raise SpeechRecognitionUnavailable(f"Model file not found: {tokens}")

    return (
        tokens,
        _find_model_file(model_dir, "encoder"),
        _find_model_file(model_dir, "decoder"),
        _find_model_file(model_dir, "joiner"),
    )


def _positive_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    try:
        value = int(raw_value) if raw_value else default
    except ValueError:
        return default
    return value if value > 0 else default


def _join_transcript(segments: list[str], current: str = "") -> str:
    values = [value.strip() for value in [*segments, current] if value.strip()]
    if not values:
        return ""

    transcript = values[0]
    for value in values[1:]:
        if _is_cjk(transcript[-1]) or _is_cjk(value[0]):
            transcript += value
        else:
            transcript = f"{transcript} {value}"
    return transcript


def _is_cjk(character: str) -> bool:
    return "\u3400" <= character <= "\u9fff"
