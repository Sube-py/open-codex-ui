from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import PurePosixPath
import secrets
import time
from typing import TYPE_CHECKING, Any

from litestar import Request
from litestar.response import Redirect, Response

from yier_web.schemas import AuthConfigResponse, SaveAuthConfigRequest

if TYPE_CHECKING:
    from yier_web.config import AppConfigService


AUTH_COOKIE_NAME = "yier_auth_session"
CODEX_EMBED_TOKEN_ENV = "YIER_CODEX_EMBED_TOKEN"
DEFAULT_SESSION_TTL_HOURS = 24 * 7
PBKDF2_HASH_PREFIX = "pbkdf2_sha256"
PBKDF2_DEFAULT_ITERATIONS = 600_000
PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/session",
}
PUBLIC_FRONTEND_PATHS = {
    "/login",
    "/codex/embed",
    "/__vite_ping",
    "/vite.svg",
}
PUBLIC_FRONTEND_PREFIXES = (
    "/assets/",
    "/@id/",
    "/@vite/",
    "/src/",
    "/node_modules/",
)


def hash_password(password: str, *, iterations: int = PBKDF2_DEFAULT_ITERATIONS) -> str:
    normalized_password = password.strip()
    if not normalized_password:
        raise ValueError("Password cannot be empty.")
    if iterations <= 0:
        raise ValueError("Iterations must be positive.")

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized_password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"{PBKDF2_HASH_PREFIX}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    parts = password_hash.split("$", 3)
    if len(parts) != 4:
        return False

    algorithm, raw_iterations, salt, expected_digest = parts
    if algorithm != PBKDF2_HASH_PREFIX:
        return False

    try:
        iterations = int(raw_iterations)
    except ValueError:
        return False

    if iterations <= 0 or not salt or not expected_digest:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.strip().encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual_digest, expected_digest)


def _env_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


class AuthService:
    def __init__(self, config_service: AppConfigService | None = None) -> None:
        self._config_service = config_service
        self._password = ""
        self._password_hash = ""
        self._secret = ""
        self._password_source = "default"
        self._secret_source = "default"
        self._session_ttl_source = "default"
        self._session_ttl_hours = DEFAULT_SESSION_TTL_HOURS
        self.reload()

    def reload(self) -> None:
        stored = (
            self._config_service.load_web_settings().auth
            if self._config_service is not None
            else None
        )
        stored_password_hash = stored.password_hash if stored is not None else ""
        stored_secret = stored.secret if stored is not None else ""
        stored_ttl_hours = (
            stored.session_ttl_hours
            if stored is not None
            else DEFAULT_SESSION_TTL_HOURS
        )

        env_password = os.getenv("YIER_AUTH_PASSWORD", "").strip()
        env_password_hash = os.getenv("YIER_AUTH_PASSWORD_HASH", "").strip()
        if env_password_hash or env_password:
            self._password = env_password
            self._password_hash = env_password_hash
            self._password_source = "environment"
        else:
            self._password = ""
            self._password_hash = stored_password_hash
            self._password_source = "settings" if stored_password_hash else "default"

        env_secret = os.getenv("YIER_AUTH_SECRET", "").strip()
        if env_secret:
            self._secret = env_secret
            self._secret_source = "environment"
        else:
            self._secret = stored_secret
            self._secret_source = "settings" if stored_secret else "default"

        raw_env_ttl = os.getenv("YIER_AUTH_SESSION_TTL_HOURS", "").strip()
        if raw_env_ttl:
            self._session_ttl_hours = _env_positive_int(
                "YIER_AUTH_SESSION_TTL_HOURS", DEFAULT_SESSION_TTL_HOURS
            )
            self._session_ttl_source = "environment"
        else:
            self._session_ttl_hours = stored_ttl_hours
            self._session_ttl_source = (
                "settings" if stored is not None else "default"
            )
        self._codex_embed_token = os.getenv(CODEX_EMBED_TOKEN_ENV, "").strip()
        self._session_ttl_seconds = self._session_ttl_hours * 3600

    def public_config(self) -> AuthConfigResponse:
        return AuthConfigResponse(
            enabled=self.enabled,
            has_password=self.enabled,
            has_secret=bool(self._secret),
            session_ttl_hours=self._session_ttl_hours,
            password_source=self._password_source,
            secret_source=self._secret_source,
            session_ttl_source=self._session_ttl_source,
        )

    def save_config(self, payload: SaveAuthConfigRequest) -> AuthConfigResponse:
        if self._config_service is None:
            raise RuntimeError("Authentication settings storage is unavailable.")

        stored = self._config_service.load_web_settings().auth
        environment_has_password = self._password_source == "environment"
        requested_has_password = bool(payload.password or stored.password_hash)
        if payload.enabled and not (
            environment_has_password or requested_has_password
        ):
            raise ValueError("A password is required to enable authentication.")

        self._config_service.save_auth_settings(payload)
        self.reload()
        return self.public_config()

    @property
    def enabled(self) -> bool:
        return bool(self._password or self._password_hash)

    def session_payload(self, request: Request) -> dict[str, bool]:
        return {
            "enabled": self.enabled,
            "authenticated": self.is_authenticated(request),
        }

    def is_public_path(self, path: str) -> bool:
        if path in PUBLIC_API_PATHS or path in PUBLIC_FRONTEND_PATHS:
            return True
        if any(path.startswith(prefix) for prefix in PUBLIC_FRONTEND_PREFIXES):
            return True
        if path.startswith("/api/"):
            return False
        return bool(PurePosixPath(path).suffix)

    def is_authenticated(self, request: Request) -> bool:
        if not self.enabled:
            return True

        return self._is_authenticated_cookie(request.cookies)

    def is_codex_embed_token_valid(self, token: str | None) -> bool:
        if not self._codex_embed_token:
            return False
        return hmac.compare_digest((token or "").strip(), self._codex_embed_token)

    def is_codex_websocket_authorized(self, connection: Any) -> bool:
        return self.is_websocket_authorized(connection)

    def is_websocket_authorized(self, connection: Any) -> bool:
        if not self.enabled:
            return True
        if self._is_authenticated_cookie(getattr(connection, "cookies", {})):
            return True
        query_params = getattr(connection, "query_params", {})
        return self.is_codex_embed_token_valid(query_params.get("embed_token"))

    def _is_authenticated_cookie(self, cookies: Any) -> bool:
        token = cookies.get(AUTH_COOKIE_NAME)
        if not token:
            return False

        return self._verify_session_token(token)

    def verify_login_password(self, password: str) -> bool:
        if not self.enabled:
            return True
        if self._password_hash:
            return verify_password(password, self._password_hash)
        return hmac.compare_digest(password.strip(), self._password)

    def build_login_response(self, request: Request) -> Response:
        return self.build_authenticated_response(
            request,
            {"enabled": self.enabled, "authenticated": True},
        )

    def build_authenticated_response(
        self,
        request: Request,
        content: dict[str, Any],
    ) -> Response:
        response = Response(content=content)
        if self.enabled:
            response.set_cookie(
                key=AUTH_COOKIE_NAME,
                value=self._build_session_token(),
                max_age=self._session_ttl_seconds,
                path="/",
                secure=self._request_is_secure(request),
                httponly=True,
                samesite="lax",
            )
        else:
            response.delete_cookie(AUTH_COOKIE_NAME, path="/")
        return response

    def build_logout_response(self, request: Request) -> Response:
        response = Response(
            content={
                "enabled": self.enabled,
                "authenticated": not self.enabled,
            }
        )
        response.delete_cookie(
            AUTH_COOKIE_NAME,
            path="/",
        )
        return response

    def build_unauthorized_api_response(self) -> Response:
        return Response(
            content={"detail": "Authentication required."},
            status_code=401,
        )

    def build_login_redirect(self, request: Request) -> Redirect:
        return Redirect(
            path="/login",
            query_params={"next": self._request_target(request)},
        )

    def _build_session_token(self) -> str:
        now = int(time.time())
        payload = {
            "exp": now + self._session_ttl_seconds,
            "iat": now,
            "nonce": secrets.token_urlsafe(12),
        }
        payload_bytes = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded_payload = _urlsafe_b64encode(payload_bytes)
        signature = hmac.new(
            self._signing_key(),
            encoded_payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_urlsafe_b64encode(signature)}"

    def _verify_session_token(self, token: str) -> bool:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
        except ValueError:
            return False

        expected_signature = hmac.new(
            self._signing_key(),
            encoded_payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        try:
            provided_signature = _urlsafe_b64decode(encoded_signature)
            payload_bytes = _urlsafe_b64decode(encoded_payload)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return False

        if not hmac.compare_digest(provided_signature, expected_signature):
            return False
        if not isinstance(payload, dict):
            return False

        expires_at = payload.get("exp")
        if not isinstance(expires_at, int):
            return False
        return expires_at >= int(time.time())

    def _signing_key(self) -> bytes:
        seed = self._secret or self._password_hash or self._password
        return hashlib.sha256(seed.encode("utf-8")).digest()

    def _request_is_secure(self, request: Request) -> bool:
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        normalized_proto = forwarded_proto.split(",", 1)[0].strip().lower()
        if normalized_proto:
            return normalized_proto == "https"
        return request.url.scheme == "https"

    def _request_target(self, request: Request) -> str:
        query = request.url.query
        return f"{request.url.path}?{query}" if query else request.url.path
