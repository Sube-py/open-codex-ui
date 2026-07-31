from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy

from codex_bridge import JsonDict, materialize_conversation_state

from yier_web.codex.session_events import CodexSessionEvent

TURN_STATE_KEYS = frozenset({"turnHistory", "turns"})
TURN_ITEMS_KEY = "items"


def _turn_id(turn: JsonDict) -> str | None:
    turn_id = turn.get("turnId")
    if not isinstance(turn_id, str):
        return None
    normalized = turn_id.strip()
    return normalized or None


def _cached_turn_id_set(turn_ids: Iterable[object]) -> set[str]:
    return {
        normalized
        for turn_id in turn_ids
        if isinstance(turn_id, str) and (normalized := turn_id.strip())
    }


def _record_items(turn: JsonDict) -> list[JsonDict] | None:
    items = turn.get(TURN_ITEMS_KEY)
    if not isinstance(items, list):
        return []
    if not all(isinstance(item, dict) for item in items):
        return None
    return [item for item in items if isinstance(item, dict)]


def _appended_string_fields(
    previous: JsonDict,
    current: JsonDict,
) -> JsonDict | None:
    appended: JsonDict = {}
    for key in previous.keys() | current.keys():
        old_value = previous.get(key)
        new_value = current.get(key)
        if old_value == new_value:
            continue
        if (
            isinstance(old_value, str)
            and isinstance(new_value, str)
            and new_value.startswith(old_value)
        ):
            appended[key] = new_value[len(old_value) :]
            continue
        return None
    return appended or None


def turn_state_patch(previous: JsonDict, current: JsonDict) -> JsonDict | None:
    """Build a compact patch while preserving exact turn and item semantics."""

    turn_id = _turn_id(current)
    if not turn_id or _turn_id(previous) != turn_id:
        return None
    previous_items = _record_items(previous)
    current_items = _record_items(current)
    if previous_items is None or current_items is None:
        return None

    previous_fields = {
        key: value
        for key, value in previous.items()
        if key not in {"turnId", TURN_ITEMS_KEY}
    }
    current_fields = {
        key: value
        for key, value in current.items()
        if key not in {"turnId", TURN_ITEMS_KEY}
    }
    changed_fields = {
        key: value
        for key, value in current_fields.items()
        if previous_fields.get(key) != value or key not in previous_fields
    }
    removed_fields = [
        key for key in previous_fields if key not in current_fields
    ]

    item_patches: list[JsonDict] = []
    for index, item in enumerate(current_items):
        if index >= len(previous_items):
            item_patches.append({"index": index, "item": item})
            continue
        previous_item = previous_items[index]
        if previous_item == item:
            continue
        appended_fields = _appended_string_fields(previous_item, item)
        if appended_fields is not None:
            item_patches.append(
                {
                    "index": index,
                    "append_fields": appended_fields,
                }
            )
        else:
            item_patches.append({"index": index, "item": item})

    item_count_changed = len(previous_items) != len(current_items)
    if not changed_fields and not removed_fields and not item_patches and not item_count_changed:
        return None
    return {
        "turn_id": turn_id,
        "set": changed_fields,
        "remove": removed_fields,
        "item_count": len(current_items),
        "item_patches": item_patches,
    }


def incremental_turn_state(
    state: JsonDict | None,
    cached_turn_ids: Iterable[object],
    refresh_turn_ids: Iterable[object] = (),
) -> tuple[JsonDict | None, list[str], list[JsonDict]]:
    """Split conversation state into live metadata and the turns a client needs."""

    materialized = materialize_conversation_state(state)
    if not isinstance(materialized, dict):
        return materialized, [], []

    raw_turns = materialized.get("turns")
    turns = (
        [dict(turn) for turn in raw_turns if isinstance(turn, dict)]
        if isinstance(raw_turns, list)
        else []
    )
    known_ids = _cached_turn_id_set(cached_turn_ids)
    refresh_ids = _cached_turn_id_set(refresh_turn_ids)
    ordered_ids = [turn_id for turn in turns if (turn_id := _turn_id(turn))]
    last_index = len(turns) - 1
    changed_turns = [
        turn
        for index, turn in enumerate(turns)
        if (turn_id := _turn_id(turn)) is None
        or turn_id not in known_ids
        or turn_id in refresh_ids
        or turn.get("status") == "inProgress"
        or index == last_index
    ]
    live_state = {
        key: value for key, value in materialized.items() if key not in TURN_STATE_KEYS
    }
    return live_state, ordered_ids, changed_turns


class TurnEventProjector:
    """Project state events throughout one WebSocket thread subscription."""

    def __init__(
        self,
        cached_turn_ids: Iterable[object],
        refresh_turn_ids: Iterable[object] = (),
    ) -> None:
        self._known_turn_ids = _cached_turn_id_set(cached_turn_ids)
        self._mutable_turn_ids = _cached_turn_id_set(refresh_turn_ids)
        self._projected_turns: dict[str, JsonDict] = {}
        self._last_live_state: JsonDict | None = None
        self._last_stream_role: JsonDict | None = None
        self._last_queued_followups: list[JsonDict] = []
        self._last_projection_changed = True

    def thread_payload(
        self,
        *,
        thread_id: str,
        state: JsonDict | None,
        stream_role: JsonDict | None,
        queued_followups: list[JsonDict],
    ) -> JsonDict:
        live_state, turn_ids, candidate_turns = incremental_turn_state(
            state,
            self._known_turn_ids,
            self._mutable_turn_ids,
        )
        self._known_turn_ids = set(turn_ids)
        turns: list[JsonDict] = []
        turn_patches: list[JsonDict] = []
        next_projected_turns: dict[str, JsonDict] = {}

        for turn in candidate_turns:
            turn_id = _turn_id(turn)
            previous = self._projected_turns.get(turn_id) if turn_id else None
            patch = turn_state_patch(previous, turn) if previous is not None else None
            if previous is None or patch is None and previous != turn:
                turns.append(turn)
            elif patch is not None:
                turn_patches.append(patch)

        last_turn_id = turn_ids[-1] if turn_ids else None
        self._mutable_turn_ids = {
            turn_id
            for turn in candidate_turns
            if turn.get("status") == "inProgress" and (turn_id := _turn_id(turn))
        }
        retained_turn_ids = self._mutable_turn_ids | ({last_turn_id} if last_turn_id else set())
        for turn in candidate_turns:
            turn_id = _turn_id(turn)
            if turn_id in retained_turn_ids:
                next_projected_turns[turn_id] = deepcopy(turn)
        for turn_id in retained_turn_ids:
            if turn_id not in next_projected_turns and turn_id in self._projected_turns:
                next_projected_turns[turn_id] = self._projected_turns[turn_id]
        self._projected_turns = next_projected_turns

        normalized_followups = [dict(item) for item in queued_followups]
        self._last_projection_changed = bool(
            turns
            or turn_patches
            or live_state != self._last_live_state
            or stream_role != self._last_stream_role
            or normalized_followups != self._last_queued_followups
        )
        self._last_live_state = deepcopy(live_state)
        self._last_stream_role = deepcopy(stream_role)
        self._last_queued_followups = deepcopy(normalized_followups)
        return {
            "thread_id": thread_id,
            "state": live_state,
            "turn_ids": turn_ids,
            "turns": turns,
            "turn_patches": turn_patches,
            "stream_role": stream_role,
            "queued_followups": normalized_followups,
        }

    def __call__(self, event: CodexSessionEvent) -> CodexSessionEvent | None:
        event_type = event.get("type")
        payload = event.get("payload")
        if event_type in {"thread_snapshot", "thread_state"} and isinstance(
            payload, dict
        ):
            state = payload.get("state")
            stream_role = payload.get("stream_role")
            queued_followups = payload.get("queued_followups")
            projected_payload = self.thread_payload(
                thread_id=str(payload.get("thread_id") or ""),
                state=state if isinstance(state, dict) else None,
                stream_role=(
                    stream_role if isinstance(stream_role, dict) else None
                ),
                queued_followups=(
                    [
                        dict(item)
                        for item in queued_followups
                        if isinstance(item, dict)
                    ]
                    if isinstance(queued_followups, list)
                    else []
                ),
            )
            if not self._last_projection_changed:
                return None
            return {
                "type": "thread_state_delta",
                "payload": projected_payload,
            }

        if event_type == "codex_session_event" and isinstance(payload, dict):
            if payload.get("method") == "thread-stream-state-changed":
                return None
        return event
