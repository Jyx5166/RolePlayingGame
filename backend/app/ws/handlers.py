from __future__ import annotations

from typing import Any

from dm.engine import DMEngine, ScenePhase


CLIENT_MESSAGE_TYPES = {
    "advance_phase",
    "ask_hint",
    "player_speech",
    "request_advance",
    "request_phase_end",
    "search",
    "share_clue",
    "stage_vote",
    "whisper_close",
    "whisper_invite",
    "whisper_speech",
}


async def handle_client_message(
    dm: DMEngine,
    msg: dict[str, Any],
) -> list[dict[str, Any]]:
    msg_type = msg.get("type")
    if not isinstance(msg_type, str) or msg_type not in CLIENT_MESSAGE_TYPES:
        return [
            {
                "type": "error",
                "code": "WS_COMMAND_FORBIDDEN",
                "message": "不支持的客户端命令",
            }
        ]
    if dm.investigation_seconds_remaining() == 0:
        return [
            *await handle_message(dm, {"type": "phase_timeout"}),
            {"type": "error", "code": "PHASE_EXPIRED", "message": "调查时间已到，DM 已结束本幕；该行动未执行。"},
        ]
    return await handle_message(dm, msg)


def active_mechanics(dm: DMEngine) -> list[dict[str, Any]]:
    return [
        {"name": mechanic.name, "actions": mechanic.describe_actions()}
        for mechanic in dm.mechanic_registry.active()
    ]


def search_status(dm: DMEngine) -> dict[str,Any]:
    search=dm.mechanic_registry.get('search')
    state=dm._require_state()
    if search is None:return {'remaining_ap':0,'targets':[]}
    return {'remaining_ap':search.remaining_ap(state.current_stage_num,state.human_player_role_id),
            'targets':search.available_targets(state.current_stage_num,state.human_player_role_id)}


def build_game_init(
    dm: DMEngine,
    history_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state = dm._require_state()
    stage_info = [] if dm.uses_scene_flow() else dm.get_human_player_info(state.current_stage_num)
    return {
        "type": "game_init",
        "role_info": {"role_id": state.human_player_role_id},
        "public_roles": dm.get_public_roles(),
        "stage": state.current_stage_num,
        "stage_info": stage_info,
        "total_stages": state.total_stages,
        "active_mechanics": active_mechanics(dm),
        "orchestration": dm.get_orchestration_summary(),
        "dispatch": dm.get_latest_dispatch(),
        "whisper_status": dm.get_whisper_status(),
        "clues": dm.get_human_clues(),
        'search_status':search_status(dm),
        "phase": dm.get_scene_summary(),
        "history_events": list(history_events or []),
        "sync": {
            "snapshot_version": dm.RUNTIME_SNAPSHOT_VERSION,
            "event_count": len(history_events or []),
        },
    }


def build_autonomy_activity(dm: DMEngine) -> dict[str, Any] | None:
    plan = dm.preview_autonomous_turn()
    if plan is None:
        return None
    return {
        "type": "agent_activity_start",
        "actor_role_id": plan["actor_role_id"],
        "actor_role_name": plan["actor_role_name"],
        "channel": "planning",
        "autonomy_turn": plan["turn_number"],
    }


def build_phase_messages(dm: DMEngine) -> list[dict[str, Any]]:
    summary = dm.get_scene_summary()
    phase = ScenePhase(summary["phase"])
    messages: list[dict[str, Any]] = [{"type": "phase_changed", "phase": summary}]

    if phase == ScenePhase.REPLAY:
        messages.append({"type": "replay", **dm.get_replay()})
        return messages

    if phase == ScenePhase.PRIVATE_REVEAL:
        messages.append(
            {
                "type": "private_script",
                "phase": summary,
                "assignment": dm.get_private_assignment(),
                "dispatch": dm.get_latest_dispatch(),
            }
        )
        return messages

    if phase == ScenePhase.INVESTIGATION:
        messages.append(
            {
                "type": "investigation_open",
                "phase": summary,
                "stage_info": dm.get_human_player_info(summary["stage"]),
                "active_mechanics": active_mechanics(dm),
                "whisper_status": dm.get_whisper_status(),
                "clues": dm.get_human_clues(),
                'search_status':search_status(dm),
            }
        )
        return messages

    if phase == ScenePhase.OPENING:
        narration = dm.get_opening_narration()
    elif phase == ScenePhase.BRIEFING:
        narration = dm.get_briefing_narration()
    else:
        narration = dm.get_hosting_narration()
    dm.record_dm_narration_for_notebooks(
        phase.value,
        summary["stage_title"],
        narration,
    )
    messages.append(
        {
            "type": "dm_narration_start",
            "phase": phase.value,
            "speaker": "DM Agent",
            "title": summary["stage_title"],
        }
    )
    messages.extend(
        {
            "type": "dm_narration_chunk",
            "phase": phase.value,
            "content": chunk,
        }
        for chunk in _text_chunks(narration)
    )
    if phase == ScenePhase.DM_HOSTING:
        resolution = dm.get_stage_resolution()
        if resolution is not None:
            messages.append(
                {
                    "type": "stage_resolution",
                    "resolution": resolution,
                }
            )
    messages.append(
        {
            "type": "dm_narration_end",
            "phase": phase.value,
            "can_continue": not dm.stage_resolution_pending(),
            "continue_label": summary["continue_label"],
        }
    )
    return messages


async def handle_message(dm: DMEngine, msg: dict[str, Any]) -> list[dict[str, Any]]:
    msg_type = msg["type"]

    if msg_type == "init_game":
        await dm.init_game(msg["script_id"], msg["role_id"], msg.get("skill", "narrative"))
        return [build_game_init(dm), *build_phase_messages(dm)]

    if msg_type == "advance_phase":
        return _phase_transition_messages(dm, await dm.advance_scene_phase())

    if msg_type == "request_phase_end":
        return await _investigation_end_vote_messages(dm)

    if msg_type == "phase_timeout":
        remaining = dm.investigation_seconds_remaining()
        if remaining is None or remaining > 0:
            raise ValueError("调查计时尚未结束")
        dm.end_investigation("timeout")
        return build_phase_messages(dm)

    if msg_type == "stage_vote":
        resolution = await dm.cast_stage_vote(str(msg.get("target_role_id", "")))
        return [{"type": "stage_resolution", "resolution": resolution}]

    if msg_type == "autonomy_tick":
        responses = await dm.run_autonomous_turn()
        if responses:
            responses.append(
                {
                    "type": "autonomy_status",
                    "autonomy": dm.get_autonomy_status(),
                }
            )
        return _append_condition_transition(dm, responses)

    if msg_type == "player_speech":
        result = await dm.handle_human_speech(msg["content"])
        responses = [{"type": "human_speech_echo", **result}]
        if result.get("warning"):
            responses.append({"type": "speech_warning", "message": result["warning"]})
        for reply in await dm.schedule_ai_turns(result):
            responses.append({"type": "ai_speech", **reply})
        return _append_condition_transition(dm, responses)

    if msg_type == "request_advance":
        if dm.uses_scene_flow():
            if dm._require_state().scene_phase == ScenePhase.INVESTIGATION:
                return await _investigation_end_vote_messages(dm)
            return _phase_transition_messages(dm, await dm.advance_scene_phase())
        if dm.can_advance():
            state = await dm.advance_stage()
            return [
                {
                    "type": "stage_advance",
                    "stage": state.current_stage_num,
                    "new_info": dm.get_human_player_info(state.current_stage_num),
                    "dispatch": dm.get_latest_dispatch(),
                    "whisper_status": dm.get_whisper_status(),
                }
            ]
        replay = await dm.run_replay()
        return [{"type": "replay", **replay}]

    if msg_type == "search":
        result = await dm.handle_mechanic_action(msg)
        return _append_condition_transition(dm, [result])

    if msg_type == "share_clue":
        result = dm.handle_clue_disclosure(msg)
        return _append_condition_transition(dm, [result])

    if msg_type in {"whisper_invite", "whisper_close"}:
        result = await dm.handle_whisper_action(msg)
        return _append_condition_transition(dm, [result])

    if msg_type == "whisper_speech":
        responses = await dm.handle_whisper_speech(str(msg.get("content", "")))
        return _append_condition_transition(dm, responses)

    if msg_type == "ask_hint":
        return [{"type": "hint", "content": "先确认你当前阶段已经知道的信息，再追问最相关的角色。"}]

    return [{"type": "error", "message": f"Unsupported message type: {msg_type}"}]


def _phase_transition_messages(
    dm: DMEngine,
    transition: dict[str, Any],
) -> list[dict[str, Any]]:
    replay = transition.get("replay")
    if replay is not None:
        return [{"type": "replay", **replay}]
    return build_phase_messages(dm)


async def _investigation_end_vote_messages(dm: DMEngine) -> list[dict[str, Any]]:
    vote = await dm.request_investigation_end_vote()
    responses = [{"type": "investigation_end_vote", "vote": vote}]
    if vote["approved"]:
        dm.end_investigation("majority_vote")
        responses.extend(build_phase_messages(dm))
    return responses


def _append_condition_transition(
    dm: DMEngine,
    responses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if (
        not dm.uses_scene_flow()
        or dm._require_state().scene_phase != ScenePhase.INVESTIGATION
    ):
        return responses
    summary = dm.get_scene_summary()
    responses.append(
        {
            "type": "investigation_progress",
            "condition": summary["end_condition"],
            "end_condition_text": summary["end_condition_text"],
        }
    )
    if dm.investigation_should_end():
        responses.append(
            {
                "type": "investigation_condition_met",
                "message": "调查时间已到，DM 将结束本幕调查。",
            }
        )
        dm.end_investigation("timeout")
        responses.extend(build_phase_messages(dm))
    return responses


def _text_chunks(text: str, size: int = 16) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return [""]
    return [normalized[index : index + size] for index in range(0, len(normalized), size)]
