from __future__ import annotations
import time
from typing import Any
from mechanics.search import SearchMechanic
from domain.state import GamePhase, ScenePhase


class RuntimeSnapshots:
    def restore_role_clues(self, clues: list[dict[str, Any]]) -> None:
        state = self._require_state()
        search = self.mechanic_registry.get("search")
        for stored in clues:
            role_id = str(stored["role_id"])
            clue = {
                "role_id": role_id,
                "clue_id": str(stored["clue_id"]),
                "stage": int(stored["stage"]),
                "target_id": str(stored["target_id"]),
                "target_name": str(stored["target_name"]),
                "truth_content": str(stored["truth_content"]),
                "disclosure_mode": str(stored.get("disclosure_mode") or "private"),
                "shared_content": str(stored.get("shared_content") or ""),
                "shared_scope": str(stored.get("shared_scope") or ""),
                "target_role_id": stored.get("target_role_id"),
            }
            state.role_clues.setdefault(role_id, {})[clue["clue_id"]] = clue
            if role_id in state.ai_role_ids:
                self.agent_pool.remember_clue(
                    role_id,
                    clue_id=clue["clue_id"],
                    stage=clue["stage"],
                    target_name=clue["target_name"],
                    truth_content=clue["truth_content"],
                    disclosure_mode=clue["disclosure_mode"],
                    shared_content=clue["shared_content"],
                )
            if isinstance(search, SearchMechanic):
                search.restore_role_clue(
                    clue["stage"],
                    role_id,
                    clue["clue_id"],
                )

    def export_runtime_snapshot(self) -> dict[str, Any]:
        state = self._require_state()
        return {
            "version": self.RUNTIME_SNAPSHOT_VERSION,
            "saved_at_epoch": time.time(),
            "script_id": state.script_id,
            "human_player_role_id": state.human_player_role_id,
            "state": {
                "ai_role_ids": list(state.ai_role_ids),
                "current_stage_num": state.current_stage_num,
                "total_stages": state.total_stages,
                "phase": state.phase.value,
                "scene_phase": state.scene_phase.value,
                "phase_started_at": state.phase_started_at,
                "investigation_deadline_at": state.investigation_deadline_at,
                "investigation_metrics": dict(state.investigation_metrics),
                "human_investigation_metrics": dict(
                    state.human_investigation_metrics
                ),
                "autonomy_turn_count": state.autonomy_turn_count,
                "autonomy_next_at": state.autonomy_next_at,
                "pending_human_question_from": state.pending_human_question_from,
                "public_history": self._copy_payload_list(state.public_history),
                "role_clues": self._copy_payload(state.role_clues),
                "role_event_counts": {
                    str(stage): self._copy_payload(role_counts)
                    for stage, role_counts in state.role_event_counts.items()
                },
                "role_scores": dict(state.role_scores),
                "stage_resolutions": {
                    str(stage): self._copy_payload(resolution)
                    for stage, resolution in state.stage_resolutions.items()
                },
                "penalties": self._copy_payload_list(state.penalties),
                "applied_penalty_keys": sorted(state.applied_penalty_keys),
                "audit_log": self._copy_payload_list(state.audit_log),
                "record_sequence": state.record_sequence,
            },
            "agents": self.agent_pool.export_runtime_state(),
            "mechanics": {
                mechanic.name: mechanic.export_runtime_state()
                for mechanic in self.mechanic_registry.active()
            },
        }

    def restore_runtime_snapshot(self, snapshot: dict[str, Any]) -> None:
        state = self._require_state()
        version = int(snapshot.get("version", 0))
        if version != self.RUNTIME_SNAPSHOT_VERSION:
            raise ValueError(
                f"不支持的游戏快照版本：{version}，"
                f"当前版本为 {self.RUNTIME_SNAPSHOT_VERSION}"
            )
        if str(snapshot.get("script_id", "")) != state.script_id:
            raise ValueError("游戏快照与当前剧本不匹配")
        if (
            str(snapshot.get("human_player_role_id", ""))
            != state.human_player_role_id
        ):
            raise ValueError("游戏快照与当前玩家角色不匹配")

        payload = snapshot.get("state")
        if not isinstance(payload, dict):
            raise ValueError("游戏快照缺少运行状态")
        stage = int(payload.get("current_stage_num", 0))
        if stage < 1 or stage > state.total_stages:
            raise ValueError("游戏快照中的幕数无效")
        if int(payload.get("total_stages", 0)) != state.total_stages:
            raise ValueError("游戏快照中的总幕数与当前剧本不匹配")
        restored_ai_roles = [
            str(role_id) for role_id in payload.get("ai_role_ids", [])
        ]
        if set(restored_ai_roles) != set(state.ai_role_ids):
            raise ValueError("游戏快照中的角色列表与当前剧本不匹配")

        state.ai_role_ids = restored_ai_roles
        state.current_stage_num = stage
        state.phase = GamePhase(str(payload.get("phase", GamePhase.PLAYING.value)))
        state.scene_phase = ScenePhase(
            str(payload.get("scene_phase", ScenePhase.BRIEFING.value))
        )
        state.phase_started_at = float(
            payload.get("phase_started_at", time.time())
        )
        deadline = payload.get("investigation_deadline_at")
        state.investigation_deadline_at = (
            float(deadline) if deadline is not None else None
        )
        state.investigation_metrics = self._restore_metric_counts(
            payload.get("investigation_metrics")
        )
        state.human_investigation_metrics = self._restore_metric_counts(
            payload.get("human_investigation_metrics")
        )
        state.autonomy_turn_count = max(
            0,
            int(payload.get("autonomy_turn_count", 0)),
        )
        autonomy_next_at = payload.get("autonomy_next_at")
        state.autonomy_next_at = (
            float(autonomy_next_at)
            if autonomy_next_at is not None
            else None
        )
        pending_role = payload.get("pending_human_question_from")
        state.pending_human_question_from = (
            str(pending_role)
            if pending_role in state.ai_role_ids
            else None
        )
        state.public_history = [
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
                **({"source_key": str(item["source_key"])} if "source_key" in item else {}),
            }
            for item in payload.get("public_history", [])
            if isinstance(item, dict)
        ]
        state.role_clues = {
            str(role_id): {
                str(clue_id): dict(clue)
                for clue_id, clue in clues.items()
                if isinstance(clue, dict)
            }
            for role_id, clues in payload.get("role_clues", {}).items()
            if isinstance(clues, dict)
        }
        state.role_event_counts = {
            int(saved_stage): {
                str(role_id): {
                    str(event_type): max(0, int(count))
                    for event_type, count in counts.items()
                }
                for role_id, counts in role_counts.items()
                if isinstance(counts, dict)
            }
            for saved_stage, role_counts in payload.get(
                "role_event_counts",
                {},
            ).items()
            if isinstance(role_counts, dict)
        }
        state.role_scores = {
            str(role_id): int(score)
            for role_id, score in payload.get("role_scores", {}).items()
        }
        state.stage_resolutions = {
            int(saved_stage): dict(resolution)
            for saved_stage, resolution in payload.get(
                "stage_resolutions",
                {},
            ).items()
            if isinstance(resolution, dict)
        }
        state.penalties = [
            dict(penalty)
            for penalty in payload.get("penalties", [])
            if isinstance(penalty, dict)
        ]
        state.applied_penalty_keys = {
            str(key) for key in payload.get("applied_penalty_keys", [])
        }
        state.audit_log = [
            dict(item)
            for item in payload.get("audit_log", [])
            if isinstance(item, dict)
        ]
        state.record_sequence = max(0, int(payload.get("record_sequence", 0)))
        state.persistence_events.clear()

        agent_states = snapshot.get("agents", {})
        if isinstance(agent_states, dict):
            self.agent_pool.restore_runtime_state(agent_states)
            if any("public_announcements" not in payload for payload in agent_states.values() if isinstance(payload, dict)):
                self._restore_legacy_public_announcements()
        mechanic_states = snapshot.get("mechanics", {})
        if isinstance(mechanic_states, dict):
            for mechanic in self.mechanic_registry.active():
                mechanic_state = mechanic_states.get(mechanic.name)
                if not isinstance(mechanic_state, dict):
                    raise ValueError(
                        f"游戏快照缺少 {mechanic.name} 机制状态"
                    )
                mechanic.restore_runtime_state(state, mechanic_state)
        for role_id in state.ai_role_ids:
            agent_payload = agent_states.get(role_id, {})
            if int(agent_payload.get("memory_version", 1)) < 2:
                agent = self.agent_pool.get(role_id)
                for known_stage in range(1, stage + 1):
                    agent.inject_info(self.permission.current_stage_blocks(role_id, known_stage), known_stage)
                whisper = next((item for item in self.mechanic_registry.active() if item.name == "whisper"), None)
                history = whisper.export_runtime_state()["history"].get(role_id, []) if whisper else []
                agent.recover_legacy_history(state.public_history, history, state.human_player_role_id)

    @staticmethod
    def _restore_metric_counts(payload: Any) -> dict[str, int]:
        source = payload if isinstance(payload, dict) else {}
        return {
            metric: max(0, int(source.get(metric, 0)))
            for metric in ("public_messages", "searches", "whispers")
        }
