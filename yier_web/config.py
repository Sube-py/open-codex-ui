from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from yier_agents.src.config import YIERConfig

from yier_web.schemas import (
    BackendHealth,
    BackendOption,
    SaveAuthConfigRequest,
    CodexConfigPayload,
    CodexProjectDefinition,
    CodexProjectPayload,
    CodexRemoteConnection,
    CodexRemoteConnectionPayload,
    ConfigResponse,
    LLMConfigPayload,
    MCPRuntimeEntry,
    SaveAppSettingsRequest,
    SaveSpeechConfigRequest,
    SaveLLMRequest,
    CodexThreadProjectAssignment,
    WebSettings,
)


RUNTIME_STATUSES = {
    "connected",
    "disabled",
    "failed",
    "needs_auth",
    "needs_client_registration",
}

PROVIDER_BASE_URLS = {
    "zai": "https://api.z.ai/api/paas/v4",
    "zai-coding-plan": "https://api.z.ai/api/coding/paas/v4",
}


class MCPValidationError(ValueError):
    """Raised when MCP configuration payloads are malformed."""


class AppConfigService:
    def __init__(self, project_root: Path, home_dir: Path | None = None) -> None:
        self.project_root = project_root.resolve()
        self.home_dir = (home_dir or Path.home()).resolve()
        self.yier_root = self.home_dir / ".yier"
        self.web_root = self.yier_root / "web"
        self.settings_path = self.web_root / "settings.json"
        self.mcp_config_path = self.yier_root / ".yier.json"
        self.ensure_storage()

    def ensure_storage(self) -> None:
        self.yier_root.mkdir(parents=True, exist_ok=True)
        self.web_root.mkdir(parents=True, exist_ok=True)

    def default_allowed_roots(self) -> list[str]:
        defaults = [
            self.project_root,
            self.yier_root,
            self.home_dir / "Desktop",
            self.home_dir / "Documents",
            self.home_dir / "Downloads",
        ]
        unique_roots: list[str] = []
        seen: set[str] = set()
        for root in defaults:
            resolved = root.resolve()
            serialized = str(resolved)
            if serialized in seen:
                continue
            seen.add(serialized)
            unique_roots.append(serialized)
        return unique_roots

    def load_web_settings(self) -> WebSettings:
        if not self.settings_path.exists():
            return self._finalize_web_settings(
                WebSettings(allowed_roots=self.default_allowed_roots())
            )

        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            settings = WebSettings.model_validate(payload)
        except (json.JSONDecodeError, ValidationError):
            return self._finalize_web_settings(
                WebSettings(allowed_roots=self.default_allowed_roots())
            )

        return self._finalize_web_settings(settings)

    def save_llm_settings(self, payload: SaveLLMRequest) -> WebSettings:
        settings = self.load_web_settings()
        settings.llm.provider = payload.provider
        settings.llm.base_url = payload.base_url
        settings.llm.model = payload.model
        if payload.api_key is not None and payload.api_key != "":
            settings.llm.api_key = payload.api_key

        settings.allowed_roots = self._normalize_allowed_roots(settings.allowed_roots)
        if not settings.allowed_roots:
            settings.allowed_roots = self.default_allowed_roots()

        self._write_json(self.settings_path, settings.model_dump())
        return settings

    def save_auth_settings(self, payload: SaveAuthConfigRequest) -> WebSettings:
        from yier_web.auth import hash_password

        settings = self.load_web_settings()
        if payload.enabled:
            if payload.password:
                settings.auth.password_hash = hash_password(payload.password)
        else:
            settings.auth.password_hash = ""
        if payload.secret is not None:
            settings.auth.secret = payload.secret
        settings.auth.session_ttl_hours = payload.session_ttl_hours
        self._write_json(self.settings_path, settings.model_dump())
        return settings

    def save_speech_settings(self, payload: SaveSpeechConfigRequest) -> WebSettings:
        settings = self.load_web_settings()
        settings.speech.model_dir = str(
            self.resolve_speech_model_path(payload.model_dir)
        )
        settings.speech.provider = payload.provider or "cpu"
        settings.speech.num_threads = payload.num_threads
        self._write_json(self.settings_path, settings.model_dump())
        return settings

    def save_allowed_roots(self, allowed_roots: list[str]) -> WebSettings:
        settings = self.load_web_settings()
        normalized_roots = self._normalize_allowed_roots(allowed_roots)
        settings.allowed_roots = normalized_roots or self.default_allowed_roots()
        self._write_json(self.settings_path, settings.model_dump())
        return settings

    def save_app_settings(self, payload: SaveAppSettingsRequest) -> WebSettings:
        settings = self.load_web_settings()
        projects = settings.codex.projects
        assignments = settings.codex.thread_project_assignments
        projectless_thread_ids = settings.codex.projectless_thread_ids
        settings.session_defaults = payload.session_defaults
        settings.codex = payload.codex
        settings.codex.projects = projects
        settings.codex.thread_project_assignments = assignments
        settings.codex.projectless_thread_ids = projectless_thread_ids
        settings.allowed_roots = self._normalize_allowed_roots(settings.allowed_roots)
        if not settings.allowed_roots:
            settings.allowed_roots = self.default_allowed_roots()
        settings = self._finalize_web_settings(settings)
        self._write_json(self.settings_path, settings.model_dump())
        return settings

    def save_codex_remote_connection(
        self,
        payload: CodexRemoteConnectionPayload,
        *,
        connection_id: str | None = None,
    ) -> CodexRemoteConnection:
        settings = self.load_web_settings()
        connection = self._remote_connection_from_payload(
            payload,
            connection_id=connection_id,
        )
        connections = [
            existing
            for existing in settings.codex.remote_connections
            if existing.id != connection.id
        ]
        connections.append(connection)
        settings.codex.remote_connections = self._normalize_remote_connections(
            connections
        )
        connection = settings.codex.remote_connections[-1]
        self._write_json(self.settings_path, settings.model_dump())
        return connection

    def set_codex_remote_connection_auto_connect(
        self,
        connection_id: str,
        auto_connect: bool,
    ) -> CodexRemoteConnection:
        settings = self.load_web_settings()
        for index, connection in enumerate(settings.codex.remote_connections):
            if connection.id != connection_id:
                continue
            updated = connection.model_copy(update={"auto_connect": auto_connect})
            settings.codex.remote_connections[index] = updated
            self._write_json(self.settings_path, settings.model_dump())
            return updated
        raise ValueError("Remote connection not found.")

    def save_codex_project(
        self, payload: CodexProjectPayload
    ) -> CodexProjectDefinition:
        settings = self.load_web_settings()
        host_id = payload.host_id or "local"
        kind = payload.kind
        if kind == "local":
            host_id = "local"
            project_path = self.resolve_project_path(payload.project_path)
        else:
            if not host_id.startswith("ssh:"):
                raise ValueError("A remote project requires an SSH host.")
            connection_id = host_id.removeprefix("ssh:")
            if connection_id not in {
                connection.id for connection in settings.codex.remote_connections
            }:
                raise ValueError("Remote connection not found.")
            project_path = payload.project_path

        for project in settings.codex.projects:
            if project.host_id == host_id and project_path in project.root_paths:
                raise ValueError("This project has already been added.")

        now = time.time()
        project = CodexProjectDefinition(
            name=payload.name or self._project_name(project_path),
            kind=kind,
            host_id=host_id,
            root_paths=[project_path],
            created_at=now,
            updated_at=now,
        )
        settings.codex.projects.append(project)
        self._write_json(self.settings_path, settings.model_dump())
        return project

    def delete_codex_project(self, project_id: str) -> None:
        settings = self.load_web_settings()
        before = len(settings.codex.projects)
        settings.codex.projects = [
            project for project in settings.codex.projects if project.id != project_id
        ]
        if len(settings.codex.projects) == before:
            raise ValueError("Project not found.")
        settings.codex.thread_project_assignments = {
            thread_id: assignment
            for thread_id, assignment in settings.codex.thread_project_assignments.items()
            if assignment.project_id != project_id
        }
        self._write_json(self.settings_path, settings.model_dump())

    def assign_codex_thread_project(
        self,
        thread_id: str,
        *,
        host_id: str,
        cwd: str,
    ) -> None:
        settings = self.load_web_settings()
        project = self._matching_codex_project(settings.codex.projects, host_id, cwd)
        projectless_thread_ids = set(settings.codex.projectless_thread_ids)
        if project is None:
            settings.codex.thread_project_assignments.pop(thread_id, None)
            projectless_thread_ids.add(thread_id)
        else:
            settings.codex.thread_project_assignments[thread_id] = (
                CodexThreadProjectAssignment(
                    project_id=project.id,
                    project_kind=project.kind,
                    host_id=host_id,
                    cwd=cwd,
                )
            )
            projectless_thread_ids.discard(thread_id)
        settings.codex.projectless_thread_ids = sorted(projectless_thread_ids)
        self._write_json(self.settings_path, settings.model_dump())

    def copy_codex_thread_assignment(
        self, source_thread_id: str, thread_id: str
    ) -> None:
        settings = self.load_web_settings()
        assignment = settings.codex.thread_project_assignments.get(source_thread_id)
        projectless_thread_ids = set(settings.codex.projectless_thread_ids)
        if assignment is not None:
            settings.codex.thread_project_assignments[thread_id] = (
                assignment.model_copy()
            )
            projectless_thread_ids.discard(thread_id)
        elif source_thread_id in projectless_thread_ids:
            projectless_thread_ids.add(thread_id)
        else:
            return
        settings.codex.projectless_thread_ids = sorted(projectless_thread_ids)
        self._write_json(self.settings_path, settings.model_dump())

    def delete_codex_remote_connection(self, connection_id: str) -> None:
        settings = self.load_web_settings()
        settings.codex.remote_connections = [
            connection
            for connection in settings.codex.remote_connections
            if connection.id != connection_id
        ]
        if settings.codex.active_remote_connection_id == connection_id:
            settings.codex.active_remote_connection_id = ""
        host_id = f"ssh:{connection_id}"
        removed_project_ids = {
            project.id
            for project in settings.codex.projects
            if project.host_id == host_id
        }
        settings.codex.projects = [
            project for project in settings.codex.projects if project.host_id != host_id
        ]
        settings.codex.thread_project_assignments = {
            thread_id: assignment
            for thread_id, assignment in settings.codex.thread_project_assignments.items()
            if assignment.project_id not in removed_project_ids
        }
        self._write_json(self.settings_path, settings.model_dump())

    def set_active_codex_remote_connection(self, connection_id: str) -> WebSettings:
        settings = self.load_web_settings()
        if connection_id:
            known_ids = {
                connection.id for connection in settings.codex.remote_connections
            }
            if connection_id not in known_ids:
                raise ValueError("Remote connection not found.")
        settings.codex.active_remote_connection_id = connection_id
        self._write_json(self.settings_path, settings.model_dump())
        return settings

    def load_mcp_root_config(self) -> dict[str, Any]:
        return YIERConfig.load_config(self.yier_root)

    def load_mcp_servers(self) -> dict[str, dict[str, Any]]:
        raw = self.load_mcp_root_config().get("mcpServers", {})
        if isinstance(raw, dict):
            return {
                str(key): value for key, value in raw.items() if isinstance(value, dict)
            }
        return {}

    def save_mcp_servers(
        self, mcp_servers: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        normalized = self._normalize_mcp_servers(mcp_servers)
        payload = self.load_mcp_root_config()
        payload["mcpServers"] = normalized
        self._write_json(self.mcp_config_path, payload)
        return normalized

    def settings_marker(self) -> tuple[bool, int, int]:
        return self._path_marker(self.settings_path)

    def mcp_marker(self) -> tuple[bool, int, int]:
        return self._path_marker(self.mcp_config_path)

    def build_public_config(
        self,
        mcp_runtime: dict[str, MCPRuntimeEntry],
    ) -> ConfigResponse:
        settings = self.load_web_settings()
        return ConfigResponse(
            llm=LLMConfigPayload(
                provider=settings.llm.provider,
                base_url=settings.llm.base_url,
                model=settings.llm.model,
                has_api_key=bool(settings.llm.api_key),
            ),
            backends=self.backend_options(),
            session_defaults=settings.session_defaults,
            codex=CodexConfigPayload(
                launcher_command=settings.codex.launcher_command,
                model=settings.codex.model,
                sandbox=settings.codex.sandbox,
                approval_policy=settings.codex.approval_policy,
                approvals_reviewer=settings.codex.approvals_reviewer,
                personality=settings.codex.personality,
                reasoning_effort=settings.codex.reasoning_effort,
                show_reasoning_cards=settings.codex.show_reasoning_cards,
                service_tier=settings.codex.service_tier,
                active_remote_connection_id=settings.codex.active_remote_connection_id,
                remote_connections=settings.codex.remote_connections,
                projects=settings.codex.projects,
            ),
            allowed_roots=settings.allowed_roots,
            mcp_runtime=mcp_runtime,
        )

    def backend_options(self) -> list[BackendOption]:
        return [
            BackendOption(id="codex", label="Codex App Server"),
        ]

    def build_backend_health(self) -> dict[str, BackendHealth]:
        return {
            "codex": BackendHealth(
                ready=True,
                detail=None,
            ),
        }

    def _normalize_mcp_servers(
        self,
        mcp_servers: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for name, server in mcp_servers.items():
            normalized_name = str(name).strip()
            if not normalized_name:
                raise MCPValidationError("MCP server names cannot be empty.")
            if not isinstance(server, dict):
                raise MCPValidationError(
                    f"MCP server '{normalized_name}' must be an object."
                )
            normalized[normalized_name] = self._normalize_mcp_server(
                normalized_name, server
            )
        return normalized

    def _remote_connection_from_payload(
        self,
        payload: CodexRemoteConnectionPayload,
        *,
        connection_id: str | None,
    ) -> CodexRemoteConnection:
        if payload.ssh_alias:
            return CodexRemoteConnection(
                id=connection_id or "",
                display_name=payload.display_name,
                ssh_alias=payload.ssh_alias,
                auto_connect=payload.auto_connect,
            ).normalized()
        if not payload.ssh_host:
            raise ValueError("ssh_host is required for a direct SSH connection.")
        return CodexRemoteConnection(
            id=connection_id or "",
            display_name=payload.display_name,
            ssh_host=payload.ssh_host,
            ssh_username=payload.ssh_username,
            ssh_port=payload.ssh_port,
            identity_file=payload.identity_file,
            auto_connect=payload.auto_connect,
        ).normalized()

    def _normalize_remote_connections(
        self,
        connections: list[CodexRemoteConnection],
    ) -> list[CodexRemoteConnection]:
        normalized: list[CodexRemoteConnection] = []
        seen: set[str] = set()
        for connection in connections:
            item = connection.normalized()
            if not item.id:
                item = item.model_copy(update={"id": self._remote_connection_id(item)})
            if item.id in seen:
                item = item.model_copy(update={"id": self._remote_connection_id(item)})
            seen.add(item.id)
            normalized.append(item)
        return normalized

    def _project_name(self, project_path: str) -> str:
        normalized = project_path.rstrip("/\\")
        return Path(normalized).name or project_path

    def _matching_codex_project(
        self,
        projects: list[CodexProjectDefinition],
        host_id: str,
        cwd: str,
    ) -> CodexProjectDefinition | None:
        return next(
            (
                project
                for project in projects
                if project.host_id == host_id and cwd in project.root_paths
            ),
            None,
        )

    def _remote_connection_id(self, connection: CodexRemoteConnection) -> str:
        source = connection.ssh_alias or connection.ssh_host or connection.display_name
        return source.replace("@", "-").replace(".", "-").replace(":", "-") or "remote"

    def _normalize_mcp_server(
        self, name: str, server: dict[str, Any]
    ) -> dict[str, Any]:
        server_type = server.get("type")
        if server_type not in {"stdio", "http", "sse"}:
            raise MCPValidationError(f"MCP server '{name}' has an invalid type.")

        normalized: dict[str, Any] = {"type": server_type}
        enabled = server.get("enabled", True)
        if not isinstance(enabled, bool):
            raise MCPValidationError(
                f"MCP server '{name}' has a non-boolean 'enabled' value."
            )
        normalized["enabled"] = enabled

        status = server.get("status")
        if status is not None:
            if status not in RUNTIME_STATUSES:
                raise MCPValidationError(
                    f"MCP server '{name}' has an invalid status value."
                )
            normalized["status"] = status

        if server_type == "stdio":
            command = server.get("command", "")
            if not isinstance(command, str) or not command.strip():
                raise MCPValidationError(
                    f"MCP server '{name}' must define a stdio command."
                )
            normalized["command"] = command.strip()
            normalized["args"] = self._coerce_string_list(
                server.get("args", []), name, "args"
            )
            env = server.get("env", {})
            normalized["env"] = self._coerce_string_map(env, name, "env")
        else:
            url = server.get("url", "")
            if not isinstance(url, str) or not url.strip():
                raise MCPValidationError(f"MCP server '{name}' must define a URL.")
            normalized["url"] = url.strip()
            headers = server.get("headers", {})
            normalized["headers"] = self._coerce_string_map(headers, name, "headers")

        return normalized

    def _coerce_string_list(
        self, value: Any, server_name: str, field_name: str
    ) -> list[str]:
        if value in (None, ""):
            return []
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise MCPValidationError(
                f"MCP server '{server_name}' field '{field_name}' must be a string array."
            )
        return value

    def _coerce_string_map(
        self, value: Any, server_name: str, field_name: str
    ) -> dict[str, str]:
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise MCPValidationError(
                f"MCP server '{server_name}' field '{field_name}' must be a string object."
            )
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise MCPValidationError(
                    f"MCP server '{server_name}' field '{field_name}' must contain only strings."
                )
            normalized[key] = item
        return normalized

    def _infer_provider_from_base_url(self, base_url: str) -> str:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url:
            return ""
        for provider, provider_base_url in PROVIDER_BASE_URLS.items():
            if normalized_base_url == provider_base_url.rstrip("/"):
                return provider
        return ""

    def _normalize_allowed_roots(self, allowed_roots: list[str]) -> list[str]:
        normalized_roots: list[str] = []
        seen: set[str] = set()
        for root in allowed_roots:
            candidate = str(root).strip()
            if not candidate:
                continue
            resolved = str(self._resolve_user_path(candidate))
            if resolved in seen:
                continue
            seen.add(resolved)
            normalized_roots.append(resolved)
        return normalized_roots

    def resolve_project_path(self, raw_path: str | None) -> str:
        candidate = raw_path.strip() if isinstance(raw_path, str) else ""
        resolved = (
            self._resolve_user_path(candidate) if candidate else self.project_root
        )
        return str(resolved.resolve())

    def resolve_speech_model_path(self, raw_path: str | None) -> Path:
        candidate = raw_path.strip() if isinstance(raw_path, str) else ""
        if not candidate:
            return (self.yier_root / "models" / "sherpa-onnx").resolve()
        return self._resolve_user_path(candidate).resolve()

    def _finalize_web_settings(self, settings: WebSettings) -> WebSettings:
        settings.allowed_roots = self._normalize_allowed_roots(settings.allowed_roots)
        if not settings.allowed_roots:
            settings.allowed_roots = self.default_allowed_roots()
        inferred_provider = self._infer_provider_from_base_url(settings.llm.base_url)
        if not settings.llm.provider and inferred_provider:
            settings.llm = settings.llm.model_copy(
                update={"provider": inferred_provider}
            )
        settings.session_defaults.default_project_path = self.resolve_project_path(
            settings.session_defaults.default_project_path
        )
        settings.session_defaults.channel_project_path = self.resolve_project_path(
            settings.session_defaults.channel_project_path
        )
        if not settings.codex.launcher_command:
            settings.codex.launcher_command = "codex app-server --listen stdio://"
        settings.codex.remote_connections = self._normalize_remote_connections(
            settings.codex.remote_connections
        )
        remote_ids = {connection.id for connection in settings.codex.remote_connections}
        if settings.codex.active_remote_connection_id not in remote_ids:
            settings.codex.active_remote_connection_id = ""
        known_hosts = {
            "local",
            *(f"ssh:{connection_id}" for connection_id in remote_ids),
        }
        settings.codex.projects = [
            project
            for project in settings.codex.projects
            if project.root_paths and project.host_id in known_hosts
        ]
        settings.codex.projectless_thread_ids = list(
            dict.fromkeys(
                [
                    *settings.codex.projectless_thread_ids,
                    *self._desktop_projectless_thread_ids(),
                ]
            )
        )
        project_ids = {project.id for project in settings.codex.projects}
        settings.codex.thread_project_assignments = {
            thread_id: assignment
            for thread_id, assignment in settings.codex.thread_project_assignments.items()
            if assignment.project_id in project_ids
        }
        return settings

    def _desktop_projectless_thread_ids(self) -> list[str]:
        state_path = self.home_dir / ".codex" / ".codex-global-state.json"
        if not state_path.exists():
            return []
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        candidates = payload.get("projectless-thread-ids")
        if not isinstance(candidates, list):
            persisted_atoms = payload.get("electron-persisted-atom-state")
            if isinstance(persisted_atoms, dict):
                candidates = persisted_atoms.get("projectless-thread-ids")
        if not isinstance(candidates, list):
            return []
        return list(
            dict.fromkeys(
                thread_id.strip()
                for thread_id in candidates
                if isinstance(thread_id, str) and thread_id.strip()
            )
        )

    def _resolve_user_path(self, raw_path: str) -> Path:
        if raw_path == "~":
            return self.home_dir.resolve()
        if raw_path.startswith("~/"):
            return (self.home_dir / raw_path[2:]).resolve()
        candidate = Path(raw_path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.project_root / candidate).resolve()

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except PermissionError:
            pass

    def _path_marker(self, path: Path) -> tuple[bool, int, int]:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return (False, 0, 0)
        return (True, stat.st_mtime_ns, stat.st_size)
