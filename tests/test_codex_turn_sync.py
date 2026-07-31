from __future__ import annotations

import json

from yier_web.codex.turn_sync import (
    TurnEventProjector,
    incremental_turn_state,
    turn_state_patch,
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
    assert payload["turn_patches"] == []


def test_turn_state_patch_appends_streaming_text_and_replaces_changed_items() -> None:
    patch = turn_state_patch(
        {
            "turnId": "turn-1",
            "status": "inProgress",
            "durationMs": 10,
            "items": [
                {"id": "message-1", "type": "agentMessage", "text": "Hello"},
                {"id": "tool-1", "type": "commandExecution", "status": "running"},
            ],
        },
        {
            "turnId": "turn-1",
            "status": "inProgress",
            "durationMs": 20,
            "items": [
                {"id": "message-1", "type": "agentMessage", "text": "Hello world"},
                {"id": "tool-1", "type": "commandExecution", "status": "completed"},
                {"id": "message-2", "type": "agentMessage", "text": "Done"},
            ],
        },
    )

    assert patch == {
        "turn_id": "turn-1",
        "set": {"durationMs": 20},
        "remove": [],
        "item_count": 3,
        "item_patches": [
            {"index": 0, "append_fields": {"text": " world"}},
            {
                "index": 1,
                "item": {
                    "id": "tool-1",
                    "type": "commandExecution",
                    "status": "completed",
                },
            },
            {
                "index": 2,
                "item": {
                    "id": "message-2",
                    "type": "agentMessage",
                    "text": "Done",
                },
            },
        ],
    }


def test_incremental_projector_sends_text_suffix_then_suppresses_duplicate_state() -> None:
    projector = TurnEventProjector([])
    initial_state = {
        "id": "thread-1",
        "turns": [
            {
                "turnId": "turn-1",
                "status": "inProgress",
                "items": [{"type": "agentMessage", "text": "Hello"}],
            }
        ],
    }
    first = projector.thread_payload(
        thread_id="thread-1",
        state=initial_state,
        stream_role=None,
        queued_followups=[],
    )
    updated_state = {
        "id": "thread-1",
        "turns": [
            {
                "turnId": "turn-1",
                "status": "inProgress",
                "items": [{"type": "agentMessage", "text": "Hello world"}],
            }
        ],
    }
    second = projector.thread_payload(
        thread_id="thread-1",
        state=updated_state,
        stream_role=None,
        queued_followups=[],
    )
    duplicate = projector(
        {
            "type": "thread_state",
            "payload": {
                "thread_id": "thread-1",
                "state": updated_state,
                "stream_role": None,
                "queued_followups": [],
            },
        }
    )

    assert first["turns"] == initial_state["turns"]
    assert first["turn_patches"] == []
    assert second["turns"] == []
    assert second["turn_patches"] == [
        {
            "turn_id": "turn-1",
            "set": {},
            "remove": [],
            "item_count": 1,
            "item_patches": [
                {"index": 0, "append_fields": {"text": " world"}}
            ],
        }
    ]
    assert duplicate is None


def test_incremental_projector_does_not_repeat_the_accumulated_turn() -> None:
    projector = TurnEventProjector([])
    text = "streamed text " * 10_000
    initial_state = {
        "id": "thread-1",
        "turns": [
            {
                "turnId": "turn-1",
                "status": "inProgress",
                "items": [{"type": "agentMessage", "text": text}],
            }
        ],
    }
    first = projector.thread_payload(
        thread_id="thread-1",
        state=initial_state,
        stream_role=None,
        queued_followups=[],
    )
    updated_state = {
        "id": "thread-1",
        "turns": [
            {
                "turnId": "turn-1",
                "status": "inProgress",
                "items": [{"type": "agentMessage", "text": f"{text}!"}],
            }
        ],
    }
    delta = projector.thread_payload(
        thread_id="thread-1",
        state=updated_state,
        stream_role=None,
        queued_followups=[],
    )

    assert len(json.dumps(first).encode()) > 100_000
    assert len(json.dumps(delta).encode()) < 1_000
    assert delta["turn_patches"][0]["item_patches"] == [
        {"index": 0, "append_fields": {"text": "!"}}
    ]


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
