from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yier_web.codex.ipc_manager import CodexIpcManager, CodexSubscriberQueue


def _payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _required_payload_text(payload: dict[str, Any], key: str) -> str:
    value = _payload_text(payload, key)
    if not value:
        raise ValueError(f"{key} is required.")
    return value


def _payload_dict(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else None


def _payload_dict_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _payload_text_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [
        normalized
        for item in value
        if isinstance(item, str) and (normalized := item.strip())
    ]


@dataclass(slots=True)
class CodexWsCommandContext:
    manager: CodexIpcManager
    payload: dict[str, Any]
    outbox: CodexSubscriberQueue
    subscribed_thread_ids: set[str]


class CodexWsCommandStrategy:
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        raise NotImplementedError


async def _publish_workspace(
    manager: CodexIpcManager,
    outbox: CodexSubscriberQueue,
) -> dict[str, Any]:
    workspace = await manager.workspace()
    payload = workspace.model_dump(mode="json")
    await outbox.put(
        {
            "type": "workspace",
            "payload": payload,
        }
    )
    return payload


class ListThreadsCommandStrategy(CodexWsCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        return await _publish_workspace(context.manager, context.outbox)


class StartThreadCommandStrategy(CodexWsCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        result = await context.manager.start_thread(
            project_path=_payload_text(context.payload, "project_path") or None,
            host_id=_payload_text(context.payload, "host_id") or "local",
        )
        await _publish_workspace(context.manager, context.outbox)
        return result


class ThreadCommandStrategy(CodexWsCommandStrategy):
    def thread_id(self, context: CodexWsCommandContext) -> str:
        return _required_payload_text(context.payload, "thread_id")

    def host_id(self, context: CodexWsCommandContext) -> str | None:
        return _payload_text(context.payload, "host_id") or None


class SubscribeThreadCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        state = await context.manager.subscribe(
            thread_id,
            context.outbox,
            host_id=self.host_id(context),
        )
        context.subscribed_thread_ids.add(thread_id)
        return {"thread_id": thread_id, "state": state}


class SubscribeThreadDeltaCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        payload = await context.manager.subscribe_with_initial_turn_delta(
            thread_id,
            context.outbox,
            cached_turn_ids=_payload_text_list(
                context.payload,
                "cached_turn_ids",
            ),
            refresh_turn_ids=_payload_text_list(
                context.payload,
                "refresh_turn_ids",
            ),
            host_id=self.host_id(context),
        )
        context.subscribed_thread_ids.add(thread_id)
        return payload


class UnsubscribeThreadCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        await context.manager.unsubscribe(thread_id, context.outbox)
        context.subscribed_thread_ids.discard(thread_id)
        return {"thread_id": thread_id}


class SendPromptCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        prompt = _payload_text(context.payload, "prompt")
        attachments = _payload_dict_list(context.payload, "attachments")
        if not prompt and not attachments:
            raise ValueError("prompt or attachments is required.")
        await context.manager.send_prompt(
            thread_id,
            prompt,
            collaboration_mode=_payload_dict(context.payload, "collaboration_mode"),
            attachments=attachments,
            approval_policy=_payload_text(context.payload, "approval_policy") or None,
            approvals_reviewer=_payload_text(context.payload, "approvals_reviewer")
            or None,
            sandbox_policy=_payload_dict(context.payload, "sandbox_policy"),
        )
        return {"thread_id": thread_id}


class SteerPromptCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        prompt = _required_payload_text(context.payload, "prompt")
        await context.manager.steer_prompt(thread_id, prompt)
        return {"thread_id": thread_id}


class EnqueueFollowupCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        prompt = _required_payload_text(context.payload, "prompt")
        return await context.manager.enqueue_followup(thread_id, prompt)


class RemoveFollowupCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        message_id = _required_payload_text(context.payload, "message_id")
        await context.manager.remove_followup(thread_id, message_id)
        return {"thread_id": thread_id, "message_id": message_id}


class InterruptTurnCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        turn_id = _payload_text(context.payload, "turn_id") or None
        interrupted = await context.manager.interrupt_turn(thread_id, turn_id)
        return {"thread_id": thread_id, "forwarded": interrupted}


class CompactThreadCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        forwarded = await context.manager.compact_thread(thread_id)
        return {"thread_id": thread_id, "forwarded": forwarded}


class SetThreadGoalCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        response = await context.manager.set_thread_goal(
            thread_id,
            objective=_payload_text(context.payload, "objective") or None,
            status=_payload_text(context.payload, "status") or None,
            token_budget=_payload_int(context.payload, "token_budget")
            or _payload_int(context.payload, "tokenBudget"),
        )
        return {"thread_id": thread_id, **response}


class GetThreadGoalCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        goal = await context.manager.get_thread_goal(thread_id)
        return {"thread_id": thread_id, "goal": goal}


class ClearThreadGoalCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        response = await context.manager.clear_thread_goal(thread_id)
        return {"thread_id": thread_id, **response}


class SetCollaborationModeCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        await context.manager.set_collaboration_mode(
            thread_id,
            _payload_dict(context.payload, "collaboration_mode"),
        )
        return {"thread_id": thread_id}


class SubmitUserInputResponseCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        request_id = _required_payload_text(context.payload, "request_id")
        submitted = await context.manager.submit_user_input_response(
            thread_id,
            request_id,
            _payload_dict(context.payload, "response") or {"answers": {}},
        )
        return {"thread_id": thread_id, "submitted": submitted}


class RenameThreadCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        name = _required_payload_text(context.payload, "name")
        await context.manager.rename_thread(thread_id, name)
        return {"thread_id": thread_id}


class ArchiveThreadCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        await context.manager.archive_thread(thread_id)
        return {"thread_id": thread_id}


class ForkThreadCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        result = await context.manager.fork_thread(
            thread_id,
            host_id=self.host_id(context),
        )
        await _publish_workspace(context.manager, context.outbox)
        return result


class UnarchiveThreadCommandStrategy(ThreadCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = self.thread_id(context)
        await context.manager.unarchive_thread(
            thread_id,
            host_id=self.host_id(context),
        )
        return {"thread_id": thread_id}


class ListSkillsCommandStrategy(CodexWsCommandStrategy):
    async def execute(self, context: CodexWsCommandContext) -> dict[str, Any]:
        thread_id = _payload_text(context.payload, "thread_id") or None
        cwd = _payload_text(context.payload, "cwd") or None
        force_reload = bool(
            context.payload.get("force_reload") or context.payload.get("forceReload")
        )
        skills = await context.manager.list_skills(
            thread_id=thread_id,
            host_id=_payload_text(context.payload, "host_id") or None,
            cwd=cwd,
            force_reload=force_reload,
        )
        return {"skills": skills}


class CodexWsCommandStrategyFactory:
    def __init__(self) -> None:
        self.strategies: dict[str, CodexWsCommandStrategy] = {
            "list_threads": ListThreadsCommandStrategy(),
            "start_thread": StartThreadCommandStrategy(),
            "subscribe_thread": SubscribeThreadCommandStrategy(),
            "subscribe_thread_delta": SubscribeThreadDeltaCommandStrategy(),
            "unsubscribe_thread": UnsubscribeThreadCommandStrategy(),
            "send_prompt": SendPromptCommandStrategy(),
            "steer_prompt": SteerPromptCommandStrategy(),
            "enqueue_followup": EnqueueFollowupCommandStrategy(),
            "remove_followup": RemoveFollowupCommandStrategy(),
            "interrupt_turn": InterruptTurnCommandStrategy(),
            "compact_thread": CompactThreadCommandStrategy(),
            "set_thread_goal": SetThreadGoalCommandStrategy(),
            "get_thread_goal": GetThreadGoalCommandStrategy(),
            "clear_thread_goal": ClearThreadGoalCommandStrategy(),
            "set_collaboration_mode": SetCollaborationModeCommandStrategy(),
            "submit_user_input_response": SubmitUserInputResponseCommandStrategy(),
            "rename_thread": RenameThreadCommandStrategy(),
            "archive_thread": ArchiveThreadCommandStrategy(),
            "fork_thread": ForkThreadCommandStrategy(),
            "unarchive_thread": UnarchiveThreadCommandStrategy(),
            "list_skills": ListSkillsCommandStrategy(),
        }

    def get(self, message_type: str) -> CodexWsCommandStrategy:
        strategy = self.strategies.get(message_type)
        if strategy is None:
            raise ValueError(f"Unsupported Codex command: {message_type}")
        return strategy
