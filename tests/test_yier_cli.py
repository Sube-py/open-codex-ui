from __future__ import annotations

from typing import Any

import pytest

from yier_web import cli


class FakeServer:
    def __init__(self) -> None:
        self.served = False

    def serve(self) -> None:
        self.served = True


def test_prod_starts_with_safe_production_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    server = FakeServer()

    def fake_build_server(**kwargs: Any) -> FakeServer:
        captured.update(kwargs)
        return server

    monkeypatch.setattr(cli, "build_server", fake_build_server)
    monkeypatch.setattr("sys.argv", ["open-codex-ui"])

    assert cli.prod() == 0
    assert captured == {
        "host": "127.0.0.1",
        "port": 9999,
        "debug": False,
        "reload": False,
    }
    assert server.served is True
