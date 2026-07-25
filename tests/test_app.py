from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

import yier_web.frontend as frontend_module
from yier_web.app import AppServices, create_app
from yier_web.auth import AuthService, hash_password
from yier_web.config import AppConfigService
from yier_web.event_stream import EventStreamBroker
from yier_web.frontend import FrontendService


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
            auth_service=AuthService(),
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
