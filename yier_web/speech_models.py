from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile
from threading import Lock, Thread
from typing import Callable, Literal
from uuid import uuid4

import httpx


DEFAULT_MODELS_DIR = Path("~/.yier/models")
STANDARD_MODEL_NAME = (
    "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
)
STANDARD_MODEL_ARCHIVE = f"{STANDARD_MODEL_NAME}.tar.bz2"
STANDARD_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{STANDARD_MODEL_ARCHIVE}"
)
STANDARD_MODEL_SHA256 = (
    "27ffbd9ee24ad186d99acc2f6354d7992b27bcab490812510665fa8f9389c5f8"
)


class SpeechModelError(RuntimeError):
    """Raised when a managed speech model operation fails."""


SpeechDownloadState = Literal["idle", "downloading", "ready", "error"]


@dataclass(frozen=True, slots=True)
class SpeechModelSpec:
    name: str
    archive_name: str
    url: str
    sha256: str
    link_name: str = "sherpa-onnx"


STANDARD_MODEL = SpeechModelSpec(
    name=STANDARD_MODEL_NAME,
    archive_name=STANDARD_MODEL_ARCHIVE,
    url=STANDARD_MODEL_URL,
    sha256=STANDARD_MODEL_SHA256,
)


class SpeechModelManager:
    def __init__(
        self,
        models_dir: Path | None = None,
        *,
        spec: SpeechModelSpec = STANDARD_MODEL,
        client_factory: Callable[[], httpx.Client] | None = None,
        proxy: str | None = None,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> None:
        self.models_dir = (
            (models_dir or DEFAULT_MODELS_DIR).expanduser().resolve()
        )
        self.spec = spec
        self.model_dir = self.models_dir / spec.name
        self.model_link = self.models_dir / spec.link_name
        self.partial_archive = self.models_dir / f".{spec.archive_name}.part"
        self.proxy = proxy.strip() if proxy else ""
        self.progress_callback = progress_callback
        self.client_factory = client_factory or self._build_default_client

    def install(self, *, force: bool = False) -> int:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        if self._is_valid_model(self.model_dir) and not force:
            self._activate_model()
            print(f"Speech model is already installed at {self.model_dir}.")
            return 0

        self._download()
        self._verify_archive()
        temporary_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{self.spec.name}.extract-",
                dir=self.models_dir,
            )
        )
        try:
            self._extract(temporary_dir)
            extracted_model = temporary_dir / self.spec.name
            self._require_valid_model(extracted_model)
            self._replace_model(extracted_model)
            self._activate_model()
        finally:
            shutil.rmtree(temporary_dir, ignore_errors=True)

        self.partial_archive.unlink(missing_ok=True)
        print(f"Installed speech model at {self.model_dir}.")
        return 0

    def status(self) -> int:
        if not self._is_valid_model(self.model_dir):
            print("The standard speech model is not installed.")
            return 1
        if not self._is_active_model():
            print(f"Speech model files exist at {self.model_dir}, but are not active.")
            return 1
        print(f"Speech model is installed and active at {self.model_dir}.")
        return 0

    def remove(self) -> int:
        self._remove_managed_link()
        if self.model_dir.is_dir() and not self.model_dir.is_symlink():
            shutil.rmtree(self.model_dir)
        elif self.model_dir.exists() or self.model_dir.is_symlink():
            raise SpeechModelError(
                f"Refusing to remove unexpected model path: {self.model_dir}"
            )
        self.partial_archive.unlink(missing_ok=True)
        print("Removed the standard speech model.")
        return 0

    def _download(self) -> None:
        existing_size = (
            self.partial_archive.stat().st_size
            if self.partial_archive.is_file()
            else 0
        )
        headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
        action = "Resuming" if existing_size else "Downloading"
        print(f"{action} speech model from {self.spec.url}")

        try:
            with self.client_factory() as client:
                with client.stream("GET", self.spec.url, headers=headers) as response:
                    if response.status_code == 416 and existing_size:
                        return
                    response.raise_for_status()
                    append = existing_size > 0 and response.status_code == 206
                    mode = "ab" if append else "wb"
                    downloaded = existing_size if append else 0
                    total = _response_total_bytes(
                        response,
                        downloaded_before_response=downloaded,
                    )
                    self._report_progress(downloaded, total)
                    last_percentage = -1
                    with self.partial_archive.open(mode) as archive_file:
                        for chunk in response.iter_bytes():
                            archive_file.write(chunk)
                            downloaded += len(chunk)
                            self._report_progress(downloaded, total)
                            last_percentage = _print_download_progress(
                                downloaded,
                                total,
                                last_percentage,
                            )
                    if downloaded:
                        print()
        except (OSError, httpx.HTTPError) as exc:
            raise SpeechModelError(f"Unable to download the speech model: {exc}") from exc

    def _report_progress(self, downloaded: int, total: int | None) -> None:
        if self.progress_callback is not None:
            self.progress_callback(downloaded, total)

    def _verify_archive(self) -> None:
        digest = hashlib.sha256()
        try:
            with self.partial_archive.open("rb") as archive_file:
                for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise SpeechModelError(
                f"Unable to read downloaded model archive: {exc}"
            ) from exc
        if digest.hexdigest() != self.spec.sha256:
            self.partial_archive.unlink(missing_ok=True)
            raise SpeechModelError(
                "Speech model checksum verification failed. The invalid download "
                "was removed; run the install command again."
            )

    def _extract(self, temporary_dir: Path) -> None:
        print("Extracting speech model...")
        try:
            with tarfile.open(self.partial_archive, mode="r:bz2") as archive:
                archive.extractall(temporary_dir, filter="data")
        except (OSError, tarfile.TarError) as exc:
            raise SpeechModelError(f"Unable to extract the speech model: {exc}") from exc

    def _replace_model(self, extracted_model: Path) -> None:
        backup = self.models_dir / f".{self.spec.name}.backup-{uuid4().hex}"
        had_existing = self.model_dir.exists()
        if had_existing:
            if not self.model_dir.is_dir() or self.model_dir.is_symlink():
                raise SpeechModelError(
                    f"Refusing to replace unexpected model path: {self.model_dir}"
                )
            self.model_dir.replace(backup)
        try:
            extracted_model.replace(self.model_dir)
        except OSError:
            if had_existing and backup.exists():
                backup.replace(self.model_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup)

    def _activate_model(self) -> None:
        if self.model_link.exists() and not self.model_link.is_symlink():
            raise SpeechModelError(
                f"Refusing to replace non-symlink model path: {self.model_link}"
            )
        temporary_link = self.models_dir / (
            f".{self.spec.link_name}.link-{uuid4().hex}"
        )
        try:
            temporary_link.symlink_to(self.spec.name, target_is_directory=True)
            temporary_link.replace(self.model_link)
        finally:
            temporary_link.unlink(missing_ok=True)

    def _remove_managed_link(self) -> None:
        if not self.model_link.is_symlink():
            if self.model_link.exists():
                raise SpeechModelError(
                    f"Refusing to remove non-symlink model path: {self.model_link}"
                )
            return
        if self.model_link.resolve() != self.model_dir.resolve():
            raise SpeechModelError(
                f"Refusing to remove custom model link: {self.model_link}"
            )
        self.model_link.unlink()

    def _is_active_model(self) -> bool:
        return (
            self.model_link.is_symlink()
            and self.model_link.resolve() == self.model_dir.resolve()
        )

    @staticmethod
    def _is_valid_model(model_dir: Path) -> bool:
        return (
            model_dir.is_dir()
            and (model_dir / "tokens.txt").is_file()
            and any(model_dir.glob("encoder*.onnx"))
            and any(model_dir.glob("decoder*.onnx"))
            and any(model_dir.glob("joiner*.onnx"))
        )

    def _require_valid_model(self, model_dir: Path) -> None:
        if not self._is_valid_model(model_dir):
            raise SpeechModelError(
                "The downloaded archive does not contain a valid sherpa-onnx "
                f"streaming model at {model_dir}."
            )

    def _build_default_client(self) -> httpx.Client:
        return httpx.Client(
            proxy=self.proxy or None,
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=30.0),
            trust_env=True,
        )


class SpeechModelDownloadManager:
    """Run the standard model download off the request thread and expose progress."""

    def __init__(self, models_dir: Path | None = None) -> None:
        self.models_dir = (
            (models_dir or DEFAULT_MODELS_DIR).expanduser().resolve()
        )
        self.model_dir = self.models_dir / STANDARD_MODEL_NAME
        self.model_link = self.models_dir / STANDARD_MODEL.link_name
        self._lock = Lock()
        self._thread: Thread | None = None
        self._status = SpeechModelDownloadStatus(model_dir=str(self.model_link))

    def status(self) -> "SpeechModelDownloadStatus":
        with self._lock:
            return self._status

    def start(self, proxy: str | None = None) -> "SpeechModelDownloadStatus":
        normalized_proxy = proxy.strip() if proxy else ""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._status
            manager = SpeechModelManager(models_dir=self.models_dir)
            if manager._is_valid_model(self.model_dir) and manager._is_active_model():
                self._status = SpeechModelDownloadStatus(
                    state="ready",
                    model_dir=str(self.model_link),
                )
                return self._status
            self._status = SpeechModelDownloadStatus(
                state="downloading",
                proxy=normalized_proxy,
                model_dir=str(self.model_link),
            )
            self._thread = Thread(
                target=self._download,
                args=(normalized_proxy,),
                name="speech-model-download",
                daemon=True,
            )
            self._thread.start()
            return self._status

    def _download(self, proxy: str) -> None:
        try:
            manager = SpeechModelManager(
                models_dir=self.models_dir,
                proxy=proxy,
                progress_callback=self._update_progress,
            )
            manager.install()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._status = SpeechModelDownloadStatus(
                    state="error",
                    error=str(exc),
                    model_dir=str(self.model_link),
                )
            return
        with self._lock:
            self._status = SpeechModelDownloadStatus(
                state="ready",
                downloaded_bytes=self._status.downloaded_bytes,
                total_bytes=self._status.total_bytes,
                model_dir=str(self.model_link),
            )

    def _update_progress(self, downloaded: int, total: int | None) -> None:
        with self._lock:
            self._status = SpeechModelDownloadStatus(
                state="downloading",
                downloaded_bytes=downloaded,
                total_bytes=total,
                proxy=self._status.proxy,
                model_dir=self._status.model_dir,
            )


@dataclass(frozen=True, slots=True)
class SpeechModelDownloadStatus:
    state: SpeechDownloadState = "idle"
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    error: str = ""
    proxy: str = ""
    model_dir: str = ""


def _response_total_bytes(
    response: httpx.Response,
    *,
    downloaded_before_response: int,
) -> int | None:
    raw_length = response.headers.get("content-length", "")
    try:
        response_length = int(raw_length)
    except ValueError:
        return None
    if response_length <= 0:
        return None
    return downloaded_before_response + response_length


def _print_download_progress(
    downloaded: int,
    total: int | None,
    last_percentage: int,
) -> int:
    if total is None:
        downloaded_mib = downloaded / (1024 * 1024)
        print(f"\rDownloaded {downloaded_mib:.1f} MiB", end="", flush=True)
        return last_percentage
    percentage = min(100, int(downloaded * 100 / total))
    if percentage != last_percentage:
        print(f"\rDownloading speech model: {percentage}%", end="", flush=True)
    return percentage
