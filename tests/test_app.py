from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

import yier_web.frontend as frontend_module
from yier_web.app import AppServices, create_app
from yier_web.auth import AuthService, hash_password, verify_password
from yier_web.config import AppConfigService
from yier_web.event_stream import EventStreamBroker
from yier_web.frontend import FrontendService
from yier_web.schemas import SaveAuthConfigRequest


class FakeCodexIpcManager:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def workspace(self) -> dict[str, list[Any]]:
        return {"projects": [], "paired_editors": []}


class FakeDirectoryPickerService:
    def select_directory(self, initial_path: str | None = None) -> str | None:
        return "/tmp/picked-project"


def build_test_client(tmp_path: Path) -> TestClient[Any]:
    project_root = tmp_path / "project"
    dist_root = tmp_path / "static"
    dist_root.mkdir(parents=True)
    (dist_root / "index.html").write_text("<html>codex</html>", encoding="utf-8")

    config_service = AppConfigService(
        project_root=project_root,
        home_dir=tmp_path / "home",
    )
    app = create_app(
        project_root=project_root,
        home_dir=tmp_path / "home",
        services=AppServices(
            config_service=config_service,
            codex_ipc_manager=FakeCodexIpcManager(),  # type: ignore[arg-type]
            event_broker=EventStreamBroker(),
            frontend_service=FrontendService(dist_root=dist_root),
            directory_picker_service=FakeDirectoryPickerService(),
            auth_service=AuthService(config_service),
        ),
    )
    return TestClient(app)


def test_frontend_service_defaults_to_packaged_static_directory() -> None:
    service = FrontendService()

    assert (
        service.dist_root == Path(frontend_module.__file__).resolve().parent / "static"
    )


def test_api_keeps_codex_config_and_removes_chat_routes(tmp_path: Path) -> None:
    with build_test_client(tmp_path) as client:
        config_response = client.get("/api/config")
        assert config_response.status_code == 200
        assert config_response.json()["backends"] == [
            {"id": "codex", "label": "Codex App Server"}
        ]
        assert (
            config_response.json()["session_defaults"]["workspace_surface"] == "codex"
        )

        health_response = client.get("/api/health")
        assert health_response.status_code == 200
        assert health_response.json()["backends"]["codex"]["ready"] is True

        codex_workspace_response = client.get("/api/codex/workspace")
        assert codex_workspace_response.status_code == 200
        assert codex_workspace_response.json() == {
            "projects": [],
            "paired_editors": [],
        }

        chat_response = client.get("/api/chat/sessions")
        assert chat_response.status_code == 404

        channel_response = client.get("/api/channel/workspace")
        assert channel_response.status_code == 404


def test_frontend_root_and_codex_path_serve_static_entry(tmp_path: Path) -> None:
    with build_test_client(tmp_path) as client:
        root_response = client.get("/")
        assert root_response.status_code == 200
        assert root_response.text == "<html>codex</html>"

        codex_response = client.get("/codex")
        assert codex_response.status_code == 200
        assert codex_response.text == "<html>codex</html>"


def test_auth_redirects_frontend_and_blocks_api_when_password_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YIER_AUTH_PASSWORD", "deploy-secret")

    with build_test_client(tmp_path) as client:
        frontend_response = client.get("/", follow_redirects=False)
        assert frontend_response.status_code == 302
        assert frontend_response.headers["location"] == "/login?next=%2F"

        api_response = client.get("/api/config")
        assert api_response.status_code == 401
        assert api_response.json()["detail"] == "Authentication required."

        embed_response = client.get("/codex/embed", follow_redirects=False)
        assert embed_response.status_code == 200


def test_auth_login_logout_and_hashed_password_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YIER_AUTH_PASSWORD", raising=False)
    monkeypatch.setenv("YIER_AUTH_PASSWORD_HASH", hash_password("deploy-secret"))

    with build_test_client(tmp_path) as client:
        session_response = client.get("/api/auth/session")
        assert session_response.status_code == 200
        assert session_response.json() == {
            "enabled": True,
            "authenticated": False,
        }

        invalid_login_response = client.post(
            "/api/auth/login",
            json={"password": "wrong-secret"},
        )
        assert invalid_login_response.status_code == 401
        assert invalid_login_response.json()["detail"] == "Invalid password."

        login_response = client.post(
            "/api/auth/login",
            json={"password": "deploy-secret"},
        )
        assert login_response.status_code == 201
        assert login_response.json() == {
            "enabled": True,
            "authenticated": True,
        }

        authorized_response = client.get("/api/config")
        assert authorized_response.status_code == 200

        logout_response = client.post("/api/auth/logout", json={})
        assert logout_response.status_code == 201
        assert logout_response.json() == {
            "enabled": True,
            "authenticated": False,
        }

        blocked_response = client.get("/api/config")
        assert blocked_response.status_code == 401


def test_auth_settings_are_hashed_persisted_and_applied_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "YIER_AUTH_PASSWORD",
        "YIER_AUTH_PASSWORD_HASH",
        "YIER_AUTH_SECRET",
        "YIER_AUTH_SESSION_TTL_HOURS",
    ):
        monkeypatch.delenv(name, raising=False)

    with build_test_client(tmp_path) as client:
        initial_response = client.get("/api/config/auth")
        assert initial_response.status_code == 200
        assert initial_response.json()["enabled"] is False
        assert initial_response.json()["has_password"] is False
        assert initial_response.json()["session_ttl_hours"] == 168

        missing_password_response = client.put(
            "/api/config/auth",
            json={
                "enabled": True,
                "password": None,
                "secret": None,
                "session_ttl_hours": 12,
            },
        )
        assert missing_password_response.status_code == 400
        assert missing_password_response.json()["detail"] == (
            "A password is required to enable authentication."
        )

        save_response = client.put(
            "/api/config/auth",
            json={
                "enabled": True,
                "password": "stored-password",
                "secret": "stored-session-secret",
                "session_ttl_hours": 12,
            },
        )
        assert save_response.status_code == 200
        assert save_response.json() == {
            "enabled": True,
            "has_password": True,
            "has_secret": True,
            "session_ttl_hours": 12,
            "password_source": "settings",
            "secret_source": "settings",
            "session_ttl_source": "settings",
        }
        assert "stored-password" not in save_response.text
        assert "stored-session-secret" not in save_response.text
        assert "yier_auth_session=" in save_response.headers["set-cookie"]
        assert client.get("/api/config").status_code == 200

        settings_path = tmp_path / "home" / ".yier" / "web" / "settings.json"
        stored_payload = json.loads(settings_path.read_text(encoding="utf-8"))
        stored_auth = stored_payload["auth"]
        assert "password" not in stored_auth
        assert verify_password("stored-password", stored_auth["password_hash"])
        assert stored_auth["secret"] == "stored-session-secret"
        assert stored_auth["session_ttl_hours"] == 12
        assert settings_path.stat().st_mode & 0o777 == 0o600

        client.post("/api/auth/logout", json={})
        login_response = client.post(
            "/api/auth/login",
            json={"password": "stored-password"},
        )
        assert login_response.status_code == 201

        disable_response = client.put(
            "/api/config/auth",
            json={
                "enabled": False,
                "password": None,
                "secret": "",
                "session_ttl_hours": 24,
            },
        )
        assert disable_response.status_code == 200
        assert disable_response.json()["enabled"] is False
        assert disable_response.json()["has_secret"] is False
        assert client.get("/api/config").status_code == 200


def test_auth_environment_overrides_stored_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_service = AppConfigService(
        project_root=tmp_path / "project",
        home_dir=tmp_path / "home",
    )
    config_service.save_auth_settings(
        SaveAuthConfigRequest(
            enabled=True,
            password="stored-password",
            secret="stored-secret",
            session_ttl_hours=24,
        )
    )
    monkeypatch.setenv("YIER_AUTH_PASSWORD", "environment-password")
    monkeypatch.setenv("YIER_AUTH_SECRET", "environment-secret")
    monkeypatch.setenv("YIER_AUTH_SESSION_TTL_HOURS", "6")

    auth_service = AuthService(config_service)

    assert auth_service.verify_login_password("environment-password") is True
    assert auth_service.verify_login_password("stored-password") is False
    assert auth_service.public_config().model_dump() == {
        "enabled": True,
        "has_password": True,
        "has_secret": True,
        "session_ttl_hours": 6,
        "password_source": "environment",
        "secret_source": "environment",
        "session_ttl_source": "environment",
    }
