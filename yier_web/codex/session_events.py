from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import inspect
import logging
from typing import Any

JsonDict = dict[str, Any]
CodexSessionEvent = JsonDict
CodexSessionEventQueue = asyncio.Queue[CodexSessionEvent]
CodexSessionEventSink = Callable[[CodexSessionEvent], Awaitable[None] | None]
CodexSessionEventProjector = Callable[[CodexSessionEvent], CodexSessionEvent | None]
Unsubscribe = Callable[[], None]

logger = logging.getLogger(__name__)


class CodexSessionEventHub:
    """Fan out Codex session events to thread subscribers and channel sinks."""

    def __init__(self) -> None:
        self._thread_subscribers: dict[
            str,
            dict[CodexSessionEventQueue, CodexSessionEventProjector | None],
        ] = {}
        self._sinks: set[CodexSessionEventSink] = set()

    def subscribe_thread(
        self,
        thread_id: str,
        queue: CodexSessionEventQueue,
        *,
        projector: CodexSessionEventProjector | None = None,
    ) -> bool:
        subscribers = self._thread_subscribers.setdefault(thread_id, {})
        was_empty = not subscribers
        subscribers[queue] = projector
        return was_empty

    def unsubscribe_thread(
        self,
        thread_id: str,
        queue: CodexSessionEventQueue,
    ) -> bool:
        subscribers = self._thread_subscribers.get(thread_id)
        if subscribers is None or queue not in subscribers:
            return False
        subscribers.pop(queue, None)
        if not subscribers:
            self._thread_subscribers.pop(thread_id, None)
            return True
        return False

    def clear_thread(self, thread_id: str) -> None:
        self._thread_subscribers.pop(thread_id, None)

    def clear_thread_subscribers(self) -> None:
        self._thread_subscribers.clear()

    def clear(self) -> None:
        self._thread_subscribers.clear()
        self._sinks.clear()

    def add_sink(self, sink: CodexSessionEventSink) -> Unsubscribe:
        self._sinks.add(sink)

        def unsubscribe() -> None:
            self._sinks.discard(sink)

        return unsubscribe

    async def publish_thread_event(
        self,
        thread_id: str,
        event: CodexSessionEvent,
    ) -> None:
        self._publish_to_subscribers(thread_id, event)
        for sink in list(self._sinks):
            await self._publish_to_sink(sink, event)

    async def publish_to_thread_subscribers(
        self,
        thread_id: str,
        event: CodexSessionEvent,
    ) -> None:
        self._publish_to_subscribers(thread_id, event)

    async def publish_to_all_thread_subscribers(
        self,
        event: CodexSessionEvent,
    ) -> None:
        for thread_id in list(self._thread_subscribers):
            self._publish_to_subscribers(thread_id, event)

    async def publish_global_event(self, event: CodexSessionEvent) -> None:
        for thread_id in list(self._thread_subscribers):
            self._publish_to_subscribers(thread_id, event)
        for sink in list(self._sinks):
            await self._publish_to_sink(sink, event)

    def _publish_to_subscribers(
        self,
        thread_id: str,
        event: CodexSessionEvent,
    ) -> None:
        subscribers = self._thread_subscribers.get(thread_id, {})
        for queue, projector in list(subscribers.items()):
            projected = projector(event) if projector is not None else event
            if projected is not None:
                queue.put_nowait(projected)

    async def _publish_to_sink(
        self,
        sink: CodexSessionEventSink,
        event: CodexSessionEvent,
    ) -> None:
        try:
            result = sink(event)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning("Codex session event sink failed: %s", exc)
