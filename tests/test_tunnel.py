from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from yier_web.tunnel import TunnelManager
from yier_web.tunnel_cloudflare import (
    CloudflareApiClient,
    RemoteTunnel,
    TunnelError,
    inspect_local_config,
)


class FakeProcess:
    pid = 4242

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


def test_cloudflare_api_resolves_named_tunnel_and_ingress() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/accounts"):
            result: Any = [{"id": "account-1"}]
        elif path.endswith("/cfd_tunnel"):
            result = [{"id": "tunnel-1", "name": "yier"}]
        elif path.endswith("/configurations"):
            result = {
                "config": {
                    "ingress": [
                        {
                            "hostname": "yier.example.com",
                            "service": "http://localhost:9999",
                        },
                        {"service": "http_status:404"},
                    ]
                }
            }
        elif path.endswith("/token"):
            result = "connector-secret"
        else:
            raise AssertionError(f"Unexpected request: {request.url}")
        return httpx.Response(200, json={"success": True, "result": result})

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.cloudflare.test/client/v4",
    ) as http_client:
        tunnel = CloudflareApiClient("api-secret", client=http_client).resolve_tunnel(
            "yier"
        )

    assert tunnel == RemoteTunnel(
        account_id="account-1",
        tunnel_id="tunnel-1",
        name="yier",
        hostname="yier.example.com",
        origin="http://localhost:9999",
        connector_token="connector-secret",
    )
    assert all(
        request.headers["authorization"] == "Bearer api-secret" for request in requests
    )


def test_quick_tunnel_uses_default_origin_and_persists_no_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        commands.append(command)
        environments.append(kwargs["env"])
        return FakeProcess()

    manager = TunnelManager(
        runtime_dir=tmp_path / "runtime",
        home_dir=tmp_path,
        environment={"PATH": "/usr/local/bin"},
        process_factory=process_factory,
    )
    monkeypatch.setattr(
        manager, "_resolve_cloudflared", lambda: Path("/cf/cloudflared")
    )
    monkeypatch.setattr(manager, "_require_reachable_origin", lambda origin: None)
    monkeypatch.setattr(
        manager,
        "_wait_for_ready",
        lambda *args, **kwargs: "https://random.trycloudflare.com",
    )

    assert manager.start(mode="quick") == 0

    assert commands == [
        [
            "/cf/cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--pidfile",
            str(manager.pid_path),
            "--url",
            "http://127.0.0.1:13140",
        ]
    ]
    assert environments[0]["CF_TELEMETRY_DISABLE"] == "1"
    assert environments[0]["HOME"].startswith(str(manager.runtime_dir))
    state = json.loads(manager.state_path.read_text(encoding="utf-8"))
    assert state["url"] == "https://random.trycloudflare.com"
    assert state["origin"] == "http://127.0.0.1:13140"


def test_managed_remote_fetches_connector_token_into_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector_token_path: Path | None = None
    command_seen: list[str] = []

    class FakeApiClient:
        def resolve_tunnel(self, *args: Any, **kwargs: Any) -> RemoteTunnel:
            return RemoteTunnel(
                account_id="account-1",
                tunnel_id="tunnel-1",
                name="yier",
                hostname="yier.example.com",
                origin="http://localhost:9999",
                connector_token="connector-secret",
            )

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        nonlocal connector_token_path
        command_seen.extend(command)
        connector_token_path = Path(command[command.index("--token-file") + 1])
        assert connector_token_path.read_text(encoding="utf-8") == "connector-secret"
        assert connector_token_path.stat().st_mode & 0o777 == 0o600
        return FakeProcess()

    manager = TunnelManager(
        runtime_dir=tmp_path / "runtime",
        home_dir=tmp_path,
        environment={"PATH": "/usr/local/bin", "CF_TOKEN": "api-secret"},
        process_factory=process_factory,
        api_client_factory=lambda token: FakeApiClient(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        manager, "_resolve_cloudflared", lambda: Path("/cf/cloudflared")
    )
    monkeypatch.setattr(manager, "_require_reachable_origin", lambda origin: None)
    monkeypatch.setattr(
        manager,
        "_wait_for_ready",
        lambda *args, **kwargs: "https://yier.example.com",
    )

    assert manager.start(mode="managed-remote", name="yier") == 0

    assert connector_token_path is not None
    assert not connector_token_path.exists()
    assert "connector-secret" not in command_seen
    state_text = manager.state_path.read_text(encoding="utf-8")
    assert "api-secret" not in state_text
    assert "connector-secret" not in state_text
    state = json.loads(state_text)
    assert state["origin"] == "http://localhost:9999"
    assert state["hostname"] == "yier.example.com"


def test_managed_remote_removes_temporary_token_when_spawn_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "connector.token"
    token_file.write_text("connector-secret", encoding="utf-8")

    def process_factory(command: list[str], **kwargs: Any) -> FakeProcess:
        raise OSError("spawn failed")

    manager = TunnelManager(
        runtime_dir=tmp_path / "runtime",
        home_dir=tmp_path,
        environment={"PATH": "/usr/local/bin"},
        process_factory=process_factory,
    )
    monkeypatch.setattr(
        manager, "_resolve_cloudflared", lambda: Path("/cf/cloudflared")
    )

    with pytest.raises(TunnelError, match="Unable to start cloudflared"):
        manager.start(
            mode="managed-remote",
            token_file=token_file,
            hostname="yier.example.com",
        )

    assert list(manager.runtime_dir.glob("open-codex-ui-tunnel-token-*")) == []
    assert not manager.state_path.exists()


def test_managed_local_reads_hostname_and_origin_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """\
tunnel: tunnel-1
ingress:
  - hostname: yier.example.com
    service: http://localhost:13140
  - service: http_status:404
""",
        encoding="utf-8",
    )

    assert inspect_local_config(config_path, requested_hostname=None) == (
        "yier.example.com",
        "http://localhost:13140",
    )


def test_status_removes_stale_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manager = TunnelManager(runtime_dir=tmp_path / "runtime", home_dir=tmp_path)
    manager.runtime_dir.mkdir(parents=True)
    manager._write_state(
        {
            "pid": 999999,
            "mode": "quick",
            "temporary_dir": None,
        }
    )
    monkeypatch.setattr(manager, "_is_owned_process", lambda state: False)

    assert manager.status() == 1
    assert not manager.state_path.exists()
    assert "removed stale state" in capsys.readouterr().out


def test_stop_only_terminates_owned_recorded_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = TunnelManager(runtime_dir=tmp_path / "runtime", home_dir=tmp_path)
    manager.runtime_dir.mkdir(parents=True)
    manager._write_state(
        {
            "pid": 4242,
            "mode": "quick",
            "temporary_dir": None,
        }
    )
    terminated: list[int] = []
    monkeypatch.setattr(manager, "_is_owned_process", lambda state: True)
    monkeypatch.setattr(
        manager,
        "_terminate_owned_process",
        lambda pid: terminated.append(pid),
    )

    assert manager.stop() == 0
    assert terminated == [4242]
    assert not manager.state_path.exists()
