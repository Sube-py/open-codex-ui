from __future__ import annotations

from collections.abc import Iterable

from codex_bridge import JsonDict, materialize_conversation_state

from yier_web.codex.session_events import CodexSessionEvent

TURN_STATE_KEYS = frozenset({"turnHistory", "turns"})


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


class InitialTurnEventProjector:
    """Project state events only while an initial WebSocket subscribe runs."""

    def __init__(
        self,
        cached_turn_ids: Iterable[object],
        refresh_turn_ids: Iterable[object] = (),
    ) -> None:
        self._known_turn_ids = _cached_turn_id_set(cached_turn_ids)
        self._mutable_turn_ids = _cached_turn_id_set(refresh_turn_ids)

    def thread_payload(
        self,
        *,
        thread_id: str,
        state: JsonDict | None,
        stream_role: JsonDict | None,
        queued_followups: list[JsonDict],
    ) -> JsonDict:
        live_state, turn_ids, turns = incremental_turn_state(
            state,
            self._known_turn_ids,
            self._mutable_turn_ids,
        )
        self._known_turn_ids = set(turn_ids)
        self._mutable_turn_ids = {
            turn_id
            for turn in turns
            if turn.get("status") == "inProgress" and (turn_id := _turn_id(turn))
        }
        return {
            "thread_id": thread_id,
            "state": live_state,
            "turn_ids": turn_ids,
            "turns": turns,
            "stream_role": stream_role,
            "queued_followups": queued_followups,
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
            return {
                "type": "thread_state_delta",
                "payload": self.thread_payload(
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
                ),
            }

        if event_type == "codex_session_event" and isinstance(payload, dict):
            if payload.get("method") == "thread-stream-state-changed":
                return None
        return event
