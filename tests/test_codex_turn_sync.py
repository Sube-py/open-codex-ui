from __future__ import annotations

from yier_web.codex.turn_sync import (
    TurnEventProjector,
    incremental_turn_state,
)


def test_incremental_turn_state_omits_cached_history_but_refreshes_latest_turn() -> (
    None
):
    first_turn = {
        "turnId": "turn-1",
        "status": "completed",
        "items": [{"type": "agentMessage", "text": "first"}],
    }
    latest_turn = {
        "turnId": "turn-2",
        "status": "completed",
        "items": [{"type": "agentMessage", "text": "latest"}],
    }
    state = {
        "id": "thread-1",
        "title": "Conversation",
        "turnHistory": {
            "kind": "canonical",
            "history": {
                "entitiesByKey": {
                    "turn:turn-1": first_turn,
                    "turn:turn-2": latest_turn,
                },
                "generation": 3,
                "isComplete": True,
                "islands": [
                    {
                        "id": "tail:3",
                        "entries": [
                            {"key": "turn:turn-1", "value": "turn:turn-1"},
                            {"key": "turn:turn-2", "value": "turn:turn-2"},
                        ],
                    }
                ],
            },
        },
        "turns": [],
    }

    live_state, turn_ids, turns = incremental_turn_state(
        state,
        ["turn-1", "turn-2"],
    )

    assert live_state == {"id": "thread-1", "title": "Conversation"}
    assert turn_ids == ["turn-1", "turn-2"]
    assert turns == [latest_turn]


def test_incremental_turn_state_returns_missing_and_idless_turns() -> None:
    state = {
        "id": "thread-1",
        "turns": [
            {"turnId": "turn-1", "status": "completed", "items": []},
            {"turnId": "turn-2", "status": "inProgress", "items": []},
            {"turnId": None, "status": "inProgress", "items": []},
        ],
    }

    _live_state, turn_ids, turns = incremental_turn_state(state, ["turn-1"])

    assert turn_ids == ["turn-1", "turn-2"]
    assert [turn.get("turnId") for turn in turns] == ["turn-2", None]


def test_incremental_projector_refreshes_mutable_turn_after_new_turn_arrives() -> None:
    projector = TurnEventProjector(
        ["turn-1"],
        ["turn-1"],
    )

    payload = projector.thread_payload(
        thread_id="thread-1",
        state={
            "id": "thread-1",
            "turns": [
                {"turnId": "turn-1", "status": "completed", "items": []},
                {"turnId": "turn-2", "status": "inProgress", "items": []},
            ],
        },
        stream_role=None,
        queued_followups=[],
    )

    assert [turn["turnId"] for turn in payload["turns"]] == ["turn-1", "turn-2"]


def test_incremental_projector_drops_duplicate_native_state_event() -> None:
    projector = TurnEventProjector([])

    event = projector(
        {
            "type": "codex_session_event",
            "payload": {
                "thread_id": "thread-1",
                "method": "thread-stream-state-changed",
                "params": {"change": {"type": "snapshot"}},
            },
        }
    )

    assert event is None
