from __future__ import annotations

import asyncio
import gzip
import json

from yier_web.codex.ws_outbox import (
    GZIP_FRAME_PREFIX,
    CodexWebSocketOutbox,
    gzip_websocket_message,
)


def test_codex_websocket_outbox_coalesces_only_pending_thread_state() -> None:
    async def scenario() -> None:
        outbox = CodexWebSocketOutbox()
        first = {
            "type": "thread_state_delta",
            "payload": {"thread_id": "thread-1", "revision": 1},
        }
        latest = {
            "type": "thread_state_delta",
            "payload": {"thread_id": "thread-1", "revision": 2},
        }
        ack = {"type": "ack", "id": "command-1", "payload": {}}

        outbox.put_nowait(first)
        outbox.put_nowait(latest)
        outbox.put_nowait(ack)

        assert outbox.qsize() == 2
        assert await outbox.get() == latest
        assert await outbox.get() == ack

        outbox.put_nowait(first)
        assert await outbox.get() == first
        outbox.put_nowait(latest)
        assert await outbox.get() == latest

    asyncio.run(scenario())


def test_codex_websocket_outbox_composes_pending_text_patches() -> None:
    async def scenario() -> None:
        outbox = CodexWebSocketOutbox()
        first = {
            "type": "thread_state_delta",
            "payload": {
                "thread_id": "thread-1",
                "state": {"id": "thread-1", "status": "running"},
                "turn_ids": ["turn-1"],
                "turns": [],
                "turn_patches": [
                    {
                        "turn_id": "turn-1",
                        "set": {},
                        "remove": [],
                        "item_count": 1,
                        "item_patches": [
                            {"index": 0, "append_fields": {"text": " world"}}
                        ],
                    }
                ],
                "stream_role": None,
                "queued_followups": [],
            },
        }
        latest = {
            "type": "thread_state_delta",
            "payload": {
                "thread_id": "thread-1",
                "state": {"id": "thread-1", "status": "running"},
                "turn_ids": ["turn-1"],
                "turns": [],
                "turn_patches": [
                    {
                        "turn_id": "turn-1",
                        "set": {"durationMs": 20},
                        "remove": [],
                        "item_count": 1,
                        "item_patches": [
                            {"index": 0, "append_fields": {"text": "!"}}
                        ],
                    }
                ],
                "stream_role": None,
                "queued_followups": [],
            },
        }

        outbox.put_nowait(first)
        outbox.put_nowait(latest)

        merged = await outbox.get()
        assert merged["payload"]["turns"] == []
        assert merged["payload"]["turn_patches"] == [
            *first["payload"]["turn_patches"],
            *latest["payload"]["turn_patches"],
        ]

    asyncio.run(scenario())


def test_codex_websocket_outbox_applies_patch_to_pending_full_turn() -> None:
    async def scenario() -> None:
        outbox = CodexWebSocketOutbox()
        outbox.put_nowait(
            {
                "type": "thread_state_delta",
                "payload": {
                    "thread_id": "thread-1",
                    "state": {"id": "thread-1"},
                    "turn_ids": ["turn-1"],
                    "turns": [
                        {
                            "turnId": "turn-1",
                            "status": "inProgress",
                            "items": [{"type": "agentMessage", "text": "Hello"}],
                        }
                    ],
                    "turn_patches": [],
                    "stream_role": None,
                    "queued_followups": [],
                },
            }
        )
        outbox.put_nowait(
            {
                "type": "thread_state_delta",
                "payload": {
                    "thread_id": "thread-1",
                    "state": {"id": "thread-1"},
                    "turn_ids": ["turn-1"],
                    "turns": [],
                    "turn_patches": [
                        {
                            "turn_id": "turn-1",
                            "set": {"status": "completed"},
                            "remove": [],
                            "item_count": 1,
                            "item_patches": [
                                {"index": 0, "append_fields": {"text": " world"}}
                            ],
                        }
                    ],
                    "stream_role": None,
                    "queued_followups": [],
                },
            }
        )

        merged = await outbox.get()
        assert merged["payload"]["turn_patches"] == []
        assert merged["payload"]["turns"] == [
            {
                "turnId": "turn-1",
                "status": "completed",
                "items": [{"type": "agentMessage", "text": "Hello world"}],
            }
        ]

    asyncio.run(scenario())


def test_codex_websocket_outbox_preserves_order_across_ack_barrier() -> None:
    async def scenario() -> None:
        outbox = CodexWebSocketOutbox()
        first = {
            "type": "thread_state_delta",
            "payload": {"thread_id": "thread-1", "revision": 1},
        }
        ack = {"type": "ack", "id": "command-1", "payload": {}}
        latest = {
            "type": "thread_state_delta",
            "payload": {"thread_id": "thread-1", "revision": 2},
        }

        outbox.put_nowait(first)
        outbox.put_nowait(ack)
        outbox.put_nowait(latest)

        assert outbox.qsize() == 3
        assert await outbox.get() == first
        assert await outbox.get() == ack
        assert await outbox.get() == latest

    asyncio.run(scenario())


def test_gzip_websocket_message_round_trips_large_json() -> None:
    message = {
        "type": "thread_state_delta",
        "payload": {"thread_id": "thread-1", "text": "streaming " * 500},
    }

    compressed = gzip_websocket_message(message, minimum_bytes=1)

    assert compressed is not None
    assert compressed.startswith(GZIP_FRAME_PREFIX)
    decoded = gzip.decompress(compressed[len(GZIP_FRAME_PREFIX) :])
    assert json.loads(decoded) == message
    assert len(compressed) < len(json.dumps(message).encode())
