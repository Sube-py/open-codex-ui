from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


MCPRuntimeStatus = Literal[
    "connected",
    "disabled",
    "failed",
    "needs_auth",
    "needs_client_registration",
]
FrontendMode = Literal["proxy", "static", "missing"]
LLMProvider = Literal["", "zai", "zai-coding-plan"]
BackendId = Literal["yier", "codex"]
WorkspaceSurface = Literal["yier", "codex", "claude"]
CodexApprovalPolicy = Literal["untrusted", "on-failure", "on-request", "never"]
CodexSandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
CodexPersonality = Literal["none", "friendly", "pragmatic"]
CodexReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
CodexServiceTier = Literal["", "fast", "flex"]
CodexApprovalsReviewer = Literal["user", "guardian_subagent"]
CodexProjectKind = Literal["local", "remote"]
AuthConfigSource = Literal["environment", "settings", "default"]
SpeechConfigSource = Literal["environment", "settings", "default"]


class StoredAuthSettings(BaseModel):
    password_hash: str = ""
    secret: str = ""
    session_ttl_hours: int = Field(default=24 * 7, ge=1)

    @field_validator("password_hash", "secret")
    @classmethod
    def strip_auth_strings(cls, value: str) -> str:
        return value.strip()


class StoredSpeechSettings(BaseModel):
    model_dir: str = ""
    provider: str = "cpu"
    num_threads: int = Field(default=2, ge=1)

    @field_validator("model_dir", "provider")
    @classmethod
    def strip_speech_strings(cls, value: str) -> str:
        return value.strip()


class StoredLLMSettings(BaseModel):
    provider: LLMProvider = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    @property
    def is_preset(self) -> bool:
        return self.provider in {"zai", "zai-coding-plan"}

    @property
    def is_ready(self) -> bool:
        has_model = bool(self.model.strip())
        has_api_key = bool(self.api_key.strip())
        if self.is_preset:
            return bool(self.provider and has_model and has_api_key)
        return bool(self.base_url.strip() and has_model and has_api_key)


class SessionDefaultsSettings(BaseModel):
    default_backend_id: BackendId = "codex"
    default_project_path: str = ""
    channel_backend_id: BackendId = "codex"
    channel_project_path: str = ""
    channel_auto_approve_codex_requests: bool = True
    workspace_surface: WorkspaceSurface = "codex"

    @field_validator("default_backend_id", "channel_backend_id")
    @classmethod
    def normalize_backend_id(cls, value: str) -> BackendId:
        return "codex"

    @field_validator("workspace_surface")
    @classmethod
    def normalize_workspace_surface(cls, value: str) -> WorkspaceSurface:
        return "codex"


class StoredCodexSettings(BaseModel):
    # Retained for backward compatibility with existing settings files. The
    # app-server is always launched from the SDK's bundled runtime; this field
    # no longer affects startup.
    launcher_command: str = ""
    model: str = "gpt-5.4"
    sandbox: CodexSandboxMode = "workspace-write"
    approval_policy: CodexApprovalPolicy = "on-request"
    approvals_reviewer: CodexApprovalsReviewer = "user"
    personality: CodexPersonality = "friendly"
    reasoning_effort: CodexReasoningEffort = "medium"
    show_reasoning_cards: bool = False
    service_tier: CodexServiceTier = ""
    active_remote_connection_id: str = ""
    remote_connections: list["CodexRemoteConnection"] = Field(default_factory=list)
    projects: list["CodexProjectDefinition"] = Field(default_factory=list)
    thread_project_assignments: dict[str, "CodexThreadProjectAssignment"] = Field(
        default_factory=dict
    )
    projectless_thread_ids: list[str] = Field(default_factory=list)

    @field_validator("launcher_command", "model", "active_remote_connection_id")
    @classmethod
    def strip_string_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("projectless_thread_ids")
    @classmethod
    def normalize_projectless_thread_ids(cls, value: list[str]) -> list[str]:
        return list(
            dict.fromkeys(thread_id.strip() for thread_id in value if thread_id.strip())
        )


class CodexRemoteConnection(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    display_name: str = ""
    ssh_host: str = ""
    ssh_username: str = ""
    ssh_port: int | None = None
    ssh_alias: str = ""
    identity_file: str = ""
    auto_connect: bool = False

    @field_validator(
        "id",
        "display_name",
        "ssh_host",
        "ssh_username",
        "ssh_alias",
        "identity_file",
    )
    @classmethod
    def strip_remote_connection_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("ssh_port")
    @classmethod
    def validate_ssh_port(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1 or value > 65535:
            raise ValueError("ssh_port must be between 1 and 65535.")
        return value

    def normalized(self) -> "CodexRemoteConnection":
        if self.ssh_alias:
            display_name = self.display_name or self.ssh_alias
            return self.model_copy(
                update={
                    "display_name": display_name,
                    "ssh_host": "",
                    "ssh_username": "",
                    "ssh_port": None,
                    "identity_file": "",
                }
            )

        ssh_host, ssh_username = self._direct_target()
        display_name = self.display_name or "@".join(
            part for part in (ssh_username, ssh_host) if part
        )
        return self.model_copy(
            update={
                "display_name": display_name,
                "ssh_host": ssh_host,
                "ssh_username": ssh_username,
            }
        )

    def _direct_target(self) -> tuple[str, str]:
        if self.ssh_username or "@" not in self.ssh_host:
            return self.ssh_host, self.ssh_username
        ssh_username, ssh_host = self.ssh_host.split("@", maxsplit=1)
        return ssh_host, ssh_username


class CodexProjectDefinition(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = ""
    kind: CodexProjectKind = "local"
    host_id: str = "local"
    root_paths: list[str] = Field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    @field_validator("id", "name", "host_id")
    @classmethod
    def strip_project_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("root_paths")
    @classmethod
    def normalize_project_roots(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(path.strip() for path in value if path.strip()))


class CodexProjectPayload(BaseModel):
    name: str = ""
    kind: CodexProjectKind = "local"
    host_id: str = "local"
    project_path: str

    @field_validator("name", "host_id", "project_path")
    @classmethod
    def strip_project_payload_strings(cls, value: str) -> str:
        return value.strip()


class CodexThreadProjectAssignment(BaseModel):
    project_id: str
    project_kind: CodexProjectKind
    host_id: str = "local"
    cwd: str

    @field_validator("project_id", "host_id", "cwd")
    @classmethod
    def strip_assignment_strings(cls, value: str) -> str:
        return value.strip()


class CodexRemoteConnectionPayload(BaseModel):
    display_name: str = ""
    ssh_host: str = ""
    ssh_username: str = ""
    ssh_port: int | None = None
    ssh_alias: str = ""
    identity_file: str = ""
    auto_connect: bool = False

    @field_validator(
        "display_name",
        "ssh_host",
        "ssh_username",
        "ssh_alias",
        "identity_file",
    )
    @classmethod
    def strip_payload_strings(cls, value: str) -> str:
        return value.strip()


class CodexRemoteConnectionAutoConnectPayload(BaseModel):
    auto_connect: bool


class CodexRemoteConnectionResponse(BaseModel):
    connection: CodexRemoteConnection


class CodexSshConfigHost(BaseModel):
    alias: str
    hostname: str
    port: int | None = None
    identity_file: str = ""


class CodexSshConfigHostsResponse(BaseModel):
    hosts: list[CodexSshConfigHost] = Field(default_factory=list)


CodexRemoteConnectionRuntimeStatus = Literal[
    "connected",
    "connecting",
    "disconnected",
    "error",
]


class CodexRemoteConnectionStatus(BaseModel):
    status: CodexRemoteConnectionRuntimeStatus = "disconnected"
    detail: str = ""


class CodexRemoteConnectionsResponse(BaseModel):
    connections: list[CodexRemoteConnection] = Field(default_factory=list)
    active_connection_id: str = ""
    statuses: dict[str, CodexRemoteConnectionStatus] = Field(default_factory=dict)


class CodexRemoteConnectionTestResponse(BaseModel):
    ok: bool
    detail: str = ""


class WebSettings(BaseModel):
    llm: StoredLLMSettings = Field(default_factory=StoredLLMSettings)
    auth: StoredAuthSettings = Field(default_factory=StoredAuthSettings)
    speech: StoredSpeechSettings = Field(default_factory=StoredSpeechSettings)
    session_defaults: SessionDefaultsSettings = Field(
        default_factory=SessionDefaultsSettings
    )
    codex: StoredCodexSettings = Field(default_factory=StoredCodexSettings)
    allowed_roots: list[str] = Field(default_factory=list)


class BackendHealth(BaseModel):
    ready: bool
    detail: str | None = None


class BackendOption(BaseModel):
    id: BackendId
    label: str


class CodexConfigPayload(BaseModel):
    launcher_command: str = ""
    model: str = ""
    sandbox: CodexSandboxMode = "workspace-write"
    approval_policy: CodexApprovalPolicy = "on-request"
    approvals_reviewer: CodexApprovalsReviewer = "user"
    personality: CodexPersonality = "friendly"
    reasoning_effort: CodexReasoningEffort = "medium"
    show_reasoning_cards: bool = False
    service_tier: CodexServiceTier = ""
    active_remote_connection_id: str = ""
    remote_connections: list[CodexRemoteConnection] = Field(default_factory=list)
    projects: list[CodexProjectDefinition] = Field(default_factory=list)


class LLMConfigPayload(BaseModel):
    provider: LLMProvider = ""
    base_url: str = ""
    model: str = ""
    has_api_key: bool = False


class MCPRuntimeEntry(BaseModel):
    status: MCPRuntimeStatus
    tool_count: int = 0
    error: str | None = None


class FrontendHealth(BaseModel):
    ready: bool
    mode: FrontendMode
    detail: str | None = None


class LLMHealth(BaseModel):
    ready: bool
    detail: str | None = None


class MCPHealth(BaseModel):
    ready: bool
    detail: str | None = None
    runtime: dict[str, MCPRuntimeEntry] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    frontend: FrontendHealth
    llm: LLMHealth
    mcp: MCPHealth
    backends: dict[BackendId, BackendHealth] = Field(default_factory=dict)
    allowed_roots: list[str] = Field(default_factory=list)


class ConfigResponse(BaseModel):
    llm: LLMConfigPayload
    backends: list[BackendOption] = Field(default_factory=list)
    session_defaults: SessionDefaultsSettings = Field(
        default_factory=SessionDefaultsSettings
    )
    codex: CodexConfigPayload = Field(default_factory=CodexConfigPayload)
    allowed_roots: list[str] = Field(default_factory=list)
    mcp_runtime: dict[str, MCPRuntimeEntry] = Field(default_factory=dict)


class AuthSessionResponse(BaseModel):
    enabled: bool = False
    authenticated: bool = True


class AuthConfigResponse(BaseModel):
    enabled: bool = False
    has_password: bool = False
    has_secret: bool = False
    session_ttl_hours: int = 24 * 7
    password_source: AuthConfigSource = "default"
    secret_source: AuthConfigSource = "default"
    session_ttl_source: AuthConfigSource = "default"


class AuthLoginRequest(BaseModel):
    password: str = ""

    @field_validator("password")
    @classmethod
    def strip_password(cls, value: str) -> str:
        return value.strip()


class SaveAuthConfigRequest(BaseModel):
    enabled: bool = False
    password: str | None = None
    secret: str | None = None
    session_ttl_hours: int = Field(default=24 * 7, ge=1)

    @field_validator("password", "secret")
    @classmethod
    def strip_optional_auth_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class SpeechConfigResponse(BaseModel):
    model_dir: str = ""
    provider: str = "cpu"
    num_threads: int = 2
    status: Literal["ready", "missing"] = "missing"
    detail: str = ""
    model_dir_source: SpeechConfigSource = "default"
    provider_source: SpeechConfigSource = "default"
    num_threads_source: SpeechConfigSource = "default"


class SaveSpeechConfigRequest(BaseModel):
    model_dir: str = ""
    provider: str = "cpu"
    num_threads: int = Field(default=2, ge=1)

    @field_validator("model_dir", "provider")
    @classmethod
    def strip_speech_config_strings(cls, value: str) -> str:
        return value.strip()


class SaveLLMRequest(BaseModel):
    provider: LLMProvider = ""
    base_url: str
    model: str
    api_key: str | None = None

    @field_validator("base_url", "model")
    @classmethod
    def strip_required_fields(cls, value: str) -> str:
        return value.strip()


class SaveAllowedRootsRequest(BaseModel):
    allowed_roots: list[str]

    @field_validator("allowed_roots")
    @classmethod
    def validate_allowed_roots(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class MCPConfigResponse(BaseModel):
    mcp_servers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    runtime: dict[str, MCPRuntimeEntry] = Field(default_factory=dict)


class SaveMCPConfigRequest(BaseModel):
    mcp_servers: dict[str, dict[str, Any]]


class SaveAppSettingsRequest(BaseModel):
    session_defaults: SessionDefaultsSettings = Field(
        default_factory=SessionDefaultsSettings
    )
    codex: StoredCodexSettings = Field(default_factory=StoredCodexSettings)


class SelectDirectoryRequest(BaseModel):
    initial_path: str | None = None

    @field_validator("initial_path")
    @classmethod
    def strip_initial_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SelectDirectoryResponse(BaseModel):
    selected: bool = False
    project_path: str = ""


class ArchiveCodexSessionResponse(BaseModel):
    thread_id: str
    archived: bool = True


class CodexNativeSessionSummary(BaseModel):
    thread_id: str
    host_id: str = "local"
    title: str
    preview: str
    updated_at: float
    started_at: float
    status: str = "idle"
    cwd: str
    project: str
    project_path: str
    source: str = "active"
    model_provider: str = ""


class CodexPairingExtensionSummary(BaseModel):
    id: str
    app_name: str
    workspace_name: str
    extension_name: str
    extension_version: str
    bundle_id: str
    marketplace_id: str
    capability_names: list[str] = Field(default_factory=list)
    capability_count: int = 0
    socket_path: str
    is_online: bool = False
    needs_reload: bool = False
    last_seen_at: float = 0.0


class CodexProjectGroup(BaseModel):
    id: str
    project: str
    project_path: str
    host_id: str = "local"
    kind: CodexProjectKind = "local"
    root_paths: list[str] = Field(default_factory=list)
    session_count: int
    sessions: list[CodexNativeSessionSummary] = Field(default_factory=list)


class CodexWorkspaceResponse(BaseModel):
    projects: list[CodexProjectGroup] = Field(default_factory=list)
    recent_threads: list[CodexNativeSessionSummary] = Field(default_factory=list)
    recent_threads_next_cursors: dict[str, str] = Field(default_factory=dict)
    paired_editors: list[CodexPairingExtensionSummary] = Field(default_factory=list)
    remote_connections: list[CodexRemoteConnection] = Field(default_factory=list)
    active_remote_connection_id: str = ""
    remote_connection_statuses: dict[str, CodexRemoteConnectionStatus] = Field(
        default_factory=dict
    )


class CodexRecentThreadsPage(BaseModel):
    threads: list[CodexNativeSessionSummary] = Field(default_factory=list)
    next_cursors: dict[str, str] = Field(default_factory=dict)


CodexFilesystemEntryKind = Literal["directory", "file", "other"]


class CodexFilesystemEntry(BaseModel):
    name: str
    path: str
    kind: CodexFilesystemEntryKind
    extension: str = ""
    readable: bool = True


class CodexFilesystemResponse(BaseModel):
    path: str
    parent_path: str | None = None
    roots: list[CodexFilesystemEntry] = Field(default_factory=list)
    entries: list[CodexFilesystemEntry] = Field(default_factory=list)


class CodexThreadCreateRequest(BaseModel):
    project_path: str | None = None
    host_id: str = "local"

    @field_validator("project_path")
    @classmethod
    def strip_project_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("host_id")
    @classmethod
    def strip_host_id(cls, value: str) -> str:
        return value.strip() or "local"


class CodexThreadCreateResponse(BaseModel):
    thread_id: str
    host_id: str = "local"
    state: dict[str, Any] | None = None


class CodexThreadStateResponse(BaseModel):
    thread_id: str
    state: dict[str, Any] | None = None


class CodexThreadNameRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()
