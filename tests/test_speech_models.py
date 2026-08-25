from __future__ import annotations

import hashlib
from pathlib import Path
import tarfile
from threading import Event
from typing import Any

import httpx
import pytest

from yier_web.speech_models import (
    SpeechModelError,
    SpeechModelDownloadManager,
    SpeechModelManager,
    SpeechModelSpec,
)


def _build_model_archive(tmp_path: Path, model_name: str) -> bytes:
    source_root = tmp_path / "source"
    model_dir = source_root / model_name
    model_dir.mkdir(parents=True)
    for filename in (
        "tokens.txt",
        "encoder-test.onnx",
        "decoder-test.onnx",
        "joiner-test.onnx",
    ):
        (model_dir / filename).write_bytes(filename.encode())

    archive_path = tmp_path / "model.tar.bz2"
    with tarfile.open(archive_path, mode="w:bz2") as archive:
        archive.add(model_dir, arcname=model_name)
    return archive_path.read_bytes()


def _model_spec(model_name: str, archive: bytes) -> SpeechModelSpec:
    return SpeechModelSpec(
        name=model_name,
        archive_name=f"{model_name}.tar.bz2",
        url="https://models.example.test/model.tar.bz2",
        sha256=hashlib.sha256(archive).hexdigest(),
    )


def _client_factory(handler: Any):
    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    return factory


def test_install_resumes_download_activates_model_and_removes_it(
    tmp_path: Path,
) -> None:
    model_name = "test-streaming-model"
    archive = _build_model_archive(tmp_path, model_name)
    spec = _model_spec(model_name, archive)
    models_dir = tmp_path / "models"
    manager = SpeechModelManager(models_dir=models_dir, spec=spec)
    manager.partial_archive.parent.mkdir(parents=True)
    split_at = len(archive) // 2
    manager.partial_archive.write_bytes(archive[:split_at])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["range"] == f"bytes={split_at}-"
        return httpx.Response(206, content=archive[split_at:])

    manager.client_factory = _client_factory(handler)
    progress: list[tuple[int, int | None]] = []
    manager.progress_callback = lambda downloaded, total: progress.append(
        (downloaded, total)
    )

    assert manager.install() == 0
    assert len(requests) == 1
    assert manager.status() == 0
    assert manager.model_link.is_symlink()
    assert manager.model_link.resolve() == manager.model_dir
    assert (manager.model_link / "tokens.txt").is_file()
    assert not manager.partial_archive.exists()
    assert progress[-1] == (len(archive), len(archive))

    assert manager.remove() == 0
    assert not manager.model_dir.exists()
    assert not manager.model_link.exists()
    assert manager.status() == 1


def test_install_rejects_archive_with_wrong_checksum(tmp_path: Path) -> None:
    model_name = "test-streaming-model"
    archive = _build_model_archive(tmp_path, model_name)
    spec = SpeechModelSpec(
        name=model_name,
        archive_name=f"{model_name}.tar.bz2",
        url="https://models.example.test/model.tar.bz2",
        sha256="0" * 64,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=archive)

    manager = SpeechModelManager(
        models_dir=tmp_path / "models",
        spec=spec,
        client_factory=_client_factory(handler),
    )

    with pytest.raises(SpeechModelError, match="checksum verification failed"):
        manager.install()
    assert not manager.model_dir.exists()
    assert not manager.partial_archive.exists()


def test_install_reuses_existing_valid_model_without_downloading(
    tmp_path: Path,
) -> None:
    model_name = "test-streaming-model"
    archive = _build_model_archive(tmp_path, model_name)
    spec = _model_spec(model_name, archive)
    manager = SpeechModelManager(models_dir=tmp_path / "models", spec=spec)
    manager.model_dir.mkdir(parents=True)
    for filename in (
        "tokens.txt",
        "encoder.onnx",
        "decoder.onnx",
        "joiner.onnx",
    ):
        (manager.model_dir / filename).touch()

    def fail_factory() -> httpx.Client:
        raise AssertionError("existing models must not be downloaded again")

    manager.client_factory = fail_factory
    assert manager.install() == 0
    assert manager.status() == 0


def test_remove_refuses_custom_model_link(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    custom_model = models_dir / "custom"
    custom_model.mkdir(parents=True)
    manager = SpeechModelManager(models_dir=models_dir)
    manager.model_link.symlink_to(custom_model, target_is_directory=True)

    with pytest.raises(SpeechModelError, match="custom model link"):
        manager.remove()


def test_download_manager_reports_progress_and_passes_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    progressed = Event()
    release = Event()
    captured_proxy: list[str] = []

    def fake_install(manager: SpeechModelManager) -> int:
        captured_proxy.append(manager.proxy)
        started.set()
        manager._report_progress(5, 10)
        progressed.set()
        assert release.wait(timeout=1)
        manager._report_progress(10, 10)
        return 0

    monkeypatch.setattr(SpeechModelManager, "install", fake_install)
    download_manager = SpeechModelDownloadManager(models_dir=tmp_path / "models")
    initial = download_manager.start(" http://127.0.0.1:7890 ")

    assert initial.state == "downloading"
    assert started.wait(timeout=1)
    assert progressed.wait(timeout=1)
    assert download_manager.status().downloaded_bytes == 5
    release.set()
    assert _wait_for_download_state(download_manager, "ready")
    assert captured_proxy == ["http://127.0.0.1:7890"]


def _wait_for_download_state(manager: Any, expected: str) -> bool:
    for _ in range(100):
        if manager.status().state == expected:
            return True
        Event().wait(0.01)
    return False
    assert manager.model_link.is_symlink()
