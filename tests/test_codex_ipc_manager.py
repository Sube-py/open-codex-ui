from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from openai_codex.generated.v2_all import (
    AbsolutePathBuf,
    IdleThreadStatus,
    SessionSource,
    SessionSourceValue,
    Thread,
    ThreadListResponse,
    ThreadStatus,
)
import pytest
from litestar.exceptions import WebSocketDisconnect
from litestar.testing import TestClient

from yier_web.app import AppServices, create_app
from yier_web.auth import AuthService
from yier_web.codex.ipc_manager import CodexIpcManager
from yier_web.config import AppConfigService
from yier_web.event_stream import EventStreamBroker
from yier_web.frontend import FrontendService
from yier_web.routes.codex import CodexController
from yier_web.schemas import CodexRemoteConnectionPayload, CodexWorkspaceResponse


def fake_thread(
    thread_id: str,
    cwd: str,
    *,
    name: str = "",
    preview: str = "",
    created_at: int = 1,
    updated_at: int = 2,
) -> Thread:
    return Thread(
        cli_version="test",
        created_at=created_at,
        cwd=AbsolutePathBuf(root=cwd),
        ephemeral=False,
        id=thread_id,
        model_provider="openai",
        name=name,
        preview=preview,
        session_id=thread_id,
        source=SessionSource(root=SessionSourceValue.app_server),
        status=ThreadStatus(root=IdleThreadStatus(type="idle")),
        turns=[],
        updated_at=updated_at,
    )


class FakeCodexIpcSession:
    def __init__(
        self, config: Any, *, notify: Callable[[str], None] | None = None
    ) -> None:
        self.config = config
        self._notify = notify
        self.started = False
        self.stopped = False
        self.thread_id = config.thread_id or ""
        self.state: dict[str, Any] | None = (
            {
                "id": self.thread_id or "workspace",
                "threadId": self.thread_id or "workspace",
                "cwd": "/tmp/project-a",
                "title": "Thread",
                "turns": [],
            }
            if config.thread_id is not None
            else None
        )
        self.stream_role: dict[str, Any] | None = {"role": "owner"}
        self.queued_followups: list[dict[str, Any]] = []
        self.start_new_thread_calls: list[dict[str, Any]] = []
        self.run_prompt_calls: list[
            tuple[str, bool, dict[str, Any] | None, list[dict[str, Any]] | None]
        ] = []
        self.steer_prompt_calls: list[str] = []
        self.interrupt_turn_calls: list[str | None] = []
        self.compact_calls = 0
        self.goal: dict[str, Any] | None = None
        self.goal_set_calls: list[dict[str, Any]] = []
        self.goal_get_calls = 0
        self.goal_clear_calls = 0
        self.collaboration_modes: list[dict[str, Any] | None] = []
        self.user_input_responses: list[tuple[str, dict[str, Any]]] = []
        self.followup_calls: list[str] = []
        self.removed_followups: list[str] = []
        self.rename_calls: list[tuple[str, str | None]] = []
        self.archive_calls: list[tuple[str | None, str | None, bool]] = []
        self.unarchive_calls: list[str | None] = []
        self.fork_calls: list[str | None] = []
        self.following_calls: list[bool] = []
        self.lifecycle_calls: list[str] = []
        self.list_threads_calls: list[dict[str, Any] | None] = []
        self.skills_list_calls: list[dict[str, Any] | None] = []
        self._state_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.list_threads_response = ThreadListResponse(
            data=[
                fake_thread("thread-a", "/tmp/project-a", name="Alpha", preview="one"),
                fake_thread("thread-b", "/tmp/project-b", name="Beta", preview="two"),
            ]
        )
        self.skills_list_response = SimpleNamespace(
            data=[
                SimpleNamespace(
                    cwd="/tmp/project-a",
                    skills=[
                        SimpleNamespace(
                            name="deep-research",
                            description="Research thoroughly",
                            enabled=True,
                            interface=SimpleNamespace(
                                display_name="Deep Research",
                                short_description="Research thoroughly",
                                model_dump=lambda mode="python", by_alias=False: {
                                    "displayName": "Deep Research",
                                    "shortDescription": "Research thoroughly",
                                },
                            ),
                            path=SimpleNamespace(root="/skills/deep-research"),
                            scope=SimpleNamespace(value="user"),
                            short_description=None,
                        )
                    ],
                )
            ]
        )

    async def start(self) -> None:
        self.started = True
        self.lifecycle_calls.append("start")

    async def stop(self) -> None:
        self.stopped = True
        self.lifecycle_calls.append("stop")

    async def set_following(self, following: bool) -> None:
        self.following_calls.append(following)
        self.lifecycle_calls.append(f"following:{following}")

    async def start_new_thread(
        self, params: dict[str, Any] | None = None
    ) -> SimpleNamespace:
        self.start_new_thread_calls.append(params or {})
        self.thread_id = "thread-created"
        self.state = {
            "id": self.thread_id,
            "threadId": self.thread_id,
            "cwd": (params or {}).get("cwd", "/tmp/project-c"),
            "title": "Created thread",
            "turns": [],
        }
        return SimpleNamespace(id=self.thread_id)

    async def hydrate_initial_state(self, *, owner_wait_seconds: float = 0.4) -> None:
        self.lifecycle_calls.append("hydrate")
        if self.thread_id == "thread-plan":
            self.state = {
                "id": "thread-plan",
                "turns": [
                    {
                        "turnId": "turn-1",
                        "status": "completed",
                        "items": [
                            {"id": "plan-1", "type": "plan", "text": "Step 1"},
                            {
                                "id": "implement-plan:turn-1",
                                "type": "planImplementation",
                                "turnId": "turn-1",
                                "planContent": "Step 1",
                                "isCompleted": False,
                            },
                        ],
                    }
                ],
                "requests": [
                    {
                        "id": "implement-plan:turn-1",
                        "method": "item/plan/requestImplementation",
                        "params": {
                            "threadId": "thread-plan",
                            "turnId": "turn-1",
                            "planContent": "Step 1",
                        },
                    }
                ],
            }
        return None

    async def list_threads(
        self, params: dict[str, Any] | None = None
    ) -> ThreadListResponse:
        self.list_threads_calls.append(params)
        return self.list_threads_response

    async def _ensure_codex(self) -> SimpleNamespace:
        async def request(
            method: str,
            params: dict[str, Any] | None,
            *,
            response_model: Any = None,
        ) -> Any:
            assert method == "skills/list"
            self.skills_list_calls.append(params)
            return self.skills_list_response

        return SimpleNamespace(_client=SimpleNamespace(request=request))

    async def run_prompt(
        self,
        prompt: str,
        *,
        wait_for_completion: bool,
        collaboration_mode: dict[str, Any] | None = None,
        input_items: list[dict[str, Any]] | None = None,
        approval_policy: str | None = None,
        approvals_reviewer: str | None = None,
        sandbox: dict[str, Any] | None = None,
    ) -> None:
        self.run_prompt_calls.append(
            (
                prompt,
                wait_for_completion,
                collaboration_mode,
                input_items,
                approval_policy,
                approvals_reviewer,
                sandbox,
            )
        )

    async def steer_prompt(self, prompt: str) -> None:
        self.steer_prompt_calls.append(prompt)

    async def interrupt_turn(self, turn_id: str | None = None) -> bool:
        self.interrupt_turn_calls.append(turn_id)
        return True

    async def compact_thread(self) -> bool:
        self.compact_calls += 1
        return True

    async def set_thread_goal(
        self,
        *,
        objective: str | None = None,
        status: str | None = None,
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        self.goal_set_calls.append(
            {
                "objective": objective,
                "status": status,
                "token_budget": token_budget,
            }
        )
        previous_goal = self.goal or {}
        self.goal = {
            "threadId": self.thread_id,
            "objective": objective or previous_goal.get("objective") or "Existing goal",
            "status": status or previous_goal.get("status") or "active",
            "tokenBudget": token_budget
            if token_budget is not None
            else previous_goal.get("tokenBudget"),
            "tokensUsed": 0,
            "timeUsedSeconds": 0,
            "createdAt": 1,
            "updatedAt": 2,
        }
        if self.state is not None:
            self.state["threadGoal"] = self.goal
        return {"goal": self.goal}

    async def get_thread_goal(self) -> dict[str, Any] | None:
        self.goal_get_calls += 1
        return self.goal

    async def clear_thread_goal(self) -> dict[str, Any]:
        self.goal_clear_calls += 1
        self.goal = None
        if self.state is not None:
            self.state["threadGoal"] = None
        return {"cleared": True}

    async def set_collaboration_mode(
        self, collaboration_mode: dict[str, Any] | None
    ) -> None:
        self.collaboration_modes.append(collaboration_mode)

    async def submit_user_input_response(
        self, request_id: str, response: dict[str, Any]
    ) -> bool:
        self.user_input_responses.append((request_id, response))
        return True

    async def enqueue_followup(self, prompt: str) -> dict[str, Any]:
        self.followup_calls.append(prompt)
        return {"message_id": "followup-1", "prompt": prompt}

    async def remove_followup(self, message_id: str) -> None:
        self.removed_followups.append(message_id)

    async def set_thread_name(
        self, name: str, thread_id: str | None = None
    ) -> dict[str, Any]:
        self.rename_calls.append((name, thread_id))
        if self.state is not None:
            self.state["title"] = name
        return {"id": thread_id or self.thread_id, "name": name}

    async def archive_thread(
        self,
        thread_id: str | None = None,
        *,
        cwd: str | None = None,
        cleanup_worktree: bool = True,
    ) -> dict[str, Any]:
        self.archive_calls.append((thread_id, cwd, cleanup_worktree))
        return {"id": thread_id or self.thread_id}

    async def unarchive_thread(self, thread_id: str | None = None) -> dict[str, Any]:
        self.unarchive_calls.append(thread_id)
        return {"id": thread_id or self.thread_id}

    async def fork_thread(
        self,
        thread_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        self.fork_calls.append(thread_id)
        self.thread_id = "thread-forked"
        self.state = {
            "id": self.thread_id,
            "threadId": self.thread_id,
            "cwd": "/tmp/project-a",
            "title": "Forked thread",
            "turns": [],
        }
        return SimpleNamespace(id=self.thread_id)

    async def watch_state(self, *, replay: bool = True):
        if replay:
            yield self.state
        while True:
            yield await self._state_queue.get()

    def emit_state(self, state: dict[str, Any] | None) -> None:
        self.state = state
        self._state_queue.put_nowait(state)


class NativeEventFakeCodexIpcSession(FakeCodexIpcSession):
    def __init__(
        self, config: Any, *, notify: Callable[[str], None] | None = None
    ) -> None:
        super().__init__(config, notify=notify)
        self._session_event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def watch_session_events(self):
        while True:
            yield await self._session_event_queue.get()

    def emit_session_event(self, event: dict[str, Any]) -> None:
        self._session_event_queue.put_nowait(event)


class FakeSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeCodexIpcSession] = []

    def __call__(
        self, config: Any, *, notify: Callable[[str], None] | None = None
    ) -> FakeCodexIpcSession:
        session = FakeCodexIpcSession(config, notify=notify)
        self.sessions.append(session)
        return session

    def by_thread_id(self, thread_id: str) -> FakeCodexIpcSession:
        for session in self.sessions:
            if session.thread_id == thread_id:
                return session
        raise KeyError(thread_id)

    def workspace_session(self) -> FakeCodexIpcSession:
        for session in self.sessions:
            if session.config.thread_id is None:
                return session
        raise KeyError("workspace")


class NativeEventSessionFactory(FakeSessionFactory):
    def __call__(
        self, config: Any, *, notify: Callable[[str], None] | None = None
    ) -> NativeEventFakeCodexIpcSession:
        session = NativeEventFakeCodexIpcSession(config, notify=notify)
        self.sessions.append(session)
        return session


class FakeDirectoryPickerService:
    def select_directory(self, initial_path: str | None = None) -> str | None:
        return None


class DisconnectingCodexSocket:
    def __init__(self, manager: CodexIpcManager) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                auth_service=AuthService(),
                codex_ipc_manager=manager,
            )
        )
        self.accepted = False
        self.sent_messages: list[dict[str, Any]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> dict[str, Any]:
        await asyncio.sleep(0)
        raise WebSocketDisconnect(detail="disconnect event")

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent_messages.append(message)


def build_app(
    tmp_path: Path, factory: FakeSessionFactory
) -> tuple[AppConfigService, TestClient[Any]]:
    project_root = tmp_path / "project"
    (project_root / "web" / "dist").mkdir(parents=True)
    (project_root / "web" / "dist" / "index.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    config_service = AppConfigService(
        project_root=project_root, home_dir=tmp_path / "home"
    )
    manager = CodexIpcManager(
        config_service=config_service,
        event_broker=EventStreamBroker(),
        session_factory=factory,
    )
    frontend_service = FrontendService(project_root=project_root)
    app = create_app(
        project_root=project_root,
        home_dir=tmp_path / "home",
        services=AppServices(
            config_service=config_service,
            codex_ipc_manager=manager,
            event_broker=EventStreamBroker(),
            frontend_service=frontend_service,
            directory_picker_service=FakeDirectoryPickerService(),
            auth_service=AuthService(),
        ),
    )
    return config_service, TestClient(app)


def test_manager_materializes_canonical_history_for_web(tmp_path: Path) -> None:
    config_service = AppConfigService(
        project_root=tmp_path,
        home_dir=tmp_path / "home",
    )
    manager = CodexIpcManager(
        config_service=config_service,
        event_broker=EventStreamBroker(),
        session_factory=FakeSessionFactory(),
    )
    turn = {
        "turnId": "turn-1",
        "status": "completed",
        "items": [{"type": "agentMessage", "id": "agent-1", "text": "done"}],
    }
    state = {
        "id": "thread-1",
        "turnHistory": {
            "kind": "canonical",
            "history": {
                "entitiesByKey": {"turn:turn-1": turn},
                "generation": 0,
                "isComplete": True,
                "islands": [
                    {
                        "id": "tail:0",
                        "entries": [{"key": "turn:turn-1", "value": "turn:turn-1"}],
                        "olderBoundary": {"status": "exhausted"},
                        "newerBoundary": {"status": "exhausted"},
                    }
                ],
            },
        },
        "turns": [],
    }

    materialized = manager._state_with_host_id(state, "local")

    assert materialized is not state
    assert materialized["turns"] == [turn]
    assert materialized["hostId"] == "local"
    assert state["turns"] == []


async def _wait_for_event(
    queue: asyncio.Queue[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        if predicate(event):
            return event


async def _wait_for_broker_event(
    queue: asyncio.Queue[Any], predicate: Callable[[Any], bool]
) -> Any:
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        if predicate(event):
            return event


def test_codex_manager_keeps_separate_sessions_alive(tmp_path: Path) -> None:
    async def scenario() -> None:
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        factory = FakeSessionFactory()
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )

        await manager.start()
        workspace = await manager.workspace()
        assert len(workspace.projects) == 2
        assert factory.workspace_session().list_threads_calls[-1] == {
            "archived": False,
            "limit": 100,
            "sort_key": "updated_at",
            "sort_direction": "desc",
        }

        created = await manager.start_thread(project_path="/tmp/project-c")
        assert created["thread_id"] == "thread-created"

        queue_a: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        queue_b: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        queue_plan: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        await manager.subscribe("thread-a", queue_a)
        await manager.subscribe("thread-created", queue_b)
        await manager.subscribe("thread-plan", queue_plan)

        snapshot_a = await _wait_for_event(
            queue_a, lambda event: event["type"] == "thread_snapshot"
        )
        snapshot_b = await _wait_for_event(
            queue_b, lambda event: event["type"] == "thread_snapshot"
        )
        snapshot_plan = await _wait_for_event(
            queue_plan,
            lambda event: event["type"] == "thread_snapshot",
        )
        assert snapshot_a["payload"]["thread_id"] == "thread-a"
        assert snapshot_a["payload"]["state"]["hostId"] == "local"
        assert snapshot_b["payload"]["thread_id"] == "thread-created"
        assert snapshot_plan["payload"]["state"]["requests"] == [
            {
                "id": "implement-plan:turn-1",
                "method": "item/plan/requestImplementation",
                "params": {
                    "threadId": "thread-plan",
                    "turnId": "turn-1",
                    "planContent": "Step 1",
                },
            }
        ]

        factory.by_thread_id("thread-a").emit_state(
            {"id": "thread-a", "phase": "working", "turns": []}
        )
        factory.by_thread_id("thread-created").emit_state(
            {"id": "thread-created", "phase": "working", "turns": []}
        )

        state_a = await _wait_for_event(
            queue_a,
            lambda event: (
                event["type"] == "thread_state"
                and event["payload"]["state"].get("phase") == "working"
            ),
        )
        state_b = await _wait_for_event(
            queue_b,
            lambda event: (
                event["type"] == "thread_state"
                and event["payload"]["state"].get("phase") == "working"
            ),
        )
        assert state_a["payload"]["thread_id"] == "thread-a"
        assert state_a["payload"]["state"]["hostId"] == "local"
        assert state_b["payload"]["thread_id"] == "thread-created"
        assert state_b["payload"]["state"]["hostId"] == "local"

        await manager.unsubscribe("thread-a", queue_a)
        await manager.unsubscribe("thread-created", queue_b)
        await manager.unsubscribe("thread-plan", queue_plan)

        assert factory.by_thread_id("thread-a").following_calls == [True, False]
        assert factory.by_thread_id("thread-created").following_calls == [True, False]
        assert factory.by_thread_id("thread-plan").following_calls == [True, False]

        assert factory.by_thread_id("thread-a").stopped is False
        assert factory.by_thread_id("thread-created").stopped is False
        assert factory.by_thread_id("thread-plan").stopped is False

        await manager.stop()

        assert factory.by_thread_id("thread-a").stopped is True
        assert factory.by_thread_id("thread-created").stopped is True
        assert factory.by_thread_id("thread-plan").stopped is True
        assert factory.workspace_session().stopped is True

    asyncio.run(scenario())


def test_codex_manager_tracks_first_and_last_thread_subscribers(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        factory = FakeSessionFactory()
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )
        first_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        second_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        await manager.start()
        await manager.subscribe("thread-a", first_queue)
        session = factory.by_thread_id("thread-a")

        assert session.lifecycle_calls[:3] == [
            "start",
            "following:True",
            "hydrate",
        ]

        await manager.subscribe("thread-a", second_queue)
        assert session.following_calls == [True]

        await manager.unsubscribe("thread-a", first_queue)
        assert session.following_calls == [True]

        await manager.unsubscribe("thread-a", second_queue)
        assert session.following_calls == [True, False]

        await manager.stop()

    asyncio.run(scenario())


def test_codex_manager_fans_out_session_events_to_sinks(tmp_path: Path) -> None:
    async def scenario() -> None:
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        factory = FakeSessionFactory()
        event_broker = EventStreamBroker()
        broker_queue = event_broker.subscribe()
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=event_broker,
            session_factory=factory,
        )
        sink_events: list[dict[str, Any]] = []
        manager.add_session_event_sink(lambda event: sink_events.append(event))

        await manager.start()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        await manager.subscribe("thread-a", queue)

        snapshot = await _wait_for_event(
            queue,
            lambda event: event["type"] == "thread_snapshot",
        )
        assert snapshot["payload"]["thread_id"] == "thread-a"

        replay = await _wait_for_event(
            queue,
            lambda event: event["type"] == "codex_session_event",
        )
        assert replay["payload"]["method"] == "thread-stream-state-changed"
        assert replay["payload"]["params"]["conversationId"] == "thread-a"

        factory.by_thread_id("thread-a").emit_state(
            {"id": "thread-a", "phase": "working", "turns": []}
        )

        legacy = await _wait_for_event(
            queue,
            lambda event: (
                event["type"] == "thread_state"
                and event["payload"]["state"].get("phase") == "working"
            ),
        )
        canonical = await _wait_for_event(
            queue,
            lambda event: (
                event["type"] == "codex_session_event"
                and event["payload"]["params"]["state"].get("phase") == "working"
            ),
        )
        broker_event = await _wait_for_broker_event(
            broker_queue,
            lambda event: (
                event.event == "codex_session_event"
                and event.data["params"]["state"].get("phase") == "working"
            ),
        )

        assert legacy["payload"]["state"]["hostId"] == "local"
        assert canonical["payload"]["params"]["state"]["hostId"] == "local"
        assert broker_event.data["method"] == "thread-stream-state-changed"
        assert any(
            event["payload"]["params"]["state"].get("phase") == "working"
            for event in sink_events
            if event.get("type") == "codex_session_event"
        )

        await manager.stop()

    asyncio.run(scenario())


def test_codex_manager_forwards_native_ipc_session_events(tmp_path: Path) -> None:
    async def scenario() -> None:
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        factory = NativeEventSessionFactory()
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )
        sink_events: list[dict[str, Any]] = []
        manager.add_session_event_sink(lambda event: sink_events.append(event))

        await manager.start()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        await manager.subscribe("thread-a", queue)
        await _wait_for_event(queue, lambda event: event["type"] == "thread_snapshot")

        native_event = {
            "type": "broadcast",
            "method": "thread-stream-state-changed",
            "sourceClientId": "owner-1",
            "version": 7,
            "params": {
                "conversationId": "thread-a",
                "hostId": "local",
                "type": "thread-stream-state-changed",
                "change": {
                    "type": "patches",
                    "baseRevision": 1,
                    "revision": 2,
                    "patches": [
                        {
                            "op": "replace",
                            "path": ["phase"],
                            "value": "streaming",
                        }
                    ],
                },
            },
        }
        await asyncio.sleep(0)
        factory.by_thread_id("thread-a").emit_session_event(native_event)

        forwarded = await _wait_for_event(
            queue,
            lambda event: (
                event["type"] == "codex_session_event"
                and event["payload"]["params"].get("change", {}).get("type")
                == "patches"
            ),
        )

        assert forwarded["payload"] == {
            "thread_id": "thread-a",
            "method": "thread-stream-state-changed",
            "params": native_event["params"],
            "source_client_id": "owner-1",
            "version": 7,
        }
        assert sink_events[-1] == forwarded

        await manager.stop()

    asyncio.run(scenario())


def test_codex_manager_builds_thread_defaults_from_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        codex_home = tmp_path / "codex-home"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            "\n".join(
                [
                    'model = "gpt-5.5"',
                    'model_provider = "cheftin"',
                    'model_reasoning_effort = "high"',
                    'approval_policy = "never"',
                    'approvals_reviewer = "guardian_subagent"',
                    'sandbox_mode = "read-only"',
                    'service_tier = "priority"',
                    'personality = "pragmatic"',
                    'developer_instructions = "Use concise status updates."',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        factory = FakeSessionFactory()
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )

        await manager.start()
        await manager.start_thread(project_path="/tmp/project-c")

        created_session = factory.by_thread_id("thread-created")
        assert created_session.config.model == "gpt-5.5"
        assert created_session.config.reasoning_effort == "high"
        assert created_session.config.app_server_config.env == {
            "CODEX_HOME": str(codex_home)
        }
        assert created_session.config.default_thread_params == {
            "cwd": str(config_service.project_root),
            "model": "gpt-5.5",
            "model_provider": "cheftin",
            "approval_policy": "never",
            "approvals_reviewer": "guardian_subagent",
            "sandbox": "read-only",
            "service_tier": "priority",
            "personality": "pragmatic",
            "developer_instructions": "Use concise status updates.",
            "config": {"model_reasoning_effort": "high"},
        }
        assert created_session.start_new_thread_calls[-1] == {
            "cwd": config_service.resolve_project_path("/tmp/project-c")
        }

        await manager.stop()

    asyncio.run(scenario())


def test_codex_manager_updates_cached_mode_for_future_snapshots(tmp_path: Path) -> None:
    async def scenario() -> None:
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        factory = FakeSessionFactory()
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )
        default_collaboration_mode = {
            "mode": "default",
            "settings": {
                "model": "gpt-5.4",
                "reasoning_effort": "medium",
                "developer_instructions": None,
            },
        }

        await manager.start()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        await manager.subscribe("thread-plan", queue)
        await _wait_for_event(
            queue,
            lambda event: event["type"] == "thread_snapshot",
        )

        await manager.set_collaboration_mode("thread-plan", default_collaboration_mode)
        state_event = await _wait_for_event(
            queue,
            lambda event: (
                event["type"] == "thread_state"
                and event["payload"]["state"].get("latestCollaborationMode")
                == default_collaboration_mode
            ),
        )

        assert (
            state_event["payload"]["state"]["latestCollaborationMode"]
            == default_collaboration_mode
        )
        assert (
            factory.by_thread_id("thread-plan").collaboration_modes[-1]
            == default_collaboration_mode
        )

        await manager.unsubscribe("thread-plan", queue)
        refreshed_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        await manager.subscribe("thread-plan", refreshed_queue)
        refreshed_snapshot = await _wait_for_event(
            refreshed_queue,
            lambda event: event["type"] == "thread_snapshot",
        )

        assert (
            refreshed_snapshot["payload"]["state"]["latestCollaborationMode"]
            == default_collaboration_mode
        )

        await manager.stop()

    asyncio.run(scenario())


def test_codex_controller_http_and_websocket_contract(tmp_path: Path) -> None:
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)

    with client:
        workspace_response = client.get("/api/codex/workspace")
        assert workspace_response.status_code == 200
        assert len(workspace_response.json()["projects"]) == 2
        sessions = [
            session
            for project in workspace_response.json()["projects"]
            for session in project["sessions"]
        ]
        thread_a = next(
            session for session in sessions if session["thread_id"] == "thread-a"
        )
        project_a = next(
            project
            for project in workspace_response.json()["projects"]
            if project["project_path"] == "/tmp/project-a"
        )
        assert project_a["host_id"] == "local"
        assert thread_a["host_id"] == "local"
        assert thread_a["cwd"] == "/tmp/project-a"
        assert thread_a["status"] == "idle"
        assert thread_a["source"] == "appServer"
        assert workspace_response.json()["remote_connections"] == []
        assert workspace_response.json()["active_remote_connection_id"] == ""

        create_response = client.post(
            "/api/codex/threads",
            json={"project_path": "/tmp/project-c"},
        )
        assert create_response.status_code == 201
        assert create_response.json()["thread_id"] == "thread-created"

        state_response = client.get("/api/codex/threads/thread-created/state")
        assert state_response.status_code == 200
        assert state_response.json()["state"]["id"] == "thread-created"

        rename_response = client.put(
            "/api/codex/threads/thread-created/name",
            json={"name": "Renamed"},
        )
        assert rename_response.status_code == 200
        assert rename_response.json()["ok"] is True

        archive_response = client.post("/api/codex/threads/thread-created/archive")
        assert archive_response.status_code == 201
        assert archive_response.json()["thread_id"] == "thread-created"

        unarchive_response = client.post("/api/codex/threads/thread-created/unarchive")
        assert unarchive_response.status_code == 201
        assert unarchive_response.json()["ok"] is True

        with client.websocket_connect("/api/codex/ws") as ws:

            def receive_until(
                predicate: Callable[[dict[str, Any]], bool],
            ) -> list[dict[str, Any]]:
                messages: list[dict[str, Any]] = []
                while True:
                    message = ws.receive_json()
                    messages.append(message)
                    if predicate(message):
                        return messages

            ready = ws.receive_json()
            assert ready["type"] == "connection_ready"

            ws.send_json({"id": "list-1", "type": "list_threads", "payload": {}})
            list_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "list-1"
                )
            )
            assert any(message["type"] == "workspace" for message in list_messages)
            assert factory.workspace_session().list_threads_calls[-1] == {
                "archived": False,
                "limit": 100,
                "sort_key": "updated_at",
                "sort_direction": "desc",
            }

            ws.send_json(
                {
                    "id": "sub-a",
                    "type": "subscribe_thread",
                    "payload": {"thread_id": "thread-a"},
                }
            )
            sub_a = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "sub-a"
                )
            )
            assert any(
                message["type"] in {"thread_snapshot", "thread_state"}
                for message in sub_a
            )

            ws.send_json(
                {
                    "id": "sub-b",
                    "type": "subscribe_thread",
                    "payload": {"thread_id": "thread-b"},
                }
            )
            sub_b = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "sub-b"
                )
            )
            assert any(
                message["type"] in {"thread_snapshot", "thread_state"}
                for message in sub_b
            )

            factory.by_thread_id("thread-a").emit_state(
                {"id": "thread-a", "phase": "working", "turns": []}
            )
            thread_state = receive_until(
                lambda message: (
                    message.get("type") == "thread_state"
                    and message["payload"]["state"].get("phase") == "working"
                )
            )
            assert thread_state[-1]["payload"]["thread_id"] == "thread-a"

            ws.send_json(
                {
                    "id": "prompt-1",
                    "type": "send_prompt",
                    "payload": {
                        "thread_id": "thread-a",
                        "prompt": "hello",
                        "collaboration_mode": {"mode": "build"},
                    },
                }
            )
            prompt_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "prompt-1"
                )
            )
            assert factory.by_thread_id("thread-a").run_prompt_calls[-1] == (
                "hello",
                False,
                {"mode": "build"},
                None,
                None,
                None,
                None,
            )

            default_collaboration_mode = {
                "mode": "default",
                "settings": {
                    "model": "gpt-5.4",
                    "reasoning_effort": "medium",
                    "developer_instructions": None,
                },
            }
            ws.send_json(
                {
                    "id": "prompt-default",
                    "type": "send_prompt",
                    "payload": {
                        "thread_id": "thread-a",
                        "prompt": "implement",
                        "collaboration_mode": default_collaboration_mode,
                    },
                }
            )
            receive_until(
                lambda message: (
                    message.get("type") == "ack"
                    and message.get("id") == "prompt-default"
                )
            )
            assert factory.by_thread_id("thread-a").run_prompt_calls[-1] == (
                "implement",
                False,
                default_collaboration_mode,
                None,
                None,
                None,
                None,
            )

            ws.send_json(
                {
                    "id": "prompt-permissions",
                    "type": "send_prompt",
                    "payload": {
                        "thread_id": "thread-a",
                        "prompt": "use full access",
                        "approval_policy": "never",
                        "approvals_reviewer": "user",
                        "sandbox_policy": {"type": "dangerFullAccess"},
                    },
                }
            )
            receive_until(
                lambda message: (
                    message.get("type") == "ack"
                    and message.get("id") == "prompt-permissions"
                )
            )
            assert factory.by_thread_id("thread-a").run_prompt_calls[-1] == (
                "use full access",
                False,
                None,
                None,
                "never",
                "user",
                {"type": "dangerFullAccess"},
            )

            ws.send_json(
                {
                    "id": "prompt-image",
                    "type": "send_prompt",
                    "payload": {
                        "thread_id": "thread-a",
                        "prompt": "",
                        "attachments": [
                            {
                                "type": "image",
                                "imageUrl": "data:image/png;base64,abc",
                                "name": "preview.png",
                            }
                        ],
                    },
                }
            )
            receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "prompt-image"
                )
            )
            assert factory.by_thread_id("thread-a").run_prompt_calls[-1] == (
                "",
                False,
                None,
                [
                    {"type": "text", "text": "", "text_elements": []},
                    {
                        "type": "image",
                        "url": "data:image/png;base64,abc",
                        "detail": "auto",
                    },
                ],
                None,
                None,
                None,
            )

            ws.send_json(
                {
                    "id": "prompt-file",
                    "type": "send_prompt",
                    "payload": {
                        "thread_id": "thread-a",
                        "prompt": "review this file",
                        "attachments": [
                            {
                                "type": "mention",
                                "name": "main.py",
                                "path": "/tmp/project/main.py",
                            }
                        ],
                    },
                }
            )
            receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "prompt-file"
                )
            )
            assert factory.by_thread_id("thread-a").run_prompt_calls[-1] == (
                "review this file",
                False,
                None,
                [
                    {
                        "type": "text",
                        "text": "review this file",
                        "text_elements": [],
                    },
                    {
                        "type": "mention",
                        "name": "main.py",
                        "path": "/tmp/project/main.py",
                    },
                ],
                None,
                None,
                None,
            )

            ws.send_json(
                {
                    "id": "prompt-skill",
                    "type": "send_prompt",
                    "payload": {
                        "thread_id": "thread-a",
                        "prompt": "use this skill",
                        "attachments": [
                            {
                                "type": "skill",
                                "name": "deep-research",
                                "path": "/skills/deep-research",
                            }
                        ],
                    },
                }
            )
            receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "prompt-skill"
                )
            )
            assert factory.by_thread_id("thread-a").run_prompt_calls[-1] == (
                "use this skill",
                False,
                None,
                [
                    {
                        "type": "text",
                        "text": "use this skill",
                        "text_elements": [],
                    },
                    {
                        "type": "skill",
                        "name": "deep-research",
                        "path": "/skills/deep-research",
                    },
                ],
                None,
                None,
                None,
            )

            ws.send_json(
                {
                    "id": "skills-1",
                    "type": "list_skills",
                    "payload": {
                        "thread_id": "thread-a",
                        "cwd": "/tmp/project-a",
                    },
                }
            )
            skills_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "skills-1"
                )
            )
            skills_ack = next(
                message
                for message in skills_messages
                if message.get("type") == "ack" and message.get("id") == "skills-1"
            )
            assert skills_ack["payload"]["skills"] == [
                {
                    "name": "deep-research",
                    "display_name": "Deep Research",
                    "description": "Research thoroughly",
                    "short_description": "Research thoroughly",
                    "path": "/skills/deep-research",
                    "scope": "user",
                    "enabled": True,
                    "interface": {
                        "displayName": "Deep Research",
                        "shortDescription": "Research thoroughly",
                    },
                    "cwd": "/tmp/project-a",
                }
            ]
            assert factory.by_thread_id("thread-a").skills_list_calls[-1] == {
                "cwds": ["/tmp/project-a"],
            }

            ws.send_json(
                {
                    "id": "input-1",
                    "type": "submit_user_input_response",
                    "payload": {
                        "thread_id": "thread-a",
                        "request_id": "request-1",
                        "response": {"answer": "ok"},
                    },
                }
            )
            input_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "input-1"
                )
            )
            assert factory.by_thread_id("thread-a").user_input_responses[-1] == (
                "request-1",
                {"answer": "ok"},
            )

            ws.send_json(
                {
                    "id": "goal-set-1",
                    "type": "set_thread_goal",
                    "payload": {
                        "thread_id": "thread-a",
                        "objective": "Finish the web goal mode",
                        "status": "active",
                        "token_budget": 12000,
                    },
                }
            )
            goal_set_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "goal-set-1"
                )
            )
            assert goal_set_messages[-1]["payload"]["goal"]["objective"] == (
                "Finish the web goal mode"
            )
            assert factory.by_thread_id("thread-a").goal_set_calls[-1] == {
                "objective": "Finish the web goal mode",
                "status": "active",
                "token_budget": 12000,
            }

            ws.send_json(
                {
                    "id": "goal-get-1",
                    "type": "get_thread_goal",
                    "payload": {"thread_id": "thread-a"},
                }
            )
            goal_get_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "goal-get-1"
                )
            )
            assert goal_get_messages[-1]["payload"]["goal"]["status"] == "active"

            ws.send_json(
                {
                    "id": "goal-clear-1",
                    "type": "clear_thread_goal",
                    "payload": {"thread_id": "thread-a"},
                }
            )
            goal_clear_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "goal-clear-1"
                )
            )
            assert goal_clear_messages[-1]["payload"]["cleared"] is True
            assert factory.by_thread_id("thread-a").goal_clear_calls == 1

            ws.send_json(
                {
                    "id": "archive-1",
                    "type": "archive_thread",
                    "payload": {"thread_id": "thread-a"},
                }
            )
            archive_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "archive-1"
                )
            )
            assert any(
                message["type"] == "thread_archived" for message in archive_messages
            )

            ws.send_json(
                {
                    "id": "fork-1",
                    "type": "fork_thread",
                    "payload": {"thread_id": "thread-b"},
                }
            )
            fork_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "fork-1"
                )
            )
            assert fork_messages[-1]["payload"]["thread_id"] == "thread-forked"
            assert any(message["type"] == "workspace" for message in fork_messages)
            assert factory.by_thread_id("thread-forked").fork_calls[-1] == "thread-b"

            ws.send_json(
                {
                    "id": "sub-fork",
                    "type": "subscribe_thread",
                    "payload": {"thread_id": "thread-forked"},
                }
            )
            sub_fork = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "sub-fork"
                )
            )
            assert any(
                message["type"] == "thread_snapshot"
                and message["payload"]["thread_id"] == "thread-forked"
                for message in sub_fork
            )

            ws.send_json(
                {
                    "id": "unarchive-1",
                    "type": "unarchive_thread",
                    "payload": {"thread_id": "thread-a"},
                }
            )
            unarchive_messages = receive_until(
                lambda message: (
                    message.get("type") == "ack" and message.get("id") == "unarchive-1"
                )
            )
            assert any(
                message["type"] == "thread_unarchived" for message in unarchive_messages
            )

            ws.send_json(
                {
                    "id": "bad-1",
                    "type": "send_prompt",
                    "payload": {"thread_id": "thread-a"},
                }
            )
            error_messages = receive_until(
                lambda message: (
                    message.get("type") == "error" and message.get("id") == "bad-1"
                )
            )
            error_message = error_messages[-1]
            assert error_message["type"] == "error"
            assert error_message["code"] == "bad_request"


def test_codex_remote_connection_configures_ssh_app_server(tmp_path: Path) -> None:
    factory = FakeSessionFactory()
    config_service, client = build_app(tmp_path, factory)

    connection = config_service.save_codex_remote_connection(
        CodexRemoteConnectionPayload(
            display_name="Build host",
            ssh_host="builder.example.com",
            ssh_port=2222,
            identity_file="~/.ssh/build",
            remote_path="/srv/project",
            auto_connect=True,
        )
    )

    with client:
        workspace_response = client.get("/api/codex/workspace")

    assert workspace_response.status_code == 200
    payload = workspace_response.json()
    assert payload["active_remote_connection_id"] == connection.id
    assert payload["remote_connections"][0]["display_name"] == "Build host"
    assert payload["remote_connection_statuses"][connection.id]["status"] == "connected"

    session = factory.workspace_session()
    assert session.config.host_id == f"ssh:{connection.id}"
    app_server_config = session.config.app_server_config
    assert app_server_config.launch_args_override is None
    assert app_server_config.ssh_websocket is not None
    ssh_config = app_server_config.ssh_websocket.connection
    assert ssh_config.host == "builder.example.com"
    assert ssh_config.port == 2222
    assert ssh_config.identity == "~/.ssh/build"
    assert app_server_config.ssh_websocket.remote_cwd == "/srv/project"

    create_response = client.post("/api/codex/threads", json={})
    assert create_response.status_code == 201
    created_session = factory.by_thread_id("thread-created")
    assert created_session.start_new_thread_calls[0]["cwd"] == "/srv/project"


def test_codex_remote_connection_routes_persist_and_switch_hosts(
    tmp_path: Path,
) -> None:
    factory = FakeSessionFactory()
    config_service, client = build_app(tmp_path, factory)

    with client:
        initial_workspace = client.get("/api/codex/workspace")
        assert initial_workspace.status_code == 200
        local_session = factory.workspace_session()
        assert local_session.config.host_id == "local"

        create_response = client.post(
            "/api/codex/remote-connections",
            json={
                "display_name": "Remote",
                "ssh_host": "user@remote",
                "ssh_port": 22,
                "identity_file": "",
                "remote_path": "~/repo",
                "auto_connect": True,
            },
        )
        assert create_response.status_code == 201
        connection_id = create_response.json()["connection"]["id"]
        assert local_session.stopped is True

        list_response = client.get("/api/codex/remote-connections")
        assert list_response.status_code == 200
        assert list_response.json()["active_connection_id"] == connection_id

        remote_workspace = client.get("/api/codex/workspace")
        assert remote_workspace.status_code == 200
        assert factory.sessions[-1].config.host_id == f"ssh:{connection_id}"
        assert (
            remote_workspace.json()["remote_connection_statuses"][connection_id][
                "status"
            ]
            == "connected"
        )

        local_response = client.post("/api/codex/remote-connections/activate-local")
        assert local_response.status_code == 201
        assert (
            config_service.load_web_settings().codex.active_remote_connection_id == ""
        )

        activate_response = client.post(
            f"/api/codex/remote-connections/{connection_id}/activate"
        )
        assert activate_response.status_code == 201
        assert (
            config_service.load_web_settings().codex.active_remote_connection_id
            == connection_id
        )
        restart_response = client.post(
            f"/api/codex/remote-connections/{connection_id}/restart"
        )
        assert restart_response.status_code == 201
        status_response = client.get("/api/codex/remote-connections")
        assert (
            status_response.json()["statuses"][connection_id]["status"] == "connecting"
        )


def test_codex_remote_connection_auto_connect_controls_active_host(
    tmp_path: Path,
) -> None:
    config_service = AppConfigService(
        project_root=tmp_path / "project",
        home_dir=tmp_path / "home",
    )

    connection = config_service.save_codex_remote_connection(
        CodexRemoteConnectionPayload(
            display_name="Manual host",
            ssh_host="manual.example.com",
            auto_connect=False,
        )
    )

    assert config_service.load_web_settings().codex.active_remote_connection_id == ""

    config_service.set_active_codex_remote_connection(connection.id)
    config_service.save_codex_remote_connection(
        CodexRemoteConnectionPayload(
            display_name="Manual host",
            ssh_host="manual.example.com",
            auto_connect=False,
        ),
        connection_id=connection.id,
    )

    assert config_service.load_web_settings().codex.active_remote_connection_id == ""


def test_codex_remote_connection_install_uses_official_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory()
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        connection = config_service.save_codex_remote_connection(
            CodexRemoteConnectionPayload(
                display_name="Build host",
                ssh_host="builder.example.com",
                auto_connect=True,
            )
        )
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )
        commands: list[tuple[str, ...]] = []

        class FakeProcess:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return (b"installed", b"")

            def kill(self) -> None:
                return None

            async def wait(self) -> None:
                return None

        async def fake_create_subprocess_exec(
            *args: str, **_kwargs: Any
        ) -> FakeProcess:
            commands.append(args)
            return FakeProcess()

        monkeypatch.setattr(
            "yier_web.codex.ipc_manager.asyncio.create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        result = await manager.install_remote_codex(connection.id)

        assert result.ok is True
        assert "installed" in result.detail
        assert commands
        assert "https://chatgpt.com/codex/install.sh" in commands[0][-1]
        statuses = manager.remote_connections().statuses
        assert statuses[connection.id].status == "connecting"
        assert statuses[connection.id].detail == "Restarting connection"

    asyncio.run(scenario())


def test_codex_remote_connection_api_key_login_uses_remote_app_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory()
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        connection = config_service.save_codex_remote_connection(
            CodexRemoteConnectionPayload(
                display_name="Build host",
                ssh_host="builder.example.com",
                auto_connect=False,
            )
        )
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )
        calls: list[tuple[str, Any]] = []

        class FakeAsyncCodexClient:
            def __init__(self, *, config: Any) -> None:
                calls.append(("config", config))

            async def __aenter__(self) -> "FakeAsyncCodexClient":
                calls.append(("enter", None))
                return self

            async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
                calls.append(("exit", None))

            async def initialize(self) -> None:
                calls.append(("initialize", None))

            async def account_login_start(self, params: dict[str, Any]) -> None:
                calls.append(("login", params))

            async def account_read(
                self, params: dict[str, Any]
            ) -> SimpleNamespace:
                calls.append(("read", params))
                return SimpleNamespace(
                    account=SimpleNamespace(root=SimpleNamespace(type="apiKey"))
                )

        monkeypatch.setattr(
            "yier_web.codex.ipc_manager.AsyncCodexClient",
            FakeAsyncCodexClient,
        )

        result = await manager.login_remote_api_key(connection.id, "sk-test")

        assert result.ok is True
        assert result.detail == "Signed in with apiKey."
        assert ("login", {"type": "apiKey", "apiKey": "sk-test"}) in calls
        assert ("read", {"refreshToken": False}) in calls
        statuses = manager.remote_connections().statuses
        assert statuses[connection.id].status == "connected"

    asyncio.run(scenario())


def test_codex_remote_chatgpt_login_starts_port_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        factory = FakeSessionFactory()
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        connection = config_service.save_codex_remote_connection(
            CodexRemoteConnectionPayload(
                display_name="Build host",
                ssh_host="builder.example.com",
                ssh_port=2222,
                auto_connect=False,
            )
        )
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=factory,
        )
        client_calls: list[tuple[str, Any]] = []
        subprocess_calls: list[tuple[str, ...]] = []

        class FakeLoginResponse:
            root = SimpleNamespace(
                type="chatgpt",
                auth_url="https://chatgpt.com/login",
                login_id="login-1",
            )

        class FakeAsyncCodexClient:
            def __init__(self, *, config: Any) -> None:
                client_calls.append(("config", config))

            async def __aenter__(self) -> "FakeAsyncCodexClient":
                return self

            async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
                return None

            async def initialize(self) -> None:
                client_calls.append(("initialize", None))

            async def account_login_start(
                self,
                params: dict[str, Any],
            ) -> FakeLoginResponse:
                client_calls.append(("account/login/start", params))
                return FakeLoginResponse()

        class FakeProcess:
            returncode = None
            stderr = None

            def terminate(self) -> None:
                self.returncode = -15

            def kill(self) -> None:
                self.returncode = -9

            async def wait(self) -> None:
                if self.returncode is not None:
                    return None
                await asyncio.sleep(10)

        async def fake_create_subprocess_exec(
            *args: str, **_kwargs: Any
        ) -> FakeProcess:
            subprocess_calls.append(args)
            return FakeProcess()

        monkeypatch.setattr(
            "yier_web.codex.ipc_manager.AsyncCodexClient",
            FakeAsyncCodexClient,
        )
        monkeypatch.setattr(
            "yier_web.codex.ipc_manager.asyncio.create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        result = await manager.start_remote_chatgpt_login(connection.id)

        assert result.ok is True
        assert result.auth_url == "https://chatgpt.com/login"
        assert (
            "account/login/start",
            {"type": "chatgpt", "codexStreamlinedLogin": True},
        ) in client_calls
        assert subprocess_calls
        args = subprocess_calls[0]
        assert "-N" in args
        assert "-L" in args
        assert "1455:127.0.0.1:1455" in args
        assert "ExitOnForwardFailure=yes" in args
        statuses = manager.remote_connections().statuses
        assert statuses[connection.id].status == "connecting"

        await manager.stop_remote_chatgpt_login(connection.id)

    asyncio.run(scenario())


def test_codex_controller_lists_host_filesystem(tmp_path: Path) -> None:
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)
    alpha_dir = tmp_path / "alpha"
    beta_dir = tmp_path / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()
    code_file = tmp_path / "main.py"
    image_file = tmp_path / "preview.PNG"
    code_file.write_text("print('hello')\n")
    image_file.write_bytes(b"png")

    with client:
        response = client.get(
            "/api/codex/filesystem",
            params={"path": str(tmp_path)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == str(tmp_path.resolve())
        assert payload["parent_path"] == str(tmp_path.resolve().parent)
        assert payload["roots"]
        assert payload["roots"][0]["kind"] == "directory"

        entries = payload["entries"]
        by_name = {entry["name"]: entry for entry in entries}
        assert by_name["alpha"]["kind"] == "directory"
        assert by_name["beta"]["kind"] == "directory"
        assert by_name["main.py"]["kind"] == "file"
        assert by_name["main.py"]["extension"] == ".py"
        assert by_name["preview.PNG"]["extension"] == ".png"

        first_file_index = next(
            index for index, entry in enumerate(entries) if entry["kind"] == "file"
        )
        last_directory_index = max(
            index for index, entry in enumerate(entries) if entry["kind"] == "directory"
        )
        assert last_directory_index < first_file_index


def test_codex_controller_rejects_invalid_filesystem_paths(tmp_path: Path) -> None:
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory\n")

    with client:
        file_response = client.get(
            "/api/codex/filesystem",
            params={"path": str(file_path)},
        )
        missing_response = client.get(
            "/api/codex/filesystem",
            params={"path": str(tmp_path / "missing")},
        )

        assert file_response.status_code == 400
        assert "not a directory" in file_response.json()["detail"]
        assert missing_response.status_code == 404
        assert "Path not found" in missing_response.json()["detail"]


def test_codex_controller_serves_host_images(tmp_path: Path) -> None:
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)
    image_path = tmp_path / "preview.png"
    image_bytes = b"\x89PNG\r\n\x1a\n"
    image_path.write_bytes(image_bytes)

    with client:
        preview_response = client.get(
            "/api/codex/image",
            params={"path": str(image_path)},
        )
        download_response = client.get(
            "/api/codex/image",
            params={"path": str(image_path), "download": "true"},
        )

        assert preview_response.status_code == 200
        assert preview_response.content == image_bytes
        assert preview_response.headers["content-type"].startswith("image/png")
        assert "inline" in preview_response.headers["content-disposition"]

        assert download_response.status_code == 200
        assert download_response.content == image_bytes
        assert "attachment" in download_response.headers["content-disposition"]
        assert "preview.png" in download_response.headers["content-disposition"]


def test_codex_controller_rejects_non_image_file_preview(tmp_path: Path) -> None:
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)
    text_path = tmp_path / "notes.txt"
    text_path.write_text("not an image\n", encoding="utf-8")

    with client:
        response = client.get(
            "/api/codex/image",
            params={"path": str(text_path)},
        )

        assert response.status_code == 400
        assert "not a supported image" in response.json()["detail"]


def test_codex_websocket_embed_token_allows_unauthenticated_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YIER_AUTH_PASSWORD", "deploy-secret")
    monkeypatch.setenv("YIER_CODEX_EMBED_TOKEN", "embed-secret")
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)

    with client:
        with client.websocket_connect(
            "/api/codex/ws",
            params={"embed_token": "embed-secret"},
        ) as ws:
            ready = ws.receive_json()
            assert ready["type"] == "connection_ready"

            ws.send_json({"id": "list-embed", "type": "list_threads", "payload": {}})
            while True:
                message = ws.receive_json()
                if message.get("type") == "ack" and message.get("id") == "list-embed":
                    assert message["ok"] is True
                    break


def test_codex_websocket_rejects_missing_or_invalid_embed_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YIER_AUTH_PASSWORD", "deploy-secret")
    monkeypatch.setenv("YIER_CODEX_EMBED_TOKEN", "embed-secret")
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)

    with client:
        with client.websocket_connect("/api/codex/ws") as ws:
            message = ws.receive_json()
            assert message["type"] == "error"
            assert message["code"] == "unauthorized"

        with client.websocket_connect(
            "/api/codex/ws",
            params={"embed_token": "wrong-secret"},
        ) as ws:
            message = ws.receive_json()
            assert message["type"] == "error"
            assert message["code"] == "unauthorized"


def test_codex_websocket_keeps_authenticated_access_with_password_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YIER_AUTH_PASSWORD", "deploy-secret")
    factory = FakeSessionFactory()
    _, client = build_app(tmp_path, factory)

    with client:
        login_response = client.post(
            "/api/auth/login",
            json={"password": "deploy-secret"},
        )
        assert login_response.status_code == 201

        with client.websocket_connect("/api/codex/ws") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "connection_ready"


def test_codex_websocket_disconnect_during_cleanup_is_quiet(tmp_path: Path) -> None:
    async def scenario() -> None:
        config_service = AppConfigService(
            project_root=tmp_path / "project",
            home_dir=tmp_path / "home",
        )
        manager = CodexIpcManager(
            config_service=config_service,
            event_broker=EventStreamBroker(),
            session_factory=FakeSessionFactory(),
        )
        socket = DisconnectingCodexSocket(manager)

        controller = CodexController.__new__(CodexController)
        await CodexController.__dict__["websocket_handler"].fn(
            controller,
            socket,
        )

        assert socket.accepted is True

    asyncio.run(scenario())
