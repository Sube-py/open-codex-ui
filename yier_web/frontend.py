from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx
from litestar.connection import WebSocket
from litestar import Request
from litestar.response import Response

from yier_web.schemas import FrontendHealth


class FrontendService:
    def __init__(
        self,
        dist_root: Path | None = None,
        vite_origin: str = "http://127.0.0.1:5173",
        debug: bool = False,
    ) -> None:
        self.dist_root = (
            dist_root or Path(__file__).resolve().parent / "static"
        ).resolve()
        self.vite_origin = vite_origin.rstrip("/")
        self.debug = debug

    async def get_status(self) -> FrontendHealth:
        if await self._should_proxy_to_vite():
            return FrontendHealth(
                ready=True, mode="proxy", detail=f"Proxying {self.vite_origin}"
            )
        if (self.dist_root / "index.html").exists():
            return FrontendHealth(
                ready=True, mode="static", detail=f"Serving {self.dist_root}"
            )
        return FrontendHealth(
            ready=False,
            mode="missing",
            detail="Start Vite dev server or build the frontend bundle first.",
        )

    async def handle_request(
        self, request: Request[Any, Any, Any], path: str
    ) -> Response:
        if await self._should_proxy_to_vite():
            return await self._proxy_request(request)

        resolved_path = self._resolve_dist_path(path)
        if resolved_path is not None and resolved_path.exists():
            return self._build_static_response(resolved_path)

        index_path = self.dist_root / "index.html"
        if index_path.exists():
            return self._build_static_response(index_path)

        return Response(
            content="Frontend is unavailable. Start `pnpm dev` in `web` or build the frontend.",
            media_type="text/plain",
            status_code=503,
        )

    async def handle_websocket(self, socket: WebSocket, _path: str) -> None:
        await socket.accept()
        if await self._should_proxy_to_vite():
            await socket.close(
                code=1013,
                reason="Frontend dev WebSocket is served by Vite on port 5173.",
            )
            return

        await socket.close(
            code=1008,
            reason="Frontend WebSocket is unavailable for the static bundle.",
        )

    async def _should_proxy_to_vite(self) -> bool:
        if not self.debug:
            return False
        return await self._vite_available()

    async def _proxy_request(self, request: Request[Any, Any, Any]) -> Response:
        request_headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "connection", "content-length"}
        }

        async with self._create_vite_client(
            timeout=10.0, follow_redirects=False
        ) as client:
            upstream = await self._proxy_to_vite(
                client,
                request=request,
                headers=request_headers,
                path=request.url.path,
                query=request.url.query,
            )

            if self._should_fallback_to_vite_index(request, upstream.status_code):
                upstream = await self._proxy_to_vite(
                    client,
                    request=request,
                    headers=request_headers,
                    path="/",
                    query="",
                )

        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in {"connection", "content-length", "transfer-encoding"}
        }
        media_type = upstream.headers.get("content-type")
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=media_type,
            headers=response_headers,
        )

    async def _proxy_to_vite(
        self,
        client: httpx.AsyncClient,
        *,
        request: Request[Any, Any, Any],
        headers: dict[str, str],
        path: str,
        query: str,
    ) -> httpx.Response:
        target_url = f"{self.vite_origin}{path}"
        if query:
            target_url = f"{target_url}?{query}"
        return await client.request(
            request.method,
            target_url,
            headers=headers,
            content=await request.body(),
        )

    def _should_fallback_to_vite_index(
        self,
        request: Request[Any, Any, Any],
        upstream_status_code: int,
    ) -> bool:
        if upstream_status_code != 404:
            return False
        if request.method.upper() not in {"GET", "HEAD"}:
            return False
        if Path(request.url.path).suffix:
            return False

        accept = request.headers.get("accept", "").lower()
        return "text/html" in accept or accept in {"", "*/*"}

    def _resolve_dist_path(self, path: str) -> Path | None:
        normalized_path = path.lstrip("/")

        if not normalized_path:
            candidate = self.dist_root / "index.html"
            return candidate if candidate.exists() else None

        candidate = (self.dist_root / normalized_path).resolve()
        try:
            candidate.relative_to(self.dist_root.resolve())
        except ValueError:
            return None

        if candidate.exists() and candidate.is_file():
            return candidate
        if Path(normalized_path).suffix:
            return None
        return None

    async def _vite_available(self) -> bool:
        try:
            async with self._create_vite_client(timeout=0.35) as client:
                response = await client.get(self.vite_origin)
        except httpx.HTTPError:
            return False
        return response.status_code < 500

    def _create_vite_client(
        self,
        *,
        timeout: float,
        follow_redirects: bool = False,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            follow_redirects=follow_redirects,
            timeout=timeout,
            trust_env=False,
        )

    def _build_static_response(self, path: Path) -> Response:
        media_type, encoding = mimetypes.guess_type(path.name)
        headers: dict[str, str] = {}
        if encoding:
            headers["content-encoding"] = encoding
        return Response(
            content=path.read_bytes(),
            media_type=media_type or "application/octet-stream",
            headers=headers or None,
        )
