from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as distribution_version
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Protocol

from yier_web.system_services import (
    ServiceConfig,
    ServiceError,
    SystemService,
    build_system_service,
    run_command,
)


PACKAGE_NAME = "open-codex-ui"


@dataclass(frozen=True)
class ToolInstallResult:
    executable: Path
    shell_updated: bool


class ToolInstaller(Protocol):
    def install(self) -> ToolInstallResult: ...


class UvToolInstaller:
    def __init__(
        self,
        *,
        package_version: str | None = None,
        uv_path: Path | None = None,
        current_executable: Path | None = None,
        environment: dict[str, str] | None = None,
        runner=run_command,
    ) -> None:
        self.package_version = package_version or distribution_version(PACKAGE_NAME)
        self.uv_path = uv_path
        self.current_executable = current_executable or Path(sys.argv[0])
        self.environment = environment if environment is not None else dict(os.environ)
        self.runner = runner

    def install(self) -> ToolInstallResult:
        uv_path = self.uv_path or self._find_uv()
        bin_result = self.runner(
            [str(uv_path), "tool", "dir", "--bin"],
            capture_output=True,
        )
        bin_dir = Path(bin_result.stdout.strip()).expanduser().resolve()
        executable_name = f"{PACKAGE_NAME}.exe" if os.name == "nt" else PACKAGE_NAME
        executable = bin_dir / executable_name
        if not self._running_persistent_command(executable):
            requirement = f"{PACKAGE_NAME}=={self.package_version}"
            self.runner([str(uv_path), "tool", "install", "--force", requirement])
        if not executable.exists():
            raise ServiceError(
                f"uv installed the tool but {executable} was not created."
            )

        shell_updated = not self._path_contains(bin_dir)
        if shell_updated:
            self.runner([str(uv_path), "tool", "update-shell"])
        return ToolInstallResult(executable=executable, shell_updated=shell_updated)

    def _running_persistent_command(self, executable: Path) -> bool:
        return (
            executable.exists()
            and self.current_executable.expanduser().resolve()
            == executable.expanduser().resolve()
        )

    def _find_uv(self) -> Path:
        executable = shutil.which("uv")
        if executable is None:
            raise ServiceError("uv is required to install the persistent command.")
        return Path(executable)

    def _path_contains(self, bin_dir: Path) -> bool:
        for entry in self.environment.get("PATH", "").split(os.pathsep):
            if not entry:
                continue
            if Path(entry).expanduser().resolve() == bin_dir:
                return True
        return False


class DaemonManager:
    def __init__(
        self,
        runtime_dir: Path | None = None,
        *,
        home_dir: Path | None = None,
        service: SystemService | None = None,
        installer: ToolInstaller | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.home_dir = (home_dir or Path.home()).resolve()
        self.runtime_dir = runtime_dir or self.home_dir / ".yier" / "web"
        self.state_path = self.runtime_dir / "open-codex-ui-service.json"
        self.environment_path = self.runtime_dir / "open-codex-ui-env.json"
        self.log_path = self.runtime_dir / "open-codex-ui.log"
        self.environment = environment if environment is not None else dict(os.environ)
        self.service = service or build_system_service(
            home_dir=self.home_dir,
            runtime_dir=self.runtime_dir,
        )
        self.installer = installer or UvToolInstaller(environment=self.environment)

    def install(self, *, host: str, port: int) -> int:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        tool = self.installer.install()
        self._write_json(self.environment_path, self._service_environment())
        config = ServiceConfig(
            executable=tool.executable,
            host=host,
            port=port,
            environment_path=self.environment_path,
            log_path=self.log_path,
            working_directory=self.home_dir,
        )
        self.service.install(config)
        self._write_json(
            self.state_path,
            {
                "executable": str(tool.executable),
                "host": host,
                "port": port,
                "service": self.service.name,
            },
        )

        print(f"Installed command: {tool.executable}")
        print(f"Installed and started {self.service.name} at http://{host}:{port}.")
        print(f"Logs: {self.log_path}")
        if tool.shell_updated:
            print("Open a new shell before using open-codex-ui directly.")
        return 0

    def start(self) -> int:
        self.service.start()
        print(f"Started {self.service.name}.")
        return 0

    def stop(self) -> int:
        status = self.service.status()
        if not status.installed:
            print(f"{self.service.name} is not installed.")
            return 0
        if not status.running:
            print(f"{self.service.name} is already stopped.")
            return 0
        self.service.stop()
        print(f"Stopped {self.service.name}.")
        return 0

    def status(self) -> int:
        status = self.service.status()
        config = self._load_state()
        if not status.installed:
            print(f"{self.service.name} is not installed.")
            return 1
        if not status.running:
            print(f"{self.service.name} is installed but not running.")
            return 1

        address = ""
        if (
            config is not None
            and isinstance(config.get("host"), str)
            and isinstance(config.get("port"), int)
        ):
            address = f" at http://{config['host']}:{config['port']}"
        pid = f" (PID {status.pid})" if status.pid is not None else ""
        print(f"{self.service.name} is running{address}{pid}.")
        print(f"Logs: {self.log_path}")
        return 0

    def uninstall(self) -> int:
        self.service.uninstall()
        self.state_path.unlink(missing_ok=True)
        self.environment_path.unlink(missing_ok=True)
        print(f"Uninstalled {self.service.name}.")
        print("The open-codex-ui command remains installed as a uv tool.")
        return 0

    def _service_environment(self) -> dict[str, str]:
        retained_names = {"HOME", "PATH", "CODEX_HOME"}
        return {
            name: value
            for name, value in self.environment.items()
            if name in retained_names or name.startswith("YIER_")
        }

    def _load_state(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.chmod(0o600)
        temporary_path.replace(path)


def load_service_environment(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceError(f"Unable to load daemon environment from {path}.") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in payload.items()
    ):
        raise ServiceError(f"Invalid daemon environment file: {path}.")
    os.environ.update(payload)
