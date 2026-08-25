from __future__ import annotations

from typing import Any

import pytest

from yier_web import cli


class FakeServer:
    def __init__(self) -> None:
        self.served = False

    def serve(self) -> None:
        self.served = True


def test_main_starts_with_network_production_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    server = FakeServer()

    def fake_build_server(**kwargs: Any) -> FakeServer:
        captured.update(kwargs)
        return server

    monkeypatch.setattr(cli, "build_server", fake_build_server)
    assert cli.main([]) == 0
    assert captured == {
        "host": "0.0.0.0",
        "port": 13140,
        "debug": False,
        "reload": False,
    }
    assert server.served is True


def test_main_accepts_explicit_serve_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    server = FakeServer()

    def fake_build_server(**kwargs: Any) -> FakeServer:
        captured.update(kwargs)
        return server

    monkeypatch.setattr(cli, "build_server", fake_build_server)

    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "8080"]) == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8080


def test_main_keeps_legacy_server_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_build_server(**kwargs: Any) -> FakeServer:
        captured.update(kwargs)
        return FakeServer()

    monkeypatch.setattr(cli, "build_server", fake_build_server)

    assert cli.main(["--port", "8081"]) == 0
    assert captured["port"] == 8081


def test_daemon_install_defaults_to_network_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeDaemonManager:
        def install(self, **kwargs: Any) -> int:
            calls.append(kwargs)
            return 0

    monkeypatch.setattr(cli, "DaemonManager", FakeDaemonManager)

    assert cli.main(["daemon", "install"]) == 0
    assert calls == [{"host": "0.0.0.0", "port": 13140}]


@pytest.mark.parametrize(
    ("arguments", "method_name", "expected_kwargs"),
    [
        (
            [
                "daemon",
                "install",
                "--host",
                "0.0.0.0",
                "--port",
                "8082",
            ],
            "install",
            {"host": "0.0.0.0", "port": 8082},
        ),
        (["daemon", "start"], "start", {}),
        (["daemon", "stop"], "stop", {}),
        (["daemon", "status"], "status", {}),
        (["daemon", "uninstall"], "uninstall", {}),
    ],
)
def test_main_dispatches_daemon_commands(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    method_name: str,
    expected_kwargs: dict[str, Any],
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeDaemonManager:
        def install(self, **kwargs: Any) -> int:
            calls.append(("install", kwargs))
            return 0

        def start(self) -> int:
            calls.append(("start", {}))
            return 0

        def stop(self) -> int:
            calls.append(("stop", {}))
            return 0

        def status(self) -> int:
            calls.append(("status", {}))
            return 0

        def uninstall(self) -> int:
            calls.append(("uninstall", {}))
            return 0

    monkeypatch.setattr(cli, "DaemonManager", FakeDaemonManager)

    assert cli.main(arguments) == 0
    assert calls == [(method_name, expected_kwargs)]


def test_main_dispatches_update(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeUpdater:
        def update(self) -> int:
            calls.append("update")
            return 0

    monkeypatch.setattr(cli, "UvToolUpdater", FakeUpdater)

    assert cli.main(["update"]) == 0
    assert calls == ["update"]


@pytest.mark.parametrize(
    ("arguments", "method_name"),
    [
        (["tunnel", "start"], "start"),
        (["tunnel", "status"], "status"),
        (["tunnel", "stop"], "stop"),
    ],
)
def test_main_dispatches_tunnel_commands(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    method_name: str,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeTunnelManager:
        def start(self, **kwargs: Any) -> int:
            calls.append(("start", kwargs))
            return 0

        def status(self) -> int:
            calls.append(("status", {}))
            return 0

        def stop(self) -> int:
            calls.append(("stop", {}))
            return 0

    monkeypatch.setattr(cli, "TunnelManager", FakeTunnelManager)

    assert cli.main(arguments) == 0
    assert calls[0][0] == method_name
    if method_name == "start":
        assert calls[0][1]["mode"] == "quick"
        assert calls[0][1]["origin"] is None


@pytest.mark.parametrize(
    ("arguments", "method_name", "expected_kwargs"),
    [
        (["speech", "install"], "install", {"force": False}),
        (["speech", "install", "--force"], "install", {"force": True}),
        (["speech", "status"], "status", {}),
        (["speech", "remove"], "remove", {}),
    ],
)
def test_main_dispatches_speech_commands(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    method_name: str,
    expected_kwargs: dict[str, Any],
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeSpeechModelManager:
        def __init__(self, *, models_dir: Any) -> None:
            assert models_dir is None

        def install(self, **kwargs: Any) -> int:
            calls.append(("install", kwargs))
            return 0

        def status(self) -> int:
            calls.append(("status", {}))
            return 0

        def remove(self) -> int:
            calls.append(("remove", {}))
            return 0

    monkeypatch.setattr(cli, "SpeechModelManager", FakeSpeechModelManager)

    assert cli.main(arguments) == 0
    assert calls == [(method_name, expected_kwargs)]


def test_main_reports_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith("open-codex-ui 0.1.18")
