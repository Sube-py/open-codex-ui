from __future__ import annotations

import glob
import shlex
import subprocess
from pathlib import Path

from yier_web.schemas import CodexSshConfigHost


_HOST_PATTERN_CHARACTERS = frozenset("!*?[]")


def discover_ssh_config_hosts(
    config_path: Path | None = None,
    *,
    home_dir: Path | None = None,
) -> list[CodexSshConfigHost]:
    home = (home_dir or Path.home()).expanduser().resolve()
    ssh_config_path = (config_path or home / ".ssh" / "config").expanduser()
    aliases = _collect_aliases(
        ssh_config_path,
        include_root=ssh_config_path.parent,
        home_dir=home,
    )
    hosts: list[CodexSshConfigHost] = []
    for alias in aliases:
        resolved = _resolve_alias(ssh_config_path, alias)
        if resolved is not None:
            hosts.append(resolved)
    return hosts


def _collect_aliases(
    config_path: Path,
    *,
    include_root: Path,
    home_dir: Path,
    visited: set[Path] | None = None,
) -> list[str]:
    visited_paths = visited if visited is not None else set()
    try:
        resolved_path = config_path.resolve(strict=True)
    except OSError:
        return []
    if resolved_path in visited_paths or not resolved_path.is_file():
        return []
    visited_paths.add(resolved_path)

    try:
        lines = resolved_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    aliases: list[str] = []
    for line in lines:
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not tokens:
            continue

        directive, separator, attached_value = tokens[0].partition("=")
        directive = directive.casefold()
        values = ([attached_value] if separator and attached_value else []) + tokens[1:]
        if directive == "include":
            for pattern in values:
                for included_path in _expand_include_paths(
                    pattern,
                    include_root=include_root,
                    home_dir=home_dir,
                ):
                    aliases.extend(
                        _collect_aliases(
                            included_path,
                            include_root=include_root,
                            home_dir=home_dir,
                            visited=visited_paths,
                        )
                    )
            continue
        if directive != "host":
            continue
        aliases.extend(alias for alias in values if _is_concrete_alias(alias))

    return list(dict.fromkeys(aliases))


def _expand_include_paths(
    pattern: str,
    *,
    include_root: Path,
    home_dir: Path,
) -> list[Path]:
    if pattern == "~":
        expanded = home_dir
    elif pattern.startswith("~/"):
        expanded = home_dir / pattern[2:]
    else:
        expanded = Path(pattern)
        if not expanded.is_absolute():
            expanded = include_root / expanded
    return [Path(path) for path in sorted(glob.glob(str(expanded)))]


def _is_concrete_alias(alias: str) -> bool:
    return bool(alias) and not any(
        character in alias for character in _HOST_PATTERN_CHARACTERS
    )


def _resolve_alias(config_path: Path, alias: str) -> CodexSshConfigHost | None:
    try:
        completed = subprocess.run(
            ["ssh", "-G", "-F", str(config_path), alias],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    values: dict[str, list[str]] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition(" ")
        normalized_value = value.strip()
        if separator and normalized_value:
            values.setdefault(key.casefold(), []).append(normalized_value)

    hostname = _first_value(values, "hostname")
    if not hostname:
        return None
    port_value = _first_value(values, "port")
    try:
        port = int(port_value) if port_value else None
    except ValueError:
        port = None
    return CodexSshConfigHost(
        alias=alias,
        hostname=hostname,
        port=port,
        identity_file=_first_value(values, "identityfile"),
    )


def _first_value(values: dict[str, list[str]], key: str) -> str:
    candidates = values.get(key, [])
    return candidates[0] if candidates else ""
