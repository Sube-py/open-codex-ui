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

from yier_web.daemon import DaemonManager, load_service_environment
from yier_web.system_services import ServiceError


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 13140


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
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
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
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
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


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["_service"]:
        return _service_main(arguments[1:])

    parser = _build_parser()
    if not arguments:
        arguments = ["serve"]
    elif arguments[0].startswith("-") and arguments[0] not in {"-h", "--help"}:
        arguments.insert(0, "serve")
    args = parser.parse_args(arguments)

    if args.command == "serve":
        return _serve(host=args.host, port=args.port)
    if args.command == "daemon":
        try:
            manager = DaemonManager()
            if args.daemon_command == "install":
                return manager.install(host=args.host, port=args.port)
            if args.daemon_command == "start":
                return manager.start()
            if args.daemon_command == "stop":
                return manager.stop()
            if args.daemon_command == "status":
                return manager.status()
            if args.daemon_command == "uninstall":
                return manager.uninstall()
        except (OSError, ServiceError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


def prod() -> int:
    return main()


def _serve(*, host: str, port: int) -> int:
    server = build_server(
        host=host,
        port=port,
        debug=False,
        reload=False,
    )
    server.serve()
    return 0


def build_web() -> int:
    return _run_foreground_process(["pnpm", "build"], cwd=web_root())


def _service_main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    _add_server_arguments(parser)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        load_service_environment(args.env_file)
        _redirect_service_output(args.log_file)
    except ServiceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return _serve(host=args.host, port=args.port)


def _redirect_service_output(log_path: Path) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab", buffering=0) as log_file:
            os.dup2(log_file.fileno(), sys.stdout.fileno())
            os.dup2(log_file.fileno(), sys.stderr.fileno())
    except OSError as exc:
        raise ServiceError(f"Unable to open daemon log at {log_path}.") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and manage the Open Codex UI production server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser(
        "serve",
        help="run in the foreground",
        description="Run Open Codex UI in the foreground.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_server_arguments(serve_parser)

    daemon_parser = subparsers.add_parser(
        "daemon",
        help="manage the login service",
        description="Install and manage the Open Codex UI login service.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    daemon_subparsers = daemon_parser.add_subparsers(
        dest="daemon_command",
        required=True,
    )
    install_parser = daemon_subparsers.add_parser(
        "install",
        help="install the command and login service",
        description="Persist the command and install the native login service.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_server_arguments(install_parser)
    daemon_subparsers.add_parser("start", help="start the installed service")
    daemon_subparsers.add_parser("stop", help="stop the installed service")
    daemon_subparsers.add_parser("status", help="show installed service status")
    daemon_subparsers.add_parser("uninstall", help="remove the login service")
    return parser


def _add_server_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_HOST, help="address to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to bind")


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


if __name__ == "__main__":
    raise SystemExit(main())
