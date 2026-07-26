from __future__ import annotations

import json
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_python_and_npm_launcher_versions_match() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    npm_package = json.loads(
        (PROJECT_ROOT / "packages" / "npm-launcher" / "package.json").read_text(
            encoding="utf-8"
        )
    )

    assert npm_package["version"] == pyproject["project"]["version"]


def test_python_distribution_only_installs_public_command() -> None:
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["scripts"] == {
        "open-codex-ui": "yier_web.cli:main"
    }
