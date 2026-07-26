from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import plistlib
import subprocess

import pytest

from yier_web.daemon import DaemonManager, ToolInstallResult, UvToolInstaller
from yier_web.system_services import (
    LaunchdService,
    ServiceConfig,
    ServiceStatus,
    SystemdUserService,
    WindowsTaskService,
    build_system_service,
)


def completed(
    command: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.print_result = completed([], returncode=1)

    def __call__(
        self,
        command: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command[:2] == ["launchctl", "print"]:
            return self.print_result
        return completed(command)


def service_config(tmp_path: Path) -> ServiceConfig:
    return ServiceConfig(
        executable=tmp_path / "bin" / "open-codex-ui",
        host="127.0.0.1",
        port=13140,
        environment_path=tmp_path / "runtime" / "env.json",
        log_path=tmp_path / "runtime" / "daemon.log",
        working_directory=tmp_path,
    )


def test_uv_tool_installer_persists_current_version_and_updates_path(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable_name = "open-codex-ui.exe" if os.name == "nt" else "open-codex-ui"
    (bin_dir / executable_name).touch()
    calls: list[list[str]] = []

    def runner(
        command: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        stdout = str(bin_dir) if command[-2:] == ["dir", "--bin"] else ""
        return completed(command, stdout=stdout)

    installer = UvToolInstaller(
        package_version="0.1.5",
        uv_path=Path("/usr/local/bin/uv"),
        current_executable=tmp_path / "uvx-cache" / "open-codex-ui",
        environment={"PATH": "/usr/bin"},
        runner=runner,
    )

    result = installer.install()

    assert result == ToolInstallResult(
        executable=bin_dir / executable_name,
        shell_updated=True,
    )
    assert calls == [
        ["/usr/local/bin/uv", "tool", "dir", "--bin"],
        [
            "/usr/local/bin/uv",
            "tool",
            "install",
            "--force",
            "open-codex-ui==0.1.5",
        ],
        ["/usr/local/bin/uv", "tool", "update-shell"],
    ]


def test_uv_tool_installer_does_not_replace_its_running_tool(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable_name = "open-codex-ui.exe" if os.name == "nt" else "open-codex-ui"
    executable = bin_dir / executable_name
    executable.touch()
    calls: list[list[str]] = []

    def runner(
        command: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed(command, stdout=str(bin_dir))

    installer = UvToolInstaller(
        package_version="0.1.5",
        uv_path=Path("/usr/local/bin/uv"),
        current_executable=executable,
        environment={"PATH": str(bin_dir)},
        runner=runner,
    )

    assert installer.install() == ToolInstallResult(executable, shell_updated=False)
    assert calls == [["/usr/local/bin/uv", "tool", "dir", "--bin"]]


@dataclass
class FakeInstaller:
    executable: Path

    def install(self) -> ToolInstallResult:
        return ToolInstallResult(executable=self.executable, shell_updated=False)


class FakeService:
    name = "test service"

    def __init__(self) -> None:
        self.installed_config: ServiceConfig | None = None
        self.actions: list[str] = []

    def install(self, config: ServiceConfig) -> None:
        self.installed_config = config
        self.actions.append("install")

    def start(self) -> None:
        self.actions.append("start")

    def stop(self) -> None:
        self.actions.append("stop")

    def status(self) -> ServiceStatus:
        return ServiceStatus(installed=True, running=True, pid=4242)

    def uninstall(self) -> None:
        self.actions.append("uninstall")


def test_daemon_install_persists_service_configuration_and_environment(
    tmp_path: Path,
) -> None:
    service = FakeService()
    executable = tmp_path / "bin" / "open-codex-ui"
    manager = DaemonManager(
        tmp_path / "runtime",
        home_dir=tmp_path,
        service=service,
        installer=FakeInstaller(executable),
        environment={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin",
            "CODEX_HOME": str(tmp_path / ".codex"),
            "YIER_AUTH_PASSWORD": "secret",
            "UNRELATED_SECRET": "ignored",
        },
    )

    assert manager.install(host="0.0.0.0", port=13140) == 0
    assert service.actions == ["install"]
    assert service.installed_config is not None
    assert service.installed_config.command[:2] == [str(executable), "_service"]
    assert json.loads(manager.environment_path.read_text(encoding="utf-8")) == {
        "CODEX_HOME": str(tmp_path / ".codex"),
        "HOME": str(tmp_path),
        "PATH": "/usr/bin",
        "YIER_AUTH_PASSWORD": "secret",
    }
    assert json.loads(manager.state_path.read_text(encoding="utf-8")) == {
        "executable": str(executable),
        "host": "0.0.0.0",
        "port": 13140,
        "service": "test service",
    }


def test_launchd_service_writes_launch_agent_and_reports_pid(tmp_path: Path) -> None:
    runner = RecordingRunner()
    service = LaunchdService(
        home_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        uid=501,
        runner=runner,
    )
    config = service_config(tmp_path)

    service.install(config)

    with service.plist_path.open("rb") as plist_file:
        payload = plistlib.load(plist_file)
    assert payload["Label"] == "io.github.sube.open-codex-ui"
    assert payload["ProgramArguments"] == config.command
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert runner.calls[-1] == [
        "launchctl",
        "bootstrap",
        "gui/501",
        str(service.plist_path),
    ]

    runner.print_result = completed([], stdout="state = running\n\tpid = 4242\n")
    assert service.status() == ServiceStatus(installed=True, running=True, pid=4242)


def test_systemd_service_writes_and_enables_user_unit(tmp_path: Path) -> None:
    runner = RecordingRunner()
    service = SystemdUserService(
        home_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        runner=runner,
    )
    config = service_config(tmp_path)

    service.install(config)

    unit = service.unit_path.read_text(encoding="utf-8")
    assert f'ExecStart="{config.executable}" "_service"' in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    assert runner.calls[-1] == [
        "systemctl",
        "--user",
        "enable",
        "--now",
        "open-codex-ui.service",
    ]


def test_windows_service_registers_logon_task(tmp_path: Path) -> None:
    runner = RecordingRunner()
    service = WindowsTaskService(runner=runner)

    service.install(service_config(tmp_path))

    create_command = runner.calls[0]
    assert create_command[:4] == ["schtasks.exe", "/Create", "/TN", "OpenCodexUI"]
    assert "ONLOGON" in create_command
    assert runner.calls[1] == ["schtasks.exe", "/Run", "/TN", "OpenCodexUI"]


@pytest.mark.parametrize(
    ("platform", "os_name", "expected_type"),
    [
        ("darwin", "posix", LaunchdService),
        ("linux", "posix", SystemdUserService),
        ("win32", "nt", WindowsTaskService),
    ],
)
def test_build_system_service_selects_platform_adapter(
    tmp_path: Path,
    platform: str,
    os_name: str,
    expected_type: type,
) -> None:
    service = build_system_service(
        home_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        platform=platform,
        os_name=os_name,
    )

    assert isinstance(service, expected_type)
