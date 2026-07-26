from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from yier_web.ssh_config import discover_ssh_config_hosts


def test_discover_ssh_config_hosts_returns_empty_for_missing_config(
    tmp_path: Path,
) -> None:
    assert discover_ssh_config_hosts(home_dir=tmp_path) == []


def test_discover_ssh_config_hosts_resolves_concrete_hosts_and_includes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssh_dir = tmp_path / ".ssh"
    included_dir = ssh_dir / "config.d"
    included_dir.mkdir(parents=True)
    (ssh_dir / "config").write_text(
        "Include=config.d/*.conf\nHost prod *.internal !blocked dev?\nHost=equals-style\n",
        encoding="utf-8",
    )
    (included_dir / "work.conf").write_text(
        "Include nested.conf\nHost staging prod\n",
        encoding="utf-8",
    )
    (ssh_dir / "nested.conf").write_text("Host nested\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        alias = command[-1]
        if alias == "prod":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="invalid")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                f"hostname {alias}.example.com\n"
                "port 2222\n"
                "identityfile ~/.ssh/id_ed25519\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("yier_web.ssh_config.subprocess.run", fake_run)

    hosts = discover_ssh_config_hosts(home_dir=tmp_path)

    assert [host.alias for host in hosts] == ["nested", "staging", "equals-style"]
    assert hosts[0].hostname == "nested.example.com"
    assert hosts[0].port == 2222
    assert hosts[0].identity_file == "~/.ssh/id_ed25519"
    assert [command[-1] for command in calls] == [
        "nested",
        "staging",
        "prod",
        "equals-style",
    ]
    assert all(
        command[:4] == ["ssh", "-G", "-F", str(ssh_dir / "config")] for command in calls
    )
