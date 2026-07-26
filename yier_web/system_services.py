from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
from typing import Any, Callable


class ServiceError(RuntimeError):
    pass


def run_command(
    command: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=capture_output,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise ServiceError(
            f"Command failed ({result.returncode}): {' '.join(command)}{suffix}"
        )
    return result


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ServiceConfig:
    executable: Path
    host: str
    port: int
    environment_path: Path
    log_path: Path
    working_directory: Path

    @property
    def command(self) -> list[str]:
        return [
            str(self.executable),
            "_service",
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--env-file",
            str(self.environment_path),
            "--log-file",
            str(self.log_path),
        ]


@dataclass(frozen=True)
class ServiceStatus:
    installed: bool
    running: bool
    pid: int | None = None


class SystemService(ABC):
    name: str

    @abstractmethod
    def install(self, config: ServiceConfig) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def status(self) -> ServiceStatus: ...

    @abstractmethod
    def uninstall(self) -> None: ...


class LaunchdService(SystemService):
    label = "io.github.sube.open-codex-ui"
    name = "Open Codex UI launch agent"

    def __init__(
        self,
        *,
        home_dir: Path,
        runtime_dir: Path,
        uid: int | None = None,
        runner: CommandRunner = run_command,
    ) -> None:
        self.home_dir = home_dir
        self.runtime_dir = runtime_dir
        self.uid = os.getuid() if uid is None else uid
        self.runner = runner
        self.plist_path = home_dir / "Library" / "LaunchAgents" / f"{self.label}.plist"

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    @property
    def target(self) -> str:
        return f"{self.domain}/{self.label}"

    def install(self, config: ServiceConfig) -> None:
        self.stop()
        self.plist_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "Label": self.label,
            "ProgramArguments": config.command,
            "WorkingDirectory": str(config.working_directory),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "ThrottleInterval": 5,
            "StandardOutPath": str(config.log_path),
            "StandardErrorPath": str(config.log_path),
        }
        temporary_path = self.plist_path.with_suffix(".tmp")
        with temporary_path.open("wb") as plist_file:
            plistlib.dump(payload, plist_file, sort_keys=True)
        temporary_path.chmod(0o600)
        temporary_path.replace(self.plist_path)
        self.runner(["launchctl", "bootstrap", self.domain, str(self.plist_path)])

    def start(self) -> None:
        if not self.plist_path.exists():
            raise ServiceError(f"Launch agent is not installed at {self.plist_path}.")
        if self._is_loaded():
            self.runner(["launchctl", "kickstart", "-k", self.target])
        else:
            self.runner(["launchctl", "bootstrap", self.domain, str(self.plist_path)])

    def stop(self) -> None:
        if self._is_loaded():
            self.runner(["launchctl", "bootout", self.target])

    def status(self) -> ServiceStatus:
        if not self.plist_path.exists():
            return ServiceStatus(installed=False, running=False)
        result = self.runner(
            ["launchctl", "print", self.target],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            return ServiceStatus(installed=True, running=False)
        pid_match = re.search(r"\bpid = (\d+)", result.stdout)
        pid = int(pid_match.group(1)) if pid_match else None
        return ServiceStatus(installed=True, running=pid is not None, pid=pid)

    def uninstall(self) -> None:
        self.stop()
        self.plist_path.unlink(missing_ok=True)

    def _is_loaded(self) -> bool:
        result = self.runner(
            ["launchctl", "print", self.target],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0


class SystemdUserService(SystemService):
    unit_name = "open-codex-ui.service"
    name = "Open Codex UI systemd user service"

    def __init__(
        self,
        *,
        home_dir: Path,
        runtime_dir: Path,
        runner: CommandRunner = run_command,
    ) -> None:
        self.home_dir = home_dir
        self.runtime_dir = runtime_dir
        self.runner = runner
        self.unit_path = home_dir / ".config" / "systemd" / "user" / self.unit_name

    def install(self, config: ServiceConfig) -> None:
        self.unit_path.parent.mkdir(parents=True, exist_ok=True)
        command = " ".join(_systemd_quote(argument) for argument in config.command)
        unit = "\n".join(
            [
                "[Unit]",
                "Description=Open Codex UI",
                "After=network.target",
                "",
                "[Service]",
                "Type=simple",
                f"ExecStart={command}",
                f"WorkingDirectory={_systemd_quote(str(config.working_directory))}",
                "Restart=on-failure",
                "RestartSec=5",
                f"StandardOutput={_systemd_quote(f'append:{config.log_path}')}",
                f"StandardError={_systemd_quote(f'append:{config.log_path}')}",
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            ]
        )
        temporary_path = self.unit_path.with_suffix(".tmp")
        temporary_path.write_text(unit, encoding="utf-8")
        temporary_path.chmod(0o600)
        temporary_path.replace(self.unit_path)
        self.runner(["systemctl", "--user", "daemon-reload"])
        self.runner(["systemctl", "--user", "enable", "--now", self.unit_name])

    def start(self) -> None:
        if not self.unit_path.exists():
            raise ServiceError(f"systemd unit is not installed at {self.unit_path}.")
        self.runner(["systemctl", "--user", "start", self.unit_name])

    def stop(self) -> None:
        if self.unit_path.exists():
            self.runner(
                ["systemctl", "--user", "stop", self.unit_name],
                check=False,
            )

    def status(self) -> ServiceStatus:
        if not self.unit_path.exists():
            return ServiceStatus(installed=False, running=False)
        active = self.runner(
            ["systemctl", "--user", "is-active", "--quiet", self.unit_name],
            check=False,
        )
        if active.returncode != 0:
            return ServiceStatus(installed=True, running=False)
        pid_result = self.runner(
            [
                "systemctl",
                "--user",
                "show",
                self.unit_name,
                "--property",
                "MainPID",
                "--value",
            ],
            capture_output=True,
        )
        try:
            pid = int(pid_result.stdout.strip() or "0") or None
        except ValueError:
            pid = None
        return ServiceStatus(installed=True, running=True, pid=pid)

    def uninstall(self) -> None:
        if self.unit_path.exists():
            self.runner(
                ["systemctl", "--user", "disable", "--now", self.unit_name],
                check=False,
            )
            self.unit_path.unlink(missing_ok=True)
            self.runner(["systemctl", "--user", "daemon-reload"])


class WindowsTaskService(SystemService):
    task_name = "OpenCodexUI"
    name = "Open Codex UI scheduled task"

    def __init__(self, *, runner: CommandRunner = run_command) -> None:
        self.runner = runner

    def install(self, config: ServiceConfig) -> None:
        task_command = subprocess.list2cmdline(config.command)
        self.runner(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                self.task_name,
                "/TR",
                task_command,
                "/SC",
                "ONLOGON",
                "/RL",
                "LIMITED",
                "/F",
            ]
        )
        self.start()

    def start(self) -> None:
        self.runner(["schtasks.exe", "/Run", "/TN", self.task_name])

    def stop(self) -> None:
        self.runner(
            ["schtasks.exe", "/End", "/TN", self.task_name],
            check=False,
        )

    def status(self) -> ServiceStatus:
        query = self.runner(
            ["schtasks.exe", "/Query", "/TN", self.task_name],
            check=False,
            capture_output=True,
        )
        if query.returncode != 0:
            return ServiceStatus(installed=False, running=False)
        state = self.runner(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-ScheduledTask -TaskName '{self.task_name}').State",
            ],
            check=False,
            capture_output=True,
        )
        return ServiceStatus(
            installed=True,
            running=state.returncode == 0 and state.stdout.strip().lower() == "running",
        )

    def uninstall(self) -> None:
        self.stop()
        self.runner(
            ["schtasks.exe", "/Delete", "/TN", self.task_name, "/F"],
            check=False,
        )


def build_system_service(
    *,
    home_dir: Path,
    runtime_dir: Path,
    platform: str | None = None,
    os_name: str | None = None,
    runner: CommandRunner = run_command,
) -> SystemService:
    resolved_platform = platform or sys.platform
    resolved_os_name = os_name or os.name
    if resolved_platform == "darwin":
        return LaunchdService(
            home_dir=home_dir,
            runtime_dir=runtime_dir,
            runner=runner,
        )
    if resolved_platform.startswith("linux"):
        return SystemdUserService(
            home_dir=home_dir,
            runtime_dir=runtime_dir,
            runner=runner,
        )
    if resolved_os_name == "nt":
        return WindowsTaskService(runner=runner)
    raise ServiceError(f"Daemon services are not supported on {resolved_platform}.")


def _systemd_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'
