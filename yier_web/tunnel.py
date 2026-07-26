from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any, Callable

import httpx

from yier_web.tunnel_cloudflare import (
    CloudflareApiClient,
    TunnelError,
    inspect_local_config,
    normalize_hostname,
    normalize_origin,
    read_secret,
)


DEFAULT_ORIGIN = "http://127.0.0.1:13140"
DEFAULT_STARTUP_TIMEOUT = 30.0
QUICK_URL_PATTERN = re.compile(
    r"https://[a-z0-9-]+\.trycloudflare\.com",
    re.IGNORECASE,
)
READY_PATTERNS = (
    re.compile(r"registered tunnel connection", re.IGNORECASE),
    re.compile(r"connection[^\n]*registered", re.IGNORECASE),
    re.compile(r"starting metrics server", re.IGNORECASE),
    re.compile(r"connected to edge", re.IGNORECASE),
)
FATAL_PATTERNS = (
    re.compile(r"invalid token", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"credentials file.*doesn't exist", re.IGNORECASE),
    re.compile(r"cannot find.*config", re.IGNORECASE),
    re.compile(r"failed to (?:read|load|parse).*config", re.IGNORECASE),
)


class TunnelManager:
    def __init__(
        self,
        runtime_dir: Path | None = None,
        *,
        home_dir: Path | None = None,
        environment: dict[str, str] | None = None,
        process_factory: Callable[..., subprocess.Popen[bytes]] | None = None,
        api_client_factory: Callable[[str], CloudflareApiClient] | None = None,
    ) -> None:
        self.home_dir = (home_dir or Path.home()).expanduser().resolve()
        self.runtime_dir = (
            (runtime_dir or self.home_dir / ".yier" / "web").expanduser().resolve()
        )
        self.state_path = self.runtime_dir / "open-codex-ui-tunnel.json"
        self.log_path = self.runtime_dir / "open-codex-ui-tunnel.log"
        self.pid_path = self.runtime_dir / "open-codex-ui-tunnel.pid"
        self.environment = environment if environment is not None else dict(os.environ)
        self.process_factory = process_factory or subprocess.Popen
        self.api_client_factory = api_client_factory or CloudflareApiClient

    def start(
        self,
        *,
        mode: str,
        origin: str | None = None,
        name: str | None = None,
        hostname: str | None = None,
        token_file: Path | None = None,
        api_token_file: Path | None = None,
        account_id: str | None = None,
        config: Path | None = None,
        timeout: float = DEFAULT_STARTUP_TIMEOUT,
    ) -> int:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        current_state = self._load_state()
        if current_state is not None and self._is_owned_process(current_state):
            raise TunnelError(
                "An Open Codex UI tunnel is already running; stop it before starting another."
            )
        if current_state is not None:
            self._cleanup_state(current_state)

        executable = self._resolve_cloudflared()
        normalized_mode = mode.strip().lower()
        state_details: dict[str, Any]
        temporary_dir: Path | None = None
        secret_path: Path | None = None

        if normalized_mode == "quick":
            resolved_origin = normalize_origin(origin or DEFAULT_ORIGIN)
            self._require_reachable_origin(resolved_origin)
            temporary_dir = self._make_temporary_dir("quick")
            command = self._base_command(executable) + ["--url", resolved_origin]
            process_environment = {**self.environment, "HOME": str(temporary_dir)}
            state_details = {"origin": resolved_origin, "hostname": None, "name": None}
        elif normalized_mode == "managed-remote":
            (
                connector_token,
                resolved_hostname,
                resolved_origin,
                resolved_name,
            ) = self._resolve_managed_remote(
                name=name,
                hostname=hostname,
                origin=origin,
                token_file=token_file,
                api_token_file=api_token_file,
                account_id=account_id,
            )
            if resolved_origin is not None:
                self._require_reachable_origin(resolved_origin)
            temporary_dir = self._make_temporary_dir("token")
            secret_path = temporary_dir / "connector-token"
            try:
                secret_path.write_text(connector_token, encoding="utf-8")
                secret_path.chmod(0o600)
            except OSError as exc:
                self._cleanup_temporary_dir(temporary_dir)
                raise TunnelError(
                    "Unable to create a temporary connector token file."
                ) from exc
            command = self._base_command(executable) + [
                "run",
                "--token-file",
                str(secret_path),
            ]
            process_environment = dict(self.environment)
            state_details = {
                "origin": resolved_origin,
                "hostname": resolved_hostname,
                "name": resolved_name,
            }
        elif normalized_mode == "managed-local":
            config_path = (
                config.expanduser().resolve()
                if config is not None
                else self.home_dir / ".cloudflared" / "config.yml"
            )
            resolved_hostname, resolved_origin = inspect_local_config(
                config_path,
                requested_hostname=hostname,
            )
            if resolved_origin is not None:
                self._require_reachable_origin(resolved_origin)
            command = self._base_command(executable, config=config_path) + ["run"]
            process_environment = dict(self.environment)
            state_details = {
                "origin": resolved_origin,
                "hostname": resolved_hostname,
                "name": None,
                "config": str(config_path),
            }
        else:
            raise TunnelError(f"Unsupported tunnel mode: {mode}")

        process_environment["CF_TELEMETRY_DISABLE"] = "1"
        process: subprocess.Popen[bytes] | None = None
        try:
            process = self._spawn(command, process_environment)
            public_url = self._wait_for_ready(
                process,
                mode=normalized_mode,
                hostname=state_details.get("hostname"),
                timeout=timeout,
            )
            if secret_path is not None:
                secret_path.unlink(missing_ok=True)
                if temporary_dir is not None:
                    self._cleanup_temporary_dir(temporary_dir)
                    temporary_dir = None

            state = {
                "version": 1,
                "pid": process.pid,
                "mode": normalized_mode,
                "url": public_url,
                "executable": str(executable),
                "started_at": datetime.now(UTC).isoformat(),
                "temporary_dir": str(temporary_dir) if temporary_dir else None,
                **state_details,
            }
            self._write_state(state)
        except Exception:
            if process is not None:
                self._terminate_started_process(process)
            if temporary_dir is not None:
                self._cleanup_temporary_dir(temporary_dir)
            self.pid_path.unlink(missing_ok=True)
            raise

        print(f"Started Cloudflare {normalized_mode} tunnel (PID {process.pid}).")
        if public_url:
            print(f"Public URL: {public_url}")
        if state_details.get("origin"):
            print(f"Origin: {state_details['origin']}")
        print(f"Logs: {self.log_path}")
        return 0

    def status(self) -> int:
        state = self._load_state()
        if state is None:
            print("No Open Codex UI tunnel is running.")
            return 1
        if not self._is_owned_process(state):
            self._cleanup_state(state)
            print("The Open Codex UI tunnel is not running; removed stale state.")
            return 1

        pid = state.get("pid")
        mode = state.get("mode", "unknown")
        print(f"Cloudflare {mode} tunnel is running (PID {pid}).")
        if isinstance(state.get("url"), str):
            print(f"Public URL: {state['url']}")
        if isinstance(state.get("origin"), str):
            print(f"Origin: {state['origin']}")
        print(f"Logs: {self.log_path}")
        return 0

    def stop(self) -> int:
        state = self._load_state()
        if state is None:
            print("No Open Codex UI tunnel is running.")
            return 0
        if not self._is_owned_process(state):
            self._cleanup_state(state)
            print("The Open Codex UI tunnel was already stopped; removed stale state.")
            return 0

        pid = int(state["pid"])
        self._terminate_owned_process(pid)
        self._cleanup_state(state)
        print("Stopped the Open Codex UI tunnel.")
        return 0

    def _resolve_managed_remote(
        self,
        *,
        name: str | None,
        hostname: str | None,
        origin: str | None,
        token_file: Path | None,
        api_token_file: Path | None,
        account_id: str | None,
    ) -> tuple[str, str, str | None, str | None]:
        if token_file is not None:
            connector_token = read_secret(token_file, "connector token")
            resolved_hostname = normalize_hostname(hostname)
            if resolved_hostname is None:
                raise TunnelError("--hostname is required with --token-file.")
            resolved_origin = normalize_origin(origin) if origin else None
            return connector_token, resolved_hostname, resolved_origin, name

        if not name:
            raise TunnelError(
                "Managed remote mode requires --name or a connector --token-file."
            )
        if api_token_file is not None:
            api_token = read_secret(api_token_file, "Cloudflare API token")
        else:
            api_token = self.environment.get("CF_TOKEN", "").strip()
        if not api_token:
            raise TunnelError(
                "CF_TOKEN or --api-token-file is required to resolve a named tunnel."
            )
        resolved_account_id = account_id or self.environment.get("CF_ACCOUNT_ID")
        remote = self.api_client_factory(api_token).resolve_tunnel(
            name,
            account_id=resolved_account_id,
            hostname=hostname,
        )
        resolved_origin = normalize_origin(origin) if origin else remote.origin
        return remote.connector_token, remote.hostname, resolved_origin, remote.name

    def _base_command(
        self,
        executable: Path,
        *,
        config: Path | None = None,
    ) -> list[str]:
        command = [
            str(executable),
            "tunnel",
            "--no-autoupdate",
            "--pidfile",
            str(self.pid_path),
        ]
        if config is not None:
            command.extend(["--config", str(config)])
        return command

    def _spawn(
        self,
        command: list[str],
        environment: dict[str, str],
    ) -> subprocess.Popen[bytes]:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.unlink(missing_ok=True)
        with self.log_path.open("wb") as log_file:
            try:
                return self.process_factory(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    start_new_session=True,
                )
            except OSError as exc:
                raise TunnelError(f"Unable to start cloudflared: {exc}") from exc

    def _wait_for_ready(
        self,
        process: subprocess.Popen[bytes],
        *,
        mode: str,
        hostname: str | None,
        timeout: float,
    ) -> str | None:
        deadline = time.monotonic() + timeout
        fallback_deadline = time.monotonic() + min(6, timeout)
        quick_url: str | None = None
        managed_ready = False
        while time.monotonic() < deadline:
            log_text = self._read_log_tail()
            if mode == "quick":
                match = QUICK_URL_PATTERN.search(log_text)
                if match:
                    quick_url = match.group(0)
            elif any(pattern.search(log_text) for pattern in READY_PATTERNS):
                managed_ready = True

            if any(pattern.search(log_text) for pattern in FATAL_PATTERNS):
                raise TunnelError(
                    f"cloudflared rejected the tunnel; see {self.log_path}."
                )
            return_code = process.poll()
            if return_code is not None:
                raise TunnelError(
                    f"cloudflared exited with code {return_code}; see {self.log_path}."
                )
            pid_ready = self._pid_file_matches(process.pid)
            if mode == "quick" and quick_url and pid_ready:
                return quick_url
            if (
                mode != "quick"
                and pid_ready
                and (managed_ready or time.monotonic() >= fallback_deadline)
            ):
                return f"https://{hostname}" if hostname else None
            time.sleep(0.2)
        raise TunnelError(f"Timed out waiting for cloudflared; see {self.log_path}.")

    def _require_reachable_origin(self, origin: str) -> None:
        try:
            with httpx.Client(timeout=3, follow_redirects=False) as client:
                response = client.get(origin)
            if response.status_code >= 500:
                raise TunnelError(
                    f"The local origin returned HTTP {response.status_code}: {origin}"
                )
        except httpx.HTTPError as exc:
            raise TunnelError(
                f"The local origin is not reachable: {origin} ({exc})"
            ) from exc

    def _resolve_cloudflared(self) -> Path:
        executable = shutil.which("cloudflared", path=self.environment.get("PATH"))
        if executable is None:
            raise TunnelError(
                "cloudflared is required. Install it from "
                "https://developers.cloudflare.com/cloudflare-one/networks/"
                "connectors/cloudflared/downloads/."
            )
        return Path(executable).resolve()

    def _is_owned_process(self, state: dict[str, Any]) -> bool:
        pid = state.get("pid")
        if not isinstance(pid, int) or pid <= 0 or not _process_exists(pid):
            return False
        if not self._pid_file_matches(pid):
            return False
        if os.name != "posix":
            return True
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            check=False,
            text=True,
        )
        return (
            result.returncode == 0
            and "cloudflared" in result.stdout
            and str(self.pid_path) in result.stdout
        )

    def _pid_file_matches(self, pid: int) -> bool:
        try:
            recorded_pid = int(self.pid_path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, OSError, ValueError):
            return False
        return recorded_pid == pid

    def _terminate_owned_process(self, pid: int) -> None:
        if os.name == "posix":
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not _process_exists(pid):
                return
            time.sleep(0.1)
        if os.name == "posix":
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)

    def _terminate_started_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()

    def _load_state(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_state(self, state: dict[str, Any]) -> None:
        temporary_path = self.state_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.chmod(0o600)
        temporary_path.replace(self.state_path)

    def _cleanup_state(self, state: dict[str, Any]) -> None:
        temporary_dir = state.get("temporary_dir")
        if isinstance(temporary_dir, str):
            self._cleanup_temporary_dir(Path(temporary_dir))
        self.state_path.unlink(missing_ok=True)
        self.pid_path.unlink(missing_ok=True)

    def _make_temporary_dir(self, purpose: str) -> Path:
        path = Path(
            tempfile.mkdtemp(
                prefix=f"open-codex-ui-tunnel-{purpose}-",
                dir=self.runtime_dir,
            )
        )
        path.chmod(0o700)
        return path

    def _cleanup_temporary_dir(self, path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if resolved.parent == self.runtime_dir and resolved.name.startswith(
            "open-codex-ui-tunnel-"
        ):
            shutil.rmtree(resolved, ignore_errors=True)

    def _read_log_tail(self) -> str:
        try:
            with self.log_path.open("rb") as log_file:
                log_file.seek(0, os.SEEK_END)
                size = log_file.tell()
                log_file.seek(max(0, size - 128 * 1024))
                return log_file.read().decode("utf-8", errors="replace")
        except OSError:
            return ""


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
