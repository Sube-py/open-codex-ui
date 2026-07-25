from __future__ import annotations

import asyncio
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from granian import Granian, loops
from granian.constants import Interfaces


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def web_root() -> Path:
    return project_root() / "web"


@loops.register("auto")
def build_loop():
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    return asyncio.new_event_loop()


def dev() -> int:
    parser = argparse.ArgumentParser(
        description="Start frontend and backend in development mode."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()

    frontend_process = _spawn_process(["pnpm", "dev"], cwd=web_root())
    backend_process = _spawn_process(
        [
            sys.executable,
            str(project_root() / "main.py"),
            "--debug",
            "--host",
            args.host,
            "--port",
            str(args.port),
            *(["--reload"] if not args.no_reload else []),
        ],
        cwd=project_root(),
    )

    try:
        return _wait_for_processes(
            [
                ("frontend", frontend_process),
                ("backend", backend_process),
            ]
        )
    finally:
        _terminate_process(frontend_process)
        _terminate_process(backend_process)


def dev_backend() -> int:
    parser = argparse.ArgumentParser(
        description="Start the backend in development mode."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()

    server = build_server(
        host=args.host,
        port=args.port,
        debug=True,
        reload=not args.no_reload,
    )
    server.serve()
    return 0


def dev_web() -> int:
    return _run_foreground_process(["pnpm", "dev"], cwd=web_root())


def prod() -> int:
    parser = argparse.ArgumentParser(description="Start Yier in production mode.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    args = parser.parse_args()

    server = build_server(
        host=args.host,
        port=args.port,
        debug=False,
        reload=False,
    )
    server.serve()
    return 0


def build_web() -> int:
    return _run_foreground_process(["pnpm", "build"], cwd=web_root())


def build_server(*, host: str, port: int, debug: bool, reload: bool) -> Granian:
    os.environ["YIER_DEBUG"] = "1" if debug else "0"
    return Granian(
        "yier_web.app:create_app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        factory=True,
        reload=reload,
        workers_kill_timeout=5,
    )


def _run_foreground_process(command: list[str], cwd: Path) -> int:
    completed = subprocess.run(command, cwd=cwd, check=False)
    return completed.returncode


def _spawn_process(command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command,
        cwd=cwd,
        start_new_session=True,
    )


def _wait_for_processes(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> int:
    try:
        while True:
            for name, process in processes:
                return_code = process.poll()
                if return_code is None:
                    continue
                if return_code != 0:
                    print(f"{name} exited with code {return_code}.", file=sys.stderr)
                return return_code
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        else:
            process.kill()
        process.wait(timeout=5)
