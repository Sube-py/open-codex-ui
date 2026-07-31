from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import gzip
import json
from typing import Any

JsonDict = dict[str, Any]

GZIP_FRAME_PREFIX = b"YIER_GZIP_V1\0"
GZIP_MINIMUM_BYTES = 1024
COALESCED_EVENT_TYPES = frozenset(
    {
        "thread_snapshot",
        "thread_state",
        "thread_state_delta",
    }
)


@dataclass(slots=True)
class _OutboxEntry:
    message: JsonDict
    coalesce_key: tuple[str, str] | None = None


def _turn_id(turn: JsonDict) -> str | None:
    turn_id = turn.get("turnId")
    if not isinstance(turn_id, str):
        return None
    normalized = turn_id.strip()
    return normalized or None


def _apply_turn_patch(turn: JsonDict, patch: JsonDict) -> JsonDict:
    result = deepcopy(turn)
    removed_fields = patch.get("remove")
    if isinstance(removed_fields, list):
        for key in removed_fields:
            if isinstance(key, str):
                result.pop(key, None)

    changed_fields = patch.get("set")
    if isinstance(changed_fields, dict):
        result.update(deepcopy(changed_fields))

    item_count = patch.get("item_count")
    item_patches = patch.get("item_patches")
    if not isinstance(item_count, int) or isinstance(item_count, bool):
        return result
    if not isinstance(item_patches, list):
        return result

    raw_items = result.get("items")
    items = deepcopy(raw_items) if isinstance(raw_items, list) else []
    item_count = max(item_count, 0)
    del items[item_count:]
    items.extend([None] * (item_count - len(items)))
    for item_patch in item_patches:
        if not isinstance(item_patch, dict):
            continue
        index = item_patch.get("index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= len(items)
        ):
            continue
        item = item_patch.get("item")
        if isinstance(item, dict):
            items[index] = deepcopy(item)
            continue
        append_fields = item_patch.get("append_fields")
        current_item = items[index]
        if not isinstance(append_fields, dict) or not isinstance(current_item, dict):
            continue
        next_item = deepcopy(current_item)
        for key, suffix in append_fields.items():
            previous = next_item.get(key)
            if isinstance(key, str) and isinstance(previous, str) and isinstance(suffix, str):
                next_item[key] = f"{previous}{suffix}"
        items[index] = next_item
    result["items"] = items
    return result


def _merge_thread_state_delta(existing: JsonDict, latest: JsonDict) -> JsonDict:
    existing_payload = existing.get("payload")
    latest_payload = latest.get("payload")
    if not isinstance(existing_payload, dict) or not isinstance(latest_payload, dict):
        return latest
    list_fields = ("turn_ids", "turns", "turn_patches")
    if any(
        not isinstance(payload.get(field), list)
        for payload in (existing_payload, latest_payload)
        for field in list_fields
    ):
        return latest

    full_turns: dict[str, JsonDict] = {}
    pending_patches: list[JsonDict] = []

    def apply_patches(patches: list[object]) -> None:
        for raw_patch in patches:
            if not isinstance(raw_patch, dict):
                continue
            patch = deepcopy(raw_patch)
            turn_id = patch.get("turn_id")
            if isinstance(turn_id, str) and turn_id in full_turns:
                full_turns[turn_id] = _apply_turn_patch(full_turns[turn_id], patch)
            else:
                pending_patches.append(patch)

    def apply_full_turns(turns: list[object]) -> None:
        for raw_turn in turns:
            if not isinstance(raw_turn, dict):
                continue
            turn = deepcopy(raw_turn)
            turn_id = _turn_id(turn)
            if not turn_id:
                continue
            full_turns[turn_id] = turn
            pending_patches[:] = [
                patch for patch in pending_patches if patch.get("turn_id") != turn_id
            ]

    # The frontend applies patches before full turns inside each frame. Preserve
    # that order while composing multiple pending frames into one transformation.
    apply_patches(existing_payload["turn_patches"])
    apply_full_turns(existing_payload["turns"])
    apply_patches(latest_payload["turn_patches"])
    apply_full_turns(latest_payload["turns"])

    latest_turn_ids = latest_payload["turn_ids"]
    ordered_full_turns = [
        full_turns[turn_id]
        for turn_id in latest_turn_ids
        if isinstance(turn_id, str) and turn_id in full_turns
    ]
    ordered_ids = {
        turn_id for turn_id in latest_turn_ids if isinstance(turn_id, str)
    }
    ordered_full_turns.extend(
        turn
        for turn_id, turn in full_turns.items()
        if turn_id not in ordered_ids
    )
    ordered_full_turns.extend(
        deepcopy(turn)
        for turn in latest_payload["turns"]
        if isinstance(turn, dict) and _turn_id(turn) is None
    )

    merged = deepcopy(latest)
    merged_payload = deepcopy(latest_payload)
    merged_payload["turns"] = ordered_full_turns
    merged_payload["turn_patches"] = pending_patches
    merged["payload"] = merged_payload
    return merged


def _coalesce_message(existing: JsonDict, latest: JsonDict) -> JsonDict:
    if existing.get("type") == latest.get("type") == "thread_state_delta":
        return _merge_thread_state_delta(existing, latest)
    return latest


def gzip_websocket_message(
    message: JsonDict,
    *,
    minimum_bytes: int = GZIP_MINIMUM_BYTES,
) -> bytes | None:
    payload = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    if len(payload) < minimum_bytes:
        return None
    return GZIP_FRAME_PREFIX + gzip.compress(payload, compresslevel=1, mtime=0)


class CodexWebSocketOutbox:
    """Keep ordered events while replacing queued thread state with its latest value."""

    def __init__(self) -> None:
        self._items: deque[_OutboxEntry] = deque()
        self._coalesced_entries: dict[tuple[str, str], _OutboxEntry] = {}
        self._available = asyncio.Event()
        self.compression_enabled = False

    def enable_gzip(self) -> None:
        self.compression_enabled = True

    async def put(self, message: JsonDict) -> None:
        self.put_nowait(message)

    def put_nowait(self, message: JsonDict) -> None:
        coalesce_key = self._coalesce_key(message)
        if coalesce_key is not None:
            existing = self._coalesced_entries.get(coalesce_key)
            if existing is not None:
                existing.message = _coalesce_message(existing.message, message)
                return
        else:
            # Ordered events are barriers: later state must not move ahead of an
            # acknowledgement, error, approval, or user-input notification.
            self._coalesced_entries.clear()

        entry = _OutboxEntry(message=message, coalesce_key=coalesce_key)
        self._items.append(entry)
        if coalesce_key is not None:
            self._coalesced_entries[coalesce_key] = entry
        self._available.set()

    async def get(self) -> JsonDict:
        while not self._items:
            self._available.clear()
            if self._items:
                break
            await self._available.wait()

        entry = self._items.popleft()
        if not self._items:
            self._available.clear()
        if (
            entry.coalesce_key is not None
            and self._coalesced_entries.get(entry.coalesce_key) is entry
        ):
            self._coalesced_entries.pop(entry.coalesce_key, None)
        return entry.message

    def qsize(self) -> int:
        return len(self._items)

    @staticmethod
    def _coalesce_key(message: JsonDict) -> tuple[str, str] | None:
        event_type = message.get("type")
        if event_type not in COALESCED_EVENT_TYPES:
            return None
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return None
        thread_id = payload.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        return str(event_type), thread_id
