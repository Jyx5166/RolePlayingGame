from __future__ import annotations

from typing import Any

from llm.base import BaseLLM

from .instance import AgentInstance


class AgentPool:
    def __init__(self) -> None:
        self._pool: dict[str, AgentInstance] = {}

    def clear(self) -> None:
        self._pool.clear()

    def create(self, role_id: str, system_prompt: str, llm_client: BaseLLM) -> AgentInstance:
        agent = AgentInstance(role_id, system_prompt, llm_client)
        self._pool[role_id] = agent
        return agent

    def get(self, role_id: str) -> AgentInstance:
        if role_id not in self._pool:
            raise KeyError(f"Agent not found: {role_id}")
        return self._pool[role_id]

    def inject_info(self, role_id: str, info_blocks: list[dict[str, Any]], stage: int) -> None:
        agent = self.get(role_id)
        agent.set_current_stage(stage)
        agent.inject_info(info_blocks, stage)

    def set_objective(self, role_id: str, stage: int, objective: str) -> None:
        self.get(role_id).set_stage_objective(stage, objective)

    def set_role_roster(self, role_id: str, roster: list[dict[str, str]]) -> None:
        self.get(role_id).set_role_roster(roster)

    def observe_event(self, role_id: str, event: dict[str, str]) -> None:
        self.get(role_id).observe_event(event)

    def remember_clue(self, role_id: str, **clue: Any) -> None:
        self.get(role_id).remember_clue(**clue)

    def role_ids(self) -> list[str]:
        return list(self._pool.keys())

    def export_runtime_state(self) -> dict[str, dict[str, Any]]:
        return {
            role_id: agent.export_runtime_state()
            for role_id, agent in self._pool.items()
        }

    def restore_runtime_state(self, payload: dict[str, Any]) -> None:
        unknown_roles = set(payload) - set(self._pool)
        missing_roles = set(self._pool) - set(payload)
        if unknown_roles or missing_roles:
            details: list[str] = []
            if unknown_roles:
                details.append(
                    "未知："
                    + "、".join(
                        sorted(str(role_id) for role_id in unknown_roles)
                    )
                )
            if missing_roles:
                details.append(
                    "缺失："
                    + "、".join(
                        sorted(str(role_id) for role_id in missing_roles)
                    )
                )
            raise ValueError(
                "运行快照中的 Agent 列表不完整（" + "；".join(details) + "）"
            )
        for role_id, state in payload.items():
            if isinstance(state, dict):
                self.get(role_id).restore_runtime_state(state)
