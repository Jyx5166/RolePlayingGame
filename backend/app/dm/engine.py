from __future__ import annotations
import uuid
from typing import Any, Callable
from agent.context import AgentContextBroker
from agent.pool import AgentPool
from dm.permission import PermissionMatrix
from dm.replay import ReplayEngine
from dm.turn_manager import TurnManager
from dm.validator import SpeechValidator
from llm.factory import LLMFactory
from loader.script_loader import ScriptLoader
from mechanics.search import SearchMechanic
from mechanics.whisper import WhisperMechanic
from registry.mechanic_registry import MechanicRegistry
from registry.skill_registry import SkillRegistry
from skill.narrative import NarrativeSkill
from runtime.contracts import RuntimeScope
from runtime.store import RuntimeStore
from workflow_config import WorkflowSettings
from domain.state import GamePhase, ScenePhase, GameState
from domain.snapshots import RuntimeSnapshots
from domain.scenes import SceneRules
from domain.settlement import SettlementRules
from domain.interactions import PlayerActions
from agent.autonomy import AutonomousRoles
from agent.execution import AgentExecution
from domain.records import GameRecords


class DMEngine(RuntimeSnapshots, SceneRules, SettlementRules, PlayerActions, AutonomousRoles, AgentExecution, GameRecords):
    RUNTIME_SNAPSHOT_VERSION = 1

    def __init__(
        self,
        script_loader: ScriptLoader,
        agent_pool: AgentPool,
        llm_factory: LLMFactory,
        mechanic_registry: MechanicRegistry,
        skill_registry: SkillRegistry,
    ) -> None:
        self.script_loader = script_loader
        self.agent_pool = agent_pool
        self.llm_factory = llm_factory
        self.mechanic_registry = mechanic_registry
        self.skill_registry = skill_registry
        self.state: GameState | None = None
        self.script: dict[str, Any] | None = None
        self.permission: PermissionMatrix | None = None
        self.validator: SpeechValidator | None = None
        self.turn_mgr: TurnManager | None = None
        self.context_broker: AgentContextBroker | None = None
        self.replay_engine = ReplayEngine()
        self.reveal_truth_on_failure = False
        self.attempt_observer: Callable[[dict[str, Any]], None] | None = None
        # Attempts are observational evidence, deliberately outside rollback snapshots.
        self.attempt_records: dict[str, dict[str, Any]] = {}
        self.dm_instance_id = str(uuid.uuid4())
        self.human_instance_id = str(uuid.uuid4())
        self.runtime_scopes: dict[str, RuntimeScope] = {}
        self.runtime_store: RuntimeStore | None = None
        self.workflow_enabled = False
        self.workflow_settings = WorkflowSettings()
        self.dm_llm = None

        if not self.skill_registry.has(NarrativeSkill.name):
            self.skill_registry.register(NarrativeSkill)
        self.mechanic_registry.register(SearchMechanic)
        self.mechanic_registry.register(WhisperMechanic)

    async def init_game(self, script_id: str, human_role_id: str, skill_name: str) -> GameState:
        script = self.script_loader.load(script_id)
        return await self.init_game_from_script(script, human_role_id, skill_name)

    async def init_game_from_script(
        self,
        script: dict[str, Any],
        human_role_id: str,
        skill_name: str,
    ) -> GameState:
        self.script_loader.validate(script)
        script_id = script["script_meta"]["script_id"]
        if skill_name not in script["script_meta"]["supported_skills"]:
            raise ValueError(f"Skill {skill_name} is not supported by script {script_id}")

        permission = PermissionMatrix(script)
        if not permission.role_exists(human_role_id):
            raise ValueError(f"Role not found: {human_role_id}")
        if not permission.role_by_id(human_role_id).get("human_playable"):
            raise ValueError(f"Role is not human playable: {human_role_id}")

        self.script = script
        self.permission = permission
        self.validator = SpeechValidator(script)
        role_names = {role_id: permission.role_name(role_id) for role_id in permission.role_ids}
        self.turn_mgr = TurnManager(role_names)
        self.mechanic_registry.activate_from_script(script)
        self.agent_pool.clear()

        ai_role_ids = [role_id for role_id in permission.role_ids if role_id != human_role_id]
        self.context_broker = AgentContextBroker(permission.role_ids)
        role_roster = [
            {
                **role,
                "controller": (
                    "真人玩家"
                    if role["role_id"] == human_role_id
                    else "角色 Agent"
                ),
            }
            for role in permission.public_role_sheet()
        ]
        skill = self.skill_registry.create(skill_name)
        for role_id in ai_role_ids:
            role = permission.role_by_id(role_id)
            stage_info = permission.visible_blocks(role_id, 1)
            system_prompt = skill.build_system_prompt(role, stage_info)
            agent = self.agent_pool.create(role_id, system_prompt, self.llm_factory.create())
            agent.set_role_profile(role)
            self.agent_pool.set_role_roster(role_id, role_roster)
            self.agent_pool.inject_info(role_id, permission.current_stage_blocks(role_id, 1), 1)
            self.agent_pool.set_objective(
                role_id,
                1,
                self._script_personal_task(script, role, 1),
            )

        self.state = GameState(
            script_id=script_id,
            human_player_role_id=human_role_id,
            ai_role_ids=ai_role_ids,
            current_stage_num=1,
            total_stages=permission.total_stages,
            phase=GamePhase.PLAYING,
            scene_phase=(
                (ScenePhase.OPENING if self.has_opening() else ScenePhase.BRIEFING)
                if self.has_scene_flow(script)
                else ScenePhase.INVESTIGATION
            ),
        )
        self._record_intelligence_dispatch(1)
        for mechanic in self.mechanic_registry.active():
            await mechanic.on_stage_advance(self.state, 1)
        return self.state

    def get_human_player_info(self, stage: int | None = None) -> list[dict[str, Any]]:
        state = self._require_state()
        permission = self._require_permission()
        target_stage = stage or state.current_stage_num
        return permission.current_stage_blocks(state.human_player_role_id, target_stage)

    def get_role_clues(self, role_id: str) -> list[dict[str, Any]]:
        state = self._require_state()
        return [
            dict(clue)
            for clue in state.role_clues.get(role_id, {}).values()
        ]

    def get_human_clues(self) -> list[dict[str, Any]]:
        state = self._require_state()
        return self.get_role_clues(state.human_player_role_id)

    def get_public_roles(self) -> list[dict[str, str]]:
        return self._require_permission().public_role_sheet()

    def get_orchestration_summary(self) -> dict[str, Any]:
        state = self._require_state()
        permission = self._require_permission()
        return {
            "dm_agent": "online",
            "total_roles": len(permission.role_ids),
            "human_role_id": state.human_player_role_id,
            "ai_agent_count": len(state.ai_role_ids),
            "ai_role_ids": list(state.ai_role_ids),
            "current_stage": state.current_stage_num,
            "current_phase": state.scene_phase.value,
            "truth_loaded": self.script is not None,
        }

    def get_latest_dispatch(self) -> dict[str, Any]:
        state = self._require_state()
        for item in reversed(state.audit_log):
            if item.get("type") == "intelligence_dispatch":
                return item
        return {}

    def get_whisper_status(self) -> dict[str, Any]:
        state = self._require_state()
        try:
            mechanic = self.mechanic_registry.get("whisper")
        except KeyError:
            return {"enabled": False, "active_target_role_id": None, "remaining_sessions": 0}
        return mechanic.status(state)

    def _require_state(self) -> GameState:
        if self.state is None:
            raise RuntimeError("Game is not initialized")
        return self.state

    def _require_script(self) -> dict[str, Any]:
        if self.script is None:
            raise RuntimeError("Script is not loaded")
        return self.script

    def _require_permission(self) -> PermissionMatrix:
        if self.permission is None:
            raise RuntimeError("Permission matrix is not initialized")
        return self.permission

    def _require_validator(self) -> SpeechValidator:
        if self.validator is None:
            raise RuntimeError("Validator is not initialized")
        return self.validator

    def _require_turn_manager(self) -> TurnManager:
        if self.turn_mgr is None:
            raise RuntimeError("Turn manager is not initialized")
        return self.turn_mgr

    def _require_context_broker(self) -> AgentContextBroker:
        if self.context_broker is None:
            raise RuntimeError("Agent context broker is not initialized")
        return self.context_broker
