import asyncio
import argparse
import os
from pathlib import Path

from granian import Granian, loops
from granian.constants import Interfaces

from yier_web.app import create_app


@loops.register("auto")
def build_loop():
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    return asyncio.new_event_loop()


def build_app():
    return create_app(project_root=Path(__file__).resolve().parent)


def build_server(
    *,
    host: str = "0.0.0.0",
    port: int = 9999,
    debug: bool = False,
    reload: bool = False,
) -> Granian:
    os.environ["YIER_DEBUG"] = "1" if debug else "0"
    return Granian(
        f"{__name__}:build_app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        factory=True,
        reload=reload,
        # Some workers do not always exit promptly after SIGINT/SIGTERM on macOS.
        # Without a timeout, the main process can block forever waiting on join().
        workers_kill_timeout=5,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Open Codex UI web server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_server(
        host=args.host,
        port=args.port,
        debug=args.debug,
        reload=args.reload,
    ).serve()
