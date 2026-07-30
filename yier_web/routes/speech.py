from __future__ import annotations

import asyncio
import json
from typing import Any

from litestar import Controller, websocket
from litestar.connection import WebSocket
from litestar.exceptions import WebSocketDisconnect

from yier_web.speech import SpeechRecognitionService, SpeechRecognitionUnavailable


MAX_AUDIO_CHUNK_BYTES = 1024 * 1024


def _speech_service(state: Any) -> SpeechRecognitionService:
    service = getattr(state, "speech_service", None)
    if not isinstance(service, SpeechRecognitionService):
        raise RuntimeError("Speech recognition service is not configured.")
    return service


class SpeechController(Controller):
    path = "/speech"

    @websocket("/ws")
    async def websocket_handler(self, socket: WebSocket) -> None:
        await socket.accept()
        auth_service = socket.app.state.auth_service
        if not auth_service.is_websocket_authorized(socket):
            await self._send_error(
                socket,
                code="unauthorized",
                message="Authentication is required for voice input.",
            )
            await socket.close(code=1008, reason="Speech WebSocket unauthorized.")
            return

        try:
            session = await asyncio.to_thread(
                _speech_service(socket.app.state).create_session
            )
        except SpeechRecognitionUnavailable as exc:
            await self._send_error(socket, code="unavailable", message=str(exc))
            await socket.close(code=1011, reason="Speech recognition unavailable.")
            return

        await socket.send_json(
            {
                "type": "ready",
                "sample_rate": 16_000,
                "encoding": "float32le",
            }
        )
        last_transcript = ""

        try:
            while True:
                event = await socket.receive()
                if event["type"] == "websocket.disconnect":
                    return

                audio = event.get("bytes")
                if audio is not None:
                    if not audio:
                        continue
                    if len(audio) > MAX_AUDIO_CHUNK_BYTES:
                        await self._send_error(
                            socket,
                            code="audio_chunk_too_large",
                            message="Audio chunk is too large.",
                        )
                        await socket.close(code=1009, reason="Audio chunk too large.")
                        return
                    try:
                        transcript = await asyncio.to_thread(
                            session.accept_audio, audio
                        )
                    except (RuntimeError, ValueError) as exc:
                        await self._send_error(
                            socket,
                            code="invalid_audio",
                            message=str(exc),
                        )
                        await socket.close(code=1003, reason="Invalid audio payload.")
                        return
                    if transcript != last_transcript:
                        last_transcript = transcript
                        await socket.send_json(
                            {"type": "partial", "text": transcript}
                        )
                    continue

                message = self._parse_control_message(event.get("text"))
                if message == "finish":
                    transcript = await asyncio.to_thread(session.finish)
                    await socket.send_json({"type": "final", "text": transcript})
                    await socket.close(code=1000, reason="Speech recognition complete.")
                    return
                if message == "cancel":
                    await socket.close(code=1000, reason="Speech recognition cancelled.")
                    return

                await self._send_error(
                    socket,
                    code="invalid_control_message",
                    message="Expected a finish or cancel control message.",
                )
        except WebSocketDisconnect:
            return
        except Exception as exc:  # noqa: BLE001
            await self._send_error(
                socket,
                code="recognition_failed",
                message=f"Voice recognition failed: {exc}",
            )
            await socket.close(code=1011, reason="Speech recognition failed.")

    @staticmethod
    def _parse_control_message(raw_message: str | None) -> str:
        if not raw_message:
            return ""
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            return ""
        if not isinstance(message, dict):
            return ""
        message_type = message.get("type")
        return message_type if isinstance(message_type, str) else ""

    @staticmethod
    async def _send_error(socket: WebSocket, *, code: str, message: str) -> None:
        await socket.send_json({"type": "error", "code": code, "message": message})
