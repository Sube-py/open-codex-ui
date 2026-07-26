import os

from granian.constants import Interfaces

from main import build_server


def test_build_server_configures_granian_shutdown_timeout() -> None:
    server = build_server()

    assert server.target == "main:build_app"
    assert server.bind_addr == "0.0.0.0"
    assert server.bind_port == 13140
    assert server.interface == Interfaces.ASGI
    assert server.factory is True
    assert server.workers_kill_timeout == 5


def test_build_server_sets_debug_environment() -> None:
    build_server(debug=True)
    assert os.environ["YIER_DEBUG"] == "1"

    build_server(debug=False)
    assert os.environ["YIER_DEBUG"] == "0"
