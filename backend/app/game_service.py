from __future__ import annotations

from collections.abc import Callable
import time
import uuid
from typing import Any

from dm.engine import DMEngine
from loader.script_loader import ScriptLoader
from storage import AppStore
from runtime.contracts import RuntimeScope
from runtime.store import RuntimeStore
from memory.archive import MemoryArchive
from agent.context import role_can_read_block
from runtime.leases import GameLeases
from workflow_config import WorkflowSettings, load_workflow_settings


ALLOWED_CATEGORIES = {"mystery", "adventure", "fantasy", "history", "custom"}
ALLOWED_MODES = {"narrative", "deduction", "faction"}


class GameService:
    def __init__(self, store: AppStore, dm_factory: Callable[[], DMEngine]) -> None:
        self.store = store
        self.dm_factory = dm_factory
        self.sessions: dict[int, DMEngine] = {}
        self.runtime_store = RuntimeStore(store)
        self.memory_archive = MemoryArchive(store)
        self.leases = GameLeases(store)
        self.workflow_defaults = load_workflow_settings()

    def inspect_script(self, script: dict[str, Any], mode: str) -> dict[str, Any]:
        if mode not in ALLOWED_MODES:
            raise ValueError("不支持的游戏模式")
        ScriptLoader(".").validate(script)
        meta = script["script_meta"]
        supported = meta["supported_skills"]
        if mode not in supported:
            raise ValueError(f"该剧本不支持 {mode} 模式")
        playable = [self._role_preview(role) for role in script["roles"] if role.get("human_playable")]
        if not playable:
            raise ValueError("剧本至少需要一个可由玩家扮演的角色")
        return {
            "script_id": meta["script_id"],
            "title": meta["title"],
            "total_stages": int(meta["total_stages"]),
            "role_count": len(script["roles"]),
            "ai_agent_count": len(script["roles"]) - 1,
            "supported_modes": list(supported),
            "playable_roles": playable,
            "story_background": script.get("story_background", ""),
        }

    async def create_game(
        self,
        user_id: int,
        script: dict[str, Any],
        category: str,
        mode: str,
        player_role_id: str,
    ) -> dict[str, Any]:
        if category not in ALLOWED_CATEGORIES:
            raise ValueError("不支持的剧本类型")
        preview = self.inspect_script(script, mode)
        playable_ids = {role["role_id"] for role in preview["playable_roles"]}
        if player_role_id not in playable_ids:
            raise ValueError("所选角色不可由玩家扮演")

        dm = self.dm_factory()
        await dm.init_game_from_script(script, player_role_id, mode)
        with self.store.transaction():
            game = self.store.create_game(user_id, script, category, mode, player_role_id)
            self.store.add_event(game["id"], "game_created", dm.get_orchestration_summary())
            self.store.add_event(game["id"], "intelligence_dispatch", dm.get_latest_dispatch())
            self.persist_engine_events(game["id"], dm)
        self.sessions[game["id"]] = dm
        self._bind_attempt_recorder(game["id"], dm)
        game = self.store.get_game(user_id, game["id"])
        return {**self._public_game(game), "orchestration": dm.get_orchestration_summary()}

    async def get_engine(self, user_id: int, game_id: int) -> tuple[dict[str, Any], DMEngine]:
        game = self.store.get_game(user_id, game_id, include_script=True)
        if game["status"] in {'preparing','abandoned'}:
            raise ValueError("请先选择角色并确认进入游戏")
        dm = self.sessions.get(game_id)
        if dm is None:
            snapshot = self.store.get_runtime_snapshot(user_id, game_id)
            dm = self.dm_factory()
            dm.reveal_truth_on_failure = game.get("lifecycle_version", 1) >= 2
            await dm.init_game_from_script(game["script"], game["player_role_id"], game["mode"])
            target_stage = (
                int(snapshot["state"]["current_stage_num"])
                if snapshot is not None
                else int(game["current_stage"])
            )
            for _ in range(1, target_stage):
                await dm.advance_stage()
            if snapshot is not None:
                dm.restore_runtime_snapshot(snapshot)
            else:
                dm.restore_scene_phase(game.get("current_phase"))
                dm.restore_role_activity_counts(
                    self.store.list_role_activities(user_id, game_id)
                )
                dm.restore_stage_resolutions(
                    self.store.list_events(user_id, game_id)
                )
                dm.restore_role_clues(
                    self.store.list_role_clues(user_id, game_id)
                )
            self._recover_legacy_memory(user_id, game_id, dm, snapshot)
            if snapshot is None:
                self.persist_engine_events(game_id, dm)
            self.sessions[game_id] = dm
        if game.get("lifecycle_version", 1) >= 2 and game.get("paused_at") is not None:
            state = dm._require_state()
            elapsed = max(0.0, time.time() - game["paused_at"])
            state.phase_started_at += elapsed
            for field in ("investigation_deadline_at", "autonomy_next_at"):
                value = getattr(state, field)
                if value is not None:
                    setattr(state, field, value + elapsed)
            with self.store.transaction():
                self.persist_engine_events(game_id, dm)
                self.store.set_game_lifecycle(game_id, paused_at=None, run_id=str(uuid.uuid4()))
                self.store.add_event(game_id, "game_resumed", {})
        self._bind_attempt_recorder(game_id, dm)
        return game, dm

    async def activate_game(self, user_id: int, game_id: int, player_role_id: str) -> dict[str, Any]:
        game = self.store.get_game(user_id, game_id, include_script=True)
        if game["status"] != "preparing":
            if game["player_role_id"] != player_role_id:
                raise ValueError("本场游戏已选定角色，不能重新选角")
            return self._public_game(game)
        preview = self.inspect_script(game["script"], game["mode"])
        if player_role_id not in {role["role_id"] for role in preview["playable_roles"]}:
            raise ValueError("所选角色不可由玩家扮演")
        dm = self.dm_factory()
        await dm.init_game_from_script(game["script"], player_role_id, game["mode"])
        dm.reveal_truth_on_failure = True
        with self.store.transaction():
            self.store.activate_preparation(user_id, game_id, player_role_id, str(uuid.uuid4()))
            self.store.add_event(game_id, "game_created", dm.get_orchestration_summary())
            self.persist_engine_events(game_id, dm)
        self.sessions[game_id] = dm
        self._bind_attempt_recorder(game_id, dm)
        return self.store.get_game(user_id, game_id)

    def pause_game(self, user_id: int, game_id: int) -> dict[str, Any]:
        game = self.store.get_game(user_id, game_id)
        if game.get("lifecycle_version", 1) < 2 or game["status"] in {"preparing", "paused", "completed"}:
            if game["status"] == "completed" and game.get("run_id"):
                self.runtime_store.close_run(game["run_id"], "completed")
            return game
        dm = self.sessions.get(game_id)
        if dm is not None and dm.runtime_scopes and dm.runtime_scopes['dm'].run_id!=game.get('run_id'):
            dm = None
        with self.store.transaction():
            if dm is not None:
                self.persist_engine_events(game_id, dm)
            self.store.set_game_lifecycle(game_id, paused_at=time.time(), status="paused")
            self.store.add_event(game_id, "game_paused", {})
            if game.get("run_id"):
                self.runtime_store.close_run(game["run_id"], "paused")
        self.sessions.pop(game_id, None)
        return self.store.get_game(user_id, game_id)

    def _bind_attempt_recorder(self, game_id: int, dm: DMEngine) -> None:
        dm.attempt_observer = lambda attempt: self.store.record_agent_attempt(game_id, attempt)
        # Binding happens after ownership was checked and after this game's snapshot was loaded.
        with self.store._connect() as connection:
            game = dict(connection.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone())
        if not game.get("run_id"):
            game["run_id"] = str(uuid.uuid4())
            self.store.set_game_lifecycle(game_id, paused_at=game.get("paused_at"), run_id=game["run_id"])
        if dm.runtime_scopes and next(iter(dm.runtime_scopes.values())).run_id == game["run_id"]:
            return
        state = dm._require_state()
        roles = [state.human_player_role_id, *state.ai_role_ids]
        context_ids = self.runtime_store.context_ids(game_id, roles)
        instances = {"dm": dm.dm_instance_id, f"role:{state.human_player_role_id}": dm.human_instance_id,
                     **{f"role:{role_id}": dm.agent_pool.get(role_id).instance_id for role_id in state.ai_role_ids}}
        with self.store._connect() as connection:
            prior = connection.execute("SELECT instances_json FROM game_runs WHERE run_id=?", (game["run_id"],)).fetchone()
        if prior is not None:
            import json
            if json.loads(prior["instances_json"]) != instances:
                game["run_id"] = str(uuid.uuid4())
                self.store.set_game_lifecycle(game_id, paused_at=game.get("paused_at"), run_id=game["run_id"])
        self.runtime_store.register_run(game_id, game["run_id"], instances)
        self.leases.bind(game_id, game['run_id'])
        dm.runtime_scopes = {key: RuntimeScope(game_id=game_id, run_id=game["run_id"], context_id=context_ids[key],
            agent_instance_id=instance_id, actor_kind="dm" if key == "dm" else "human" if key == f"role:{state.human_player_role_id}" else "role",
            actor_role_id="dm" if key == "dm" else key.removeprefix("role:")) for key, instance_id in instances.items()}
        dm.runtime_store = self.runtime_store
        dm.workflow_enabled = game.get("lifecycle_version", 1) >= 3
        dm.workflow_settings = WorkflowSettings.model_validate_json(game["workflow_config_json"]) if game.get("workflow_config_json") else self.workflow_defaults
        dm.memory_archive = self.memory_archive
        dm._require_context_broker().runtime_scopes = {role: dm.runtime_scopes[f"role:{role}"] for role in state.ai_role_ids}
        for role in state.ai_role_ids:
            dm.agent_pool.get(role).runtime_scope = dm.runtime_scopes[f"role:{role}"]
            dm.agent_pool.get(role).archive = self.memory_archive if dm.workflow_enabled and dm.workflow_settings.context_strategy == 'archive_retrieval' else None
            dm.agent_pool.get(role).workflow_settings = dm.workflow_settings
            if dm.workflow_enabled and dm.workflow_settings.reasoning_effort and hasattr(dm.agent_pool.get(role)._llm,'reasoning_effort'):
                dm.agent_pool.get(role)._llm.reasoning_effort=dm.workflow_settings.reasoning_effort
        self.memory_archive.sync_game(dm)

    def _recover_legacy_memory(self, user_id: int, game_id: int, dm: DMEngine,
                               snapshot: dict[str, Any] | None) -> None:
        legacy_roles = [role_id for role_id in dm.state.ai_role_ids
                        if snapshot is None or int(snapshot.get("agents", {}).get(role_id, {}).get("memory_version", 1)) < 2]
        if not legacy_roles:
            return
        activities = self.store.list_role_activities(user_id, game_id)
        private_types = {"private_speech", "private_response", "autonomous_private_speech", "autonomous_private_response"}
        for role_id in legacy_roles:
            agent = dm.agent_pool.get(role_id)
            for activity in activities:
                stage = int(activity["stage"])
                if not 1 <= stage <= dm.state.current_stage_num:
                    continue
                actor, target = activity["actor_role_id"], activity.get("target_role_id")
                if not dm.permission.role_exists(actor):
                    continue
                if activity["channel"] == "private" and activity["event_type"] in private_types:
                    if role_id not in {actor, target}:
                        continue
                    counterpart = target if actor == role_id else actor
                    if not dm.permission.role_exists(counterpart):
                        continue
                    content = activity.get("details", {}).get("content")
                    if not isinstance(content, str):
                        continue
                    agent.remember_private_exchange(stage, dm.permission.role_name(counterpart),
                        "sent" if actor == role_id else "received", content,
                        source_key=f"activity:{activity['id']}", counterpart_role_id=counterpart, phase=activity["phase"])
                    agent._private_memory[-1]["created_at"] = activity["created_at"]
                elif activity["channel"] == "public":
                    agent.observe_event({"source_key": f"activity:{activity['id']}", "stage": stage,
                        "phase": activity["phase"], "created_at": activity["created_at"], "channel": "public",
                        "actor_role_id": actor, "actor_role_name": dm.permission.role_name(actor),
                        "event_type": activity["event_type"], "content": activity["summary"]})
            for note in self.store.list_notebook_entries(user_id, game_id, role_id):
                if note["section"] != "reasoning" or not 1 <= int(note["stage"]) <= dm.state.current_stage_num:
                    continue
                agent.remember_reasoning_note(int(note["stage"]), note["content"], source_key=note["source_key"], phase="legacy_unknown")
                agent._reasoning_notes[-1]["created_at"] = note["created_at"]

    def record_responses(self, game_id: int, dm: DMEngine, responses: list[dict[str, Any]]) -> None:
        with self.store.transaction():
            self._record_responses(game_id, dm, responses)

    def _record_responses(self, game_id: int, dm: DMEngine, responses: list[dict[str, Any]]) -> None:
        for response in responses:
            response_type = response.get("type", "unknown")
            if response_type not in {
                "dm_narration_start",
                "dm_narration_chunk",
                "dm_narration_end",
                "investigation_open",
                "private_script",
            }:
                self.store.add_event(game_id, response_type, response)
            if response_type == "stage_advance":
                self.store.add_event(game_id, "intelligence_dispatch", dm.get_latest_dispatch())
                self.store.update_game(game_id, int(response["stage"]), "playing")
            elif response_type == "phase_changed":
                phase = response["phase"]
                self.store.update_game(
                    game_id,
                    int(phase["stage"]),
                    "playing",
                    str(phase["phase"]),
                )
                if phase["phase"] == "briefing" and int(phase["stage"]) > 1:
                    self.store.add_event(
                        game_id,
                        "intelligence_dispatch",
                        dm.get_latest_dispatch(),
                    )
            elif response_type == "replay":
                stage = dm.state.current_stage_num if dm.state else 1
                self.store.update_game(game_id, stage, "completed", "replay")
        self.persist_engine_events(game_id, dm)

    def persist_engine_events(self, game_id: int, dm: DMEngine) -> None:
        pending = list(dm._require_state().persistence_events)
        try:
            with self.store.transaction():
                self._persist_engine_events(game_id, dm)
        except BaseException:
            dm._require_state().persistence_events = pending
            raise

    def _persist_engine_events(self, game_id: int, dm: DMEngine) -> None:
        for event in dm.drain_persistence_events():
            if event["kind"] == "notebook":
                self.store.add_notebook_entry(
                    game_id=game_id,
                    role_id=str(event["role_id"]),
                    section=str(event["section"]),
                    source_type=str(event["source_type"]),
                    source_key=str(event["source_key"]),
                    stage=int(event["stage"]),
                    title=str(event["title"]),
                    content=str(event["content"]),
                )
            elif event["kind"] == "activity":
                self.store.add_role_activity(
                    game_id=game_id,
                    actor_role_id=str(event["actor_role_id"]),
                    target_role_id=(
                        str(event["target_role_id"])
                        if event.get("target_role_id") is not None
                        else None
                    ),
                    event_type=str(event["event_type"]),
                    stage=int(event["stage"]),
                    phase=str(event["phase"]),
                    channel=str(event["channel"]),
                    summary=str(event["summary"]),
                    details=dict(event.get("details", {})),
                )
            elif event["kind"] == "clue":
                self.store.upsert_role_clue(
                    game_id=game_id,
                    role_id=str(event["role_id"]),
                    clue_id=str(event["clue_id"]),
                    stage=int(event["stage"]),
                    target_id=str(event["target_id"]),
                    target_name=str(event["target_name"]),
                    truth_content=str(event["truth_content"]),
                    disclosure_mode=str(event.get("disclosure_mode") or "private"),
                    shared_content=str(event.get("shared_content") or ""),
                    shared_scope=str(event.get("shared_scope") or ""),
                    target_role_id=(
                        str(event["target_role_id"])
                        if event.get("target_role_id")
                        else None
                    ),
                )
            elif event["kind"] == "agent_context":
                self.store.add_agent_context_audit(
                    game_id=game_id,
                    call_id=str(event["call_id"]),
                    role_id=str(event["role_id"]),
                    stage=int(event["stage"]),
                    phase=str(event["phase"]),
                    channel=str(event["channel"]),
                    purpose=str(event["purpose"]),
                    status=str(event["status"]),
                    error=str(event.get("error") or ""),
                    context=dict(event["context"]),
                )
        self.store.save_runtime_snapshot(
            game_id,
            dm.export_runtime_snapshot(),
        )
        state = dm._require_state()
        self.store.update_game(
            game_id,
            state.current_stage_num,
            "completed" if state.phase.value == "replay" else "playing",
            state.scene_phase.value,
        )
        if getattr(dm, 'memory_archive', None) is not None:
            self.memory_archive.sync_game(dm)

    def delete_game(self, user_id: int, game_id: int) -> None:
        self.store.delete_game(user_id, game_id)
        self.sessions.pop(game_id, None)
        checkpoint=self.store.database_path.with_name(self.store.database_path.stem+'.workflow.db')
        if checkpoint.exists():
            import sqlite3
            with sqlite3.connect(checkpoint) as connection:
                for table in ('checkpoints','writes'):
                    if connection.execute('SELECT name FROM sqlite_master WHERE name=?',(table,)).fetchone():
                        connection.execute(f'DELETE FROM {table} WHERE thread_id LIKE ?',(f'game:{game_id}:%',))

    def get_player_notebook(self, user_id: int, game_id: int) -> dict[str, Any]:
        game = self.store.get_game(user_id, game_id, include_script=True)
        if game["status"] == "preparing":
            raise ValueError("选定角色后才能读取游戏手记")
        self._ensure_baseline_notebook_records(user_id, game)
        role_id = str(game["player_role_id"])
        entries = self.store.list_notebook_entries(user_id, game_id, role_id)
        entries = self._authorized_notebook_entries(game, entries)
        entries = self._without_legacy_dm_duplicates(entries)
        manual = self.store.list_manual_notes(user_id, game_id).get(
            role_id,
            {"content": "", "updated_at": ""},
        )
        return {
            "game_id": game_id,
            "role_id": role_id,
            "clues": self.store.list_role_clues(
                user_id,
                game_id,
                role_id,
            ),
            "automatic": [
                entry for entry in entries if entry["section"] == "automatic"
            ],
            "reasoning_entries": [
                entry for entry in entries if entry["section"] == "reasoning"
            ],
            "manual_notes": manual["content"],
            "manual_updated_at": manual["updated_at"],
            "manual_history": [item for item in self.store.list_manual_note_revisions(user_id, game_id)
                               if item["role_id"] == role_id],
        }

    def save_player_manual_notes(
        self,
        user_id: int,
        game_id: int,
        content: str,
    ) -> dict[str, Any]:
        game = self.store.get_game(user_id, game_id)
        if game["status"] == "preparing":
            raise ValueError("选定角色后才能保存游戏手记")
        return self.store.save_manual_notes(
            user_id,
            game_id,
            str(game["player_role_id"]),
            content,
        )

    def get_role_records(self, user_id: int, game_id: int) -> dict[str, Any]:
        game = self.store.get_game(user_id, game_id, include_script=True)
        if game["status"] != "completed":
            raise ValueError("案件结束后才能查看全部角色记录")

        self._ensure_baseline_notebook_records(user_id, game)
        notebook_entries = self.store.list_notebook_entries(user_id, game_id)
        notebook_entries = self._authorized_notebook_entries(game, notebook_entries)
        notebook_entries = self._without_legacy_dm_duplicates(notebook_entries)
        manual_revisions = self.store.list_manual_note_revisions(user_id, game_id)
        activities = self.store.list_role_activities(user_id, game_id)
        context_audits = self.store.list_agent_context_audits(user_id, game_id)
        committed = {audit["call_id"]: audit for audit in context_audits}
        for attempt in self.store.list_agent_attempts(user_id, game_id):
            attempt["gameplay_committed"] = attempt["call_id"] in committed
            committed[attempt["call_id"]] = attempt
        context_audits = list(committed.values())
        clues = self.store.list_role_clues(user_id, game_id)
        resolutions = self._resolution_history(
            self.store.list_events(user_id, game_id)
        )
        snapshot = self.store.get_runtime_snapshot(user_id, game_id)
        if snapshot is not None:
            saved = snapshot.get("state", {}).get("stage_resolutions", {})
            if saved:
                resolutions = [saved[stage] for stage in sorted(saved, key=int)]
        if not activities:
            activities = self._recover_legacy_activities(user_id, game)
        roles: list[dict[str, Any]] = []
        for role in game["script"]["roles"]:
            role_id = str(role["role_id"])
            entries = [
                entry
                for entry in notebook_entries
                if entry["role_id"] == role_id
            ]
            reasoning_entries = [
                entry
                for entry in entries
                if entry["section"] == "reasoning"
            ]
            for manual in manual_revisions:
                if manual["role_id"] != role_id:
                    continue
                reasoning_entries.append(
                    {
                        "role_id": role_id,
                        "section": "reasoning",
                        "source_type": "manual",
                        "source_key": f"manual:{role_id}:{manual['revision']}",
                        "stage": manual["stage"], "phase": manual["phase"],
                        "title": f"玩家推理手记 · 第 {manual['revision']} 版",
                        "content": manual["content"],
                        "created_at": manual["created_at"],
                    }
                )
            roles.append(
                {
                    "role_id": role_id,
                    "role_name": role["role_name"],
                    "public_identity": role["public_identity"],
                    "controller": (
                        "human"
                        if role_id == game["player_role_id"]
                        else "agent"
                    ),
                    "automatic_notebook": [
                        entry
                        for entry in entries
                        if entry["section"] == "automatic"
                    ],
                    "reasoning_notebook": reasoning_entries,
                    "clues": [
                        clue
                        for clue in clues
                        if clue["role_id"] == role_id
                    ],
                    "operations": [
                        activity
                        for activity in activities
                        if activity["actor_role_id"] == role_id
                    ],
                    "agent_context_audits": [
                        audit
                        for audit in context_audits
                        if audit["role_id"] == role_id
                    ],
                    "stage_results": [
                        {
                            "stage": resolution["stage"],
                            "title": resolution["title"],
                            "metric": resolution["metric"],
                            "result": next(
                                (
                                    result
                                    for result in resolution.get("role_results", [])
                                    if result["role_id"] == role_id
                                ),
                                None,
                            ),
                            "vote": resolution.get("vote"),
                        }
                        for resolution in resolutions
                    ],
                }
            )
        return {
            "game_id": game_id,
            "title": game["title"],
            "status": game["status"],
            "stage_resolutions": resolutions,
            "final_decision": (
                resolutions[-1].get("vote")
                if resolutions
                and isinstance(resolutions[-1].get("vote"), dict)
                and resolutions[-1]["vote"].get("kind") == "final"
                else None
            ),
            "roles": roles,
        }

    @staticmethod
    def _resolution_history(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_stage: dict[int, dict[str, Any]] = {}
        for event in events:
            if event.get("type") != "stage_resolution":
                continue
            payload = event.get("payload", {})
            resolution = payload.get("resolution", payload)
            if not isinstance(resolution, dict) or "stage" not in resolution:
                continue
            by_stage[int(resolution["stage"])] = dict(resolution)
        return [by_stage[stage] for stage in sorted(by_stage)]

    @staticmethod
    def _authorized_notebook_entries(
        game: dict[str, Any], entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Recheck persisted script notes, including records written by older builds."""
        current_stage = int(game["current_stage"])
        if game["script"].get("opening") and current_stage == 1:
            phase = game.get("current_phase")
            if phase in {"opening", "private_reveal"}:
                allowed = {"opening"} if phase == "opening" else {"opening", "role_script", "personal_task"}
                entries = [entry for entry in entries if entry.get("source_type") in allowed]
        visible = {
            (str(role["role_id"]), str(block.get("block_id", index))): block
            for role in game["script"]["roles"]
            for stage in range(1, current_stage + 1)
            for index, block in enumerate(
                role.get("stage_knowledge", {}).get(f"stage_{stage}", {}).get("blocks", []), 1
            )
            if role_can_read_block(block, str(role["role_id"]), current_stage)
        }
        authorized = []
        for entry in entries:
            source_key = str(entry.get("source_key", ""))
            if source_key.startswith("role-script:"):
                parts = source_key.split(":", 2)
                if len(parts) != 3 or not parts[1].isdigit() or not 1 <= int(parts[1]) <= current_stage:
                    continue
                block = visible.get((str(entry["role_id"]), parts[2]))
                if block is None or str(entry.get("content", "")).strip() != str(block["content"]).strip():
                    continue
            elif entry.get("source_type") == "role_script":
                # Unidentifiable historical script entries cannot establish permission.
                continue
            authorized.append(entry)
        return authorized

    def _ensure_baseline_notebook_records(
        self,
        user_id: int,
        game: dict[str, Any],
    ) -> None:
        script = game["script"]
        game_id = int(game["id"])
        current_stage = int(game["current_stage"])
        roles = script["roles"]
        stage_flow = script.get("stage_flow", {})
        saved = self.store.get_runtime_snapshot(user_id, game_id)
        penalties = saved.get("state", {}).get("penalties", []) if saved else []
        opening = script.get("opening")
        phase = str(game.get("current_phase") or "")
        initial_private = bool(opening) and current_stage == 1 and phase == "private_reveal"
        if opening:
            for role in roles:
                self.store.add_notebook_entry(game_id=game_id, role_id=str(role["role_id"]), section="automatic",
                    source_type="opening", source_key="dm-opening:1", stage=1,
                    title=opening["title"], content=opening["content"])
            if current_stage == 1 and phase == "opening":
                return

        for stage in range(1, current_stage + 1):
            config = stage_flow.get(f"stage_{stage}", {})
            stage_title = str(config.get("title", f"第 {stage} 幕"))
            shared_entries: list[tuple[str, str, str, str]] = []
            if stage == 1 and not opening:
                shared_entries.append(
                    (
                        "story_background",
                        "dm-background:1",
                        "案件背景",
                        str(script.get("story_background", "")),
                    )
                )
            if not initial_private:
                shared_entries.append(
                    (
                        "public_briefing",
                        f"dm-public-briefing:{stage}",
                        f"{stage_title} · 公开通报",
                        str(config.get("public_briefing", "")),
                    )
                )
            public_tasks = [
                str(task).strip()
                for task in ([] if initial_private else config.get("public_tasks", []))
                if str(task).strip()
            ]
            if public_tasks:
                shared_entries.append(
                    (
                        "public_tasks",
                        f"dm-public-tasks:{stage}",
                        f"{stage_title} · 公开任务",
                        "\n".join(
                            f"{index}. {task}"
                            for index, task in enumerate(public_tasks, start=1)
                        ),
                    )
                )
            phase = str(game.get("current_phase") or "")
            hosting_is_known = (
                stage < current_stage
                or game["status"] == "completed"
                or (
                    stage == current_stage
                    and phase in {"dm_hosting", "replay"}
                )
            )
            if hosting_is_known:
                shared_entries.append(
                    (
                        "dm_hosting",
                        f"dm-hosting:{stage}",
                        f"{stage_title} · DM 主持",
                        str(config.get("dm_hosting", "")),
                    )
                )

            for role in roles:
                role_id = str(role["role_id"])
                for source_type, source_key, title, content in shared_entries:
                    self.store.add_notebook_entry(
                        game_id=game_id,
                        role_id=role_id,
                        section="automatic",
                        source_type=source_type,
                        source_key=source_key,
                        stage=stage,
                        title=title,
                        content=content,
                    )

                blocks = (
                    role.get("stage_knowledge", {})
                    .get(f"stage_{stage}", {})
                    .get("blocks", [])
                )
                for index, block in enumerate(blocks, start=1):
                    if not role_can_read_block(block, role_id, current_stage):
                        continue
                    is_public = block.get("visibility") == "public"
                    if initial_private and is_public:
                        continue
                    self.store.add_notebook_entry(
                        game_id=game_id,
                        role_id=role_id,
                        section="automatic",
                        source_type=(
                            "public_information"
                            if is_public
                            else "role_script"
                        ),
                        source_key=(
                            f"role-script:{stage}:"
                            f"{block.get('block_id', index)}"
                        ),
                        stage=stage,
                        title=(
                            f"第 {stage} 幕 · DM 公开信息"
                            if is_public
                            else f"第 {stage} 幕 · 角色剧本"
                        ),
                        content=str(block.get("content", "")),
                    )

                personal_task = DMEngine._script_personal_task(script, role, stage)
                extras = [str(penalty["extra_task"]) for penalty in penalties
                          if penalty.get("target_role_id") == role_id and penalty.get("target_stage") == stage and penalty.get("extra_task")]
                if extras:
                    personal_task += "\n附加惩罚任务：" + "；".join(extras)
                self.store.add_notebook_entry(
                    game_id=game_id,
                    role_id=role_id,
                    section="automatic",
                    source_type="personal_task",
                    source_key=f"personal-task:{stage}:{role_id}",
                    stage=stage,
                    title=f"第 {stage} 幕 · 个人任务",
                    content=str(personal_task),
                )

        existing_clues = {
            (str(clue["role_id"]), str(clue["clue_id"]))
            for clue in self.store.list_role_clues(user_id, game_id)
        }
        for index, event in enumerate(
            self.store.list_events(user_id, game_id),
            start=1,
        ):
            if event["type"] != "search_result":
                continue
            payload = event["payload"]
            clue = payload.get("clue")
            if not clue:
                continue
            role_id = str(payload.get("actor_role_id") or game["player_role_id"])
            target_name = str(payload.get("target_name") or "现场")
            self.store.add_notebook_entry(
                game_id=game_id,
                role_id=role_id,
                section="automatic",
                source_type="search",
                source_key=f"search:{clue.get('id', index)}",
                stage=int(payload.get("stage") or 1),
                title=f"搜证 · {target_name}",
                content=str(clue.get("content", "")),
            )
            clue_id = str(clue.get("id", index))
            clue_key = (role_id, clue_id)
            if clue_key not in existing_clues:
                self.store.upsert_role_clue(
                    game_id=game_id,
                    role_id=role_id,
                    clue_id=clue_id,
                    stage=int(payload.get("stage") or 1),
                    target_id=str(payload.get("target_id") or "legacy"),
                    target_name=target_name,
                    truth_content=str(clue.get("content", "")),
                    disclosure_mode="private",
                    shared_content="",
                    shared_scope="",
                    target_role_id=None,
                )
                existing_clues.add(clue_key)

    @staticmethod
    def _without_legacy_dm_duplicates(
        entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not any(
            entry["source_type"]
            in {
                "story_background",
                "public_briefing",
                "public_tasks",
                "dm_hosting",
            }
            for entry in entries
        ):
            return entries
        return [
            entry
            for entry in entries
            if entry["source_type"] != "dm_narration"
        ]

    def _recover_legacy_activities(
        self,
        user_id: int,
        game: dict[str, Any],
    ) -> list[dict[str, Any]]:
        activities: list[dict[str, Any]] = []
        human_role_id = str(game["player_role_id"])
        role_names = {
            str(role["role_id"]): str(role["role_name"])
            for role in game["script"]["roles"]
        }
        for event in self.store.list_events(user_id, int(game["id"])):
            payload = event["payload"]
            event_type = event["type"]
            actor_role_id: str | None = None
            target_role_id: str | None = None
            recovered_type = event_type
            channel = str(payload.get("channel") or "public")
            content = str(payload.get("content") or "")

            if event_type == "human_speech_echo":
                actor_role_id = str(payload.get("role_id") or human_role_id)
                recovered_type = "public_speech"
            elif event_type == "ai_speech":
                actor_role_id = str(payload.get("role_id") or "")
                target_role_id = str(payload.get("target_role_id") or human_role_id)
                recovered_type = str(payload.get("event_type") or "public_response")
            elif event_type == "ai_proactive_speech":
                actor_role_id = str(payload.get("role_id") or "")
                target_role_id = (
                    str(payload["target_role_id"])
                    if payload.get("target_role_id")
                    else None
                )
                recovered_type = "autonomous_public_speech"
            elif event_type == "search_result":
                actor_role_id = str(payload.get("actor_role_id") or human_role_id)
                recovered_type = "search"
                clue = payload.get("clue")
                content = (
                    str(clue.get("content", ""))
                    if isinstance(clue, dict)
                    else str(payload.get("message") or "")
                )
                channel = "action"
            elif event_type == "whisper_message":
                actor_role_id = str(payload.get("sender_role_id") or "")
                target_role_id = str(
                    payload.get("conversation_role_id") or human_role_id
                )
                recovered_type = (
                    "private_speech"
                    if payload.get("sender_type") == "player"
                    else "private_response"
                )
                channel = "private"
            else:
                continue

            if not actor_role_id:
                continue
            actor_name = role_names.get(actor_role_id, actor_role_id)
            target_name = (
                role_names.get(target_role_id, target_role_id)
                if target_role_id
                else ""
            )
            summary = (
                f"{actor_name} → {target_name}：{content}"
                if target_name
                else f"{actor_name}：{content}"
            )
            activities.append(
                {
                    "actor_role_id": actor_role_id,
                    "target_role_id": target_role_id,
                    "event_type": recovered_type,
                    "stage": int(payload.get("stage") or 1),
                    "phase": str(payload.get("phase") or "investigation"),
                    "channel": channel,
                    "summary": summary,
                    "details": {"recovered_from_history": True, **payload},
                    "created_at": event["created_at"],
                }
            )
        return activities

    @staticmethod
    def _role_preview(role: dict[str, Any]) -> dict[str, Any]:
        return {
            "role_id": role["role_id"],
            "role_name": role["role_name"],
            "public_identity": role["public_identity"],
        }

    @staticmethod
    def _public_game(game: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in game.items() if key != "script"}
