from __future__ import annotations

from typing import Any

from .base import MechanicBase


class SearchMechanic(MechanicBase):
    name = "search"

    def __init__(self, config: dict[str, Any]) -> None:
        self.ap_per_stage = list(config.get("ap_per_stage", [1]))
        self.targets = {target["id"]: target for target in config.get("search_targets", [])}
        self._remaining_ap: dict[tuple[int, str], int] = {}
        self._found_by_role: dict[str, set[str]] = {}
        self._exclusive_found_clues: set[str] = set()

    def describe_actions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "search",
                "label": "搜证",
                "fields": [{"name": "target_id", "type": "select"}],
                "targets": [
                    {
                        "id": target["id"],
                        "name": target.get("name", target["id"]),
                        "unlock_stage": int(target.get("unlock_stage", 1)),
                    }
                    for target in self.targets.values()
                ],
            }
        ]

    async def on_stage_advance(self, state: Any, new_stage: int) -> None:
        for role_id in [state.human_player_role_id, *state.ai_role_ids]:
            self._ensure_stage_ap(new_stage, role_id)

    async def on_player_action(self, state: Any, action: dict[str, Any]) -> dict[str, Any]:
        return await self.on_role_action(state, state.human_player_role_id, action)

    async def on_role_action(
        self,
        state: Any,
        role_id: str,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        stage = int(state.current_stage_num)
        self._ensure_stage_ap(stage, role_id)
        ap_key = (stage, role_id)
        if self._remaining_ap[ap_key] <= 0:
            return {"type": "search_result", "clue": None, "remaining_ap": 0, "message": "本阶段搜证次数已用完。"}

        target_id = action.get("target_id")
        if target_id not in self.targets:
            return {"type": "search_result", "clue": None, "remaining_ap": self._remaining_ap[ap_key], "message": "未知搜证目标。"}

        target = self.targets[target_id]
        if int(target.get("unlock_stage", 1)) > stage:
            return {"type": "search_result", "clue": None, "remaining_ap": self._remaining_ap[ap_key], "message": "该目标尚未解锁。"}

        clue = self._next_clue(target, role_id)
        if clue is None:
            return {"type": "search_result", "clue": None, "remaining_ap": self._remaining_ap[ap_key], "message": "这里暂时没有新的线索。"}

        self._remaining_ap[ap_key] -= 1
        self._mark_found(role_id, clue)
        return {"type": "search_result", "clue": clue, "remaining_ap": self._remaining_ap[ap_key]}

    def available_targets(
        self,
        stage: int,
        role_id: str | None = None,
    ) -> list[dict[str, str]]:
        return [
            {"id": target["id"], "name": target.get("name", target["id"])}
            for target in self.targets.values()
            if int(target.get("unlock_stage", 1)) <= stage
            and (
                role_id is None
                or any(
                    self._clue_available(clue, role_id)
                    for clue in target.get("clues", [])
                )
            )
        ]

    def remaining_ap(self, stage: int, role_id: str) -> int:
        self._ensure_stage_ap(stage, role_id)
        return self._remaining_ap[(stage, role_id)]

    def reduce_ap(self, stage: int, role_id: str, amount: int) -> int:
        self._ensure_stage_ap(stage, role_id)
        key = (stage, role_id)
        self._remaining_ap[key] = max(0, self._remaining_ap[key] - max(0, int(amount)))
        return self._remaining_ap[key]

    def restore_role_clue(self, stage: int, role_id: str, clue_id: str) -> None:
        clue = self._clue_by_id(clue_id)
        if clue is None or clue_id in self._found_by_role.get(role_id, set()):
            return
        self._mark_found(role_id, clue)
        self._ensure_stage_ap(stage, role_id)
        key = (stage, role_id)
        self._remaining_ap[key] = max(0, self._remaining_ap[key] - 1)

    def export_runtime_state(self) -> dict[str, Any]:
        return {
            "remaining_ap": [
                {
                    "stage": stage,
                    "role_id": role_id,
                    "remaining": remaining,
                }
                for (stage, role_id), remaining in self._remaining_ap.items()
            ],
            "found_by_role": {
                role_id: sorted(clue_ids)
                for role_id, clue_ids in self._found_by_role.items()
            },
            "exclusive_found_clues": sorted(self._exclusive_found_clues),
        }

    def restore_runtime_state(self, state: Any, payload: dict[str, Any]) -> None:
        valid_roles = {state.human_player_role_id, *state.ai_role_ids}
        self._remaining_ap = {}
        for item in payload.get("remaining_ap", []):
            if not isinstance(item, dict):
                continue
            role_id = str(item.get("role_id", ""))
            stage = int(item.get("stage", 0))
            if role_id not in valid_roles or stage < 1:
                continue
            self._remaining_ap[(stage, role_id)] = max(
                0,
                int(item.get("remaining", 0)),
            )
        self._found_by_role = {
            str(role_id): {
                str(clue_id)
                for clue_id in clue_ids
                if self._clue_by_id(str(clue_id)) is not None
            }
            for role_id, clue_ids in payload.get("found_by_role", {}).items()
            if role_id in valid_roles and isinstance(clue_ids, list)
        }
        self._exclusive_found_clues = {
            str(clue_id)
            for clue_id in payload.get("exclusive_found_clues", [])
            if self._clue_by_id(str(clue_id)) is not None
        }

    def _next_clue(
        self,
        target: dict[str, Any],
        role_id: str,
    ) -> dict[str, Any] | None:
        for clue in target.get("clues", []):
            if self._clue_available(clue, role_id):
                return clue
        return None

    def _clue_available(self, clue: dict[str, Any], role_id: str) -> bool:
        clue_id = str(clue["id"])
        if clue_id in self._found_by_role.get(role_id, set()):
            return False
        if clue.get("exclusivity", "shared") == "shared":
            return True
        return clue_id not in self._exclusive_found_clues

    def _mark_found(self, role_id: str, clue: dict[str, Any]) -> None:
        clue_id = str(clue["id"])
        self._found_by_role.setdefault(role_id, set()).add(clue_id)
        if clue.get("exclusivity", "shared") != "shared":
            self._exclusive_found_clues.add(clue_id)

    def _clue_by_id(self, clue_id: str) -> dict[str, Any] | None:
        for target in self.targets.values():
            for clue in target.get("clues", []):
                if clue.get("id") == clue_id:
                    return clue
        return None

    def _ensure_stage_ap(self, stage: int, role_id: str) -> None:
        key = (stage, role_id)
        if key not in self._remaining_ap:
            idx = min(stage - 1, len(self.ap_per_stage) - 1)
            self._remaining_ap[key] = int(self.ap_per_stage[idx])
