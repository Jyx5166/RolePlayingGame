from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from runtime.contracts import RuntimeScope, RuntimeAccessError, execution_frame
from tools.contracts import DM_TOOLS, ROLE_TOOLS, ToolResult
from tools.domain import DomainActionError, GameActions


class ToolGateway:
    def __init__(self, service: Any, user_id: int, dm: Any) -> None:
        self.service, self.user_id, self.dm = service, user_id, dm
        self.runtime = service.runtime_store
        self.actions = GameActions(dm)

    async def execute(self, scope: RuntimeScope, call_id: str) -> ToolResult:
        record = self.runtime.tool_record(scope, call_id)
        # A committed receipt is authoritative even if its graph checkpoint was not saved.
        if record["result"] is not None:
            return ToolResult.model_validate(record["result"])
        before = self.dm.export_runtime_snapshot()
        pending = deepcopy(self.dm._require_state().persistence_events)
        result: ToolResult
        try:
            game = self.runtime.assert_scope(scope, expected_epoch=record["phase_epoch"])
            if record["run_id"] != scope.run_id or record["agent_instance_id"] != scope.agent_instance_id:
                raise RuntimeAccessError("工具属于已失效的执行实例")
            frame = execution_frame.get()
            if frame is None or (frame.game_id, frame.run_id) != (scope.game_id, scope.run_id):
                raise RuntimeAccessError("工具没有当前运行批次的执行范围")
            key = f"{scope.actor_kind}:{scope.actor_role_id}"
            if scope.actor_kind != "human" and not record["tool_name"].startswith("internal_"):
                count = frame.tool_counts.get(key, 0)
                if count >= self.dm.workflow_settings.max_tool_calls_per_role_turn:
                    raise DomainActionError("TOOL_BUDGET_EXCEEDED", "本角色回合工具调用次数达到 YAML 上限")
                frame.tool_counts[key] = count + 1
            name, values = record["tool_name"], record["arguments"]
            if scope.actor_kind == "human" and name.startswith("command_"):
                from ws.protocol import PAYLOAD_MODELS
                message_type = name.removeprefix("command_")
                schema = PAYLOAD_MODELS.get(message_type)
                if schema is None:
                    raise DomainActionError("TOOL_FORBIDDEN", "不支持的玩家操作")
                payload = schema.model_validate(values).model_dump()
                outcome = await self.actions.human_command({"type": message_type, **payload})
            elif scope.actor_kind == "dm" and name.startswith("internal_"):
                if values:
                    raise DomainActionError("INVALID_ARGUMENTS", "内部操作不接受模型参数")
                outcome = await self.actions.internal_command(name.removeprefix("internal_"))
            else:
                catalog = DM_TOOLS if scope.actor_kind == "dm" else ROLE_TOOLS if scope.actor_kind == "role" else {}
                definition = catalog.get(name)
                if definition is None:
                    raise DomainActionError("TOOL_FORBIDDEN", "当前角色无权执行该工具")
                if scope.actor_kind=='role' and scope.actor_role_id in frame.response_role_ids and scope.actor_role_id not in frame.responded_role_ids and name != 'speak_public':
                    raise DomainActionError('PUBLIC_RESPONSE_REQUIRED','本回合须先提交公开答复，再执行其他行动')
                args = definition[0].model_validate(values)
                if name == 'read_memory':
                    from tools.domain import ActionOutcome
                    outcome = ActionOutcome(data=self.service.memory_archive.retrieve(scope, self.dm.state.current_stage_num,
                        **args.model_dump(), chunk_chars=self.dm.workflow_settings.memory_chunk_chars))
                else:
                    outcome = await (self.actions.dm_tool(name, args) if scope.actor_kind == "dm" else self.actions.role_tool(scope, name, args))
            self.runtime.assert_scope(scope, expected_epoch=record["phase_epoch"])
            result = ToolResult(tool_call_id=call_id, status="rejected" if outcome.rejected else "succeeded", code=outcome.code,
                                data=outcome.data, gameplay_committed=True)
            state = self.dm._require_state()
            for event in outcome.events:
                if scope.actor_kind=='human' and (event.get('type')=='human_speech_echo' or (event.get('type')=='whisper_message' and event.get('sender_role_id')==scope.actor_role_id)):
                    event['request_id']=frame.request_id
            phase_changed = (before["state"]["current_stage_num"], before["state"]["scene_phase"]) != (state.current_stage_num, state.scene_phase.value)
            with self.service.store.transaction():
                # Validate again while holding the database writer lock, so another
                # process cannot replace the run between authorization and commit.
                self.runtime.assert_scope(scope, expected_epoch=record["phase_epoch"])
                self.service.record_responses(scope.game_id, self.dm, outcome.events)
                self.runtime.bump_state(scope.game_id, phase_changed=phase_changed)
                self.runtime.finish_tool(call_id, result.model_dump())
                self.runtime.append_events(scope.game_id, frame.request_id, outcome.events)
            frame.public_events.extend(outcome.events)
            return result
        except ValidationError as exc:
            result = ToolResult(tool_call_id=call_id, status="rejected", code="INVALID_ARGUMENTS",
                message="参数格式无效：" + ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors()))
        except RuntimeAccessError as exc:
            result = ToolResult(tool_call_id=call_id, status="rejected", code="STALE_SCOPE", message=str(exc))
        except DomainActionError as exc:
            result = ToolResult(tool_call_id=call_id, status="rejected", code=exc.code, message=str(exc))
        except ValueError as exc:
            result = ToolResult(tool_call_id=call_id, status="rejected", code="RULE_REJECTED", message=str(exc))
        except BaseException as exc:
            import asyncio
            cancelled = isinstance(exc, asyncio.CancelledError)
            result = ToolResult(tool_call_id=call_id, status="cancelled" if cancelled else "failed", code="TOOL_CANCELLED" if cancelled else "TOOL_EXECUTION_FAILED", message="工具执行未提交")
            self.dm.restore_runtime_snapshot(before)
            self.dm._require_state().persistence_events = pending
            self.runtime.finish_tool(call_id, result.model_dump())
            if cancelled or not isinstance(exc, Exception):
                raise
            return result
        self.dm.restore_runtime_snapshot(before)
        self.dm._require_state().persistence_events = pending
        self.runtime.finish_tool(call_id, result.model_dump())
        return result
