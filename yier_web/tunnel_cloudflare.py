from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml


class TunnelError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteTunnel:
    account_id: str
    tunnel_id: str
    name: str
    hostname: str
    origin: str
    connector_token: str


class CloudflareApiClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.cloudflare.com/client/v4",
        client: httpx.Client | None = None,
    ) -> None:
        if not token.strip():
            raise TunnelError("The Cloudflare API token is empty.")
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self.client = client

    def resolve_tunnel(
        self,
        name: str,
        *,
        account_id: str | None = None,
        hostname: str | None = None,
    ) -> RemoteTunnel:
        normalized_name = name.strip()
        if not normalized_name:
            raise TunnelError("A Cloudflare tunnel name is required.")

        account_ids = [account_id.strip()] if account_id else self._list_account_ids()
        matches: list[tuple[str, dict[str, Any]]] = []
        for current_account_id in account_ids:
            result = self._request(
                f"/accounts/{current_account_id}/cfd_tunnel",
                params={"name": normalized_name, "is_deleted": "false"},
            )
            if not isinstance(result, list):
                continue
            for tunnel in result:
                if (
                    isinstance(tunnel, dict)
                    and tunnel.get("name") == normalized_name
                    and isinstance(tunnel.get("id"), str)
                ):
                    matches.append((current_account_id, tunnel))

        if not matches:
            raise TunnelError(f"Cloudflare tunnel '{normalized_name}' was not found.")
        if len(matches) > 1:
            raise TunnelError(
                f"Cloudflare tunnel '{normalized_name}' exists in multiple accounts; "
                "use --account-id."
            )

        resolved_account_id, tunnel = matches[0]
        tunnel_id = str(tunnel["id"])
        configuration = self._request(
            f"/accounts/{resolved_account_id}/cfd_tunnel/{tunnel_id}/configurations"
        )
        resolved_hostname, origin = resolve_remote_ingress(
            configuration,
            requested_hostname=hostname,
        )
        connector_token = self._request(
            f"/accounts/{resolved_account_id}/cfd_tunnel/{tunnel_id}/token"
        )
        if not isinstance(connector_token, str) or not connector_token.strip():
            raise TunnelError("Cloudflare returned an empty connector token.")
        return RemoteTunnel(
            account_id=resolved_account_id,
            tunnel_id=tunnel_id,
            name=normalized_name,
            hostname=resolved_hostname,
            origin=origin,
            connector_token=connector_token.strip(),
        )

    def _list_account_ids(self) -> list[str]:
        result = self._request("/accounts", params={"per_page": "100"})
        if not isinstance(result, list):
            raise TunnelError("Cloudflare returned an invalid account list.")
        account_ids = [
            account["id"]
            for account in result
            if isinstance(account, dict) and isinstance(account.get("id"), str)
        ]
        if not account_ids:
            raise TunnelError(
                "No Cloudflare account is available to this token; use --account-id "
                "if the token cannot list accounts."
            )
        return account_ids

    def _request(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            if self.client is not None:
                response = self.client.get(path, headers=headers, params=params)
            else:
                with httpx.Client(base_url=self.base_url, timeout=15) as client:
                    response = client.get(path, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TunnelError(
                f"Cloudflare API request failed for {path}: {exc}"
            ) from exc

        if not isinstance(payload, dict) or payload.get("success") is not True:
            detail = _cloudflare_error_detail(payload)
            raise TunnelError(f"Cloudflare API rejected {path}: {detail}")
        return payload.get("result")


def resolve_remote_ingress(
    configuration: Any,
    *,
    requested_hostname: str | None,
) -> tuple[str, str]:
    requested = normalize_hostname(requested_hostname)
    config = configuration.get("config") if isinstance(configuration, dict) else None
    ingress = config.get("ingress") if isinstance(config, dict) else None
    if not isinstance(ingress, list):
        raise TunnelError(
            "The Cloudflare tunnel has no readable ingress configuration."
        )

    candidates: list[tuple[str, str]] = []
    for rule in ingress:
        if not isinstance(rule, dict):
            continue
        rule_hostname = normalize_hostname(rule.get("hostname"))
        service = rule.get("service")
        if rule_hostname and isinstance(service, str) and _is_http_origin(service):
            candidates.append((rule_hostname, normalize_origin(service)))
    if requested:
        for rule_hostname, service in candidates:
            if rule_hostname == requested:
                return rule_hostname, service
        raise TunnelError(
            f"Hostname '{requested}' is not configured on this Cloudflare tunnel."
        )
    if not candidates:
        raise TunnelError("The Cloudflare tunnel has no HTTP ingress hostname.")
    return candidates[0]


def inspect_local_config(
    config_path: Path,
    *,
    requested_hostname: str | None,
) -> tuple[str | None, str | None]:
    if not config_path.is_file():
        raise TunnelError(f"Cloudflare tunnel config does not exist: {config_path}")
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TunnelError(
            f"Unable to read Cloudflare tunnel config: {config_path}"
        ) from exc

    requested = normalize_hostname(requested_hostname)
    ingress = payload.get("ingress") if isinstance(payload, dict) else None
    candidates: list[tuple[str, str | None]] = []
    if isinstance(ingress, list):
        for rule in ingress:
            if not isinstance(rule, dict):
                continue
            rule_hostname = normalize_hostname(rule.get("hostname"))
            service = rule.get("service")
            if not rule_hostname:
                continue
            origin = (
                normalize_origin(service)
                if isinstance(service, str) and _is_http_origin(service)
                else None
            )
            candidates.append((rule_hostname, origin))
    if requested:
        for rule_hostname, origin in candidates:
            if rule_hostname == requested:
                return rule_hostname, origin
        raise TunnelError(f"Hostname '{requested}' is not configured in {config_path}.")
    return candidates[0] if candidates else (None, None)


def normalize_hostname(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if "://" in normalized:
        parsed = urlsplit(normalized)
        normalized = parsed.hostname or ""
    normalized = normalized.rstrip(".").lower()
    if (
        not normalized
        or "/" in normalized
        or any(char.isspace() for char in normalized)
    ):
        raise TunnelError(f"Invalid tunnel hostname: {value}")
    return normalized


def normalize_origin(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise TunnelError("The local origin is empty.")
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise TunnelError(f"Invalid local origin: {value}")
    return normalized


def read_secret(path: Path, description: str) -> str:
    try:
        value = path.expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TunnelError(f"Unable to read {description} file: {path}") from exc
    if not value:
        raise TunnelError(f"The {description} file is empty: {path}")
    return value


def _is_http_origin(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _cloudflare_error_detail(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "invalid response"
    errors = payload.get("errors")
    if isinstance(errors, list):
        messages = [
            error.get("message")
            for error in errors
            if isinstance(error, dict) and isinstance(error.get("message"), str)
        ]
        if messages:
            return "; ".join(messages)
    return "unknown Cloudflare API error"
