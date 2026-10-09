from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.context import role_can_read_block


class PermissionMatrix:
    def __init__(self, script: dict[str, Any]) -> None:
        self.script = script
        self.total_stages = int(script["script_meta"]["total_stages"])
        self._roles = {role["role_id"]: role for role in script["roles"]}

    @property
    def role_ids(self) -> list[str]:
        return list(self._roles.keys())

    def role_exists(self, role_id: str) -> bool:
        return role_id in self._roles

    def role_name(self, role_id: str) -> str:
        return self._roles[role_id]["role_name"]

    def role_by_id(self, role_id: str) -> dict[str, Any]:
        return self._roles[role_id]

    def human_playable_roles(self) -> list[dict[str, Any]]:
        return [role for role in self._roles.values() if role.get("human_playable")]

    def visible_blocks(self, role_id: str, stage: int) -> list[dict[str, Any]]:
        if role_id not in self._roles:
            raise KeyError(f"Unknown role_id: {role_id}")
        if stage < 1 or stage > self.total_stages:
            raise ValueError(f"Invalid stage: {stage}")

        blocks: list[dict[str, Any]] = []
        for current_stage in range(1, stage + 1):
            stage_key = f"stage_{current_stage}"
            role_blocks = self._roles[role_id]["stage_knowledge"][stage_key].get("blocks", [])
            for block in role_blocks:
                if role_can_read_block(block, role_id, stage):
                    blocks.append(deepcopy(block))
        return blocks

    def current_stage_blocks(self, role_id: str, stage: int) -> list[dict[str, Any]]:
        visible = self.visible_blocks(role_id, stage)
        current_ids = {
            block["block_id"]
            for block in self._roles[role_id]["stage_knowledge"][f"stage_{stage}"].get("blocks", [])
        }
        return [
            block for block in visible
            if block["block_id"] in current_ids or block["unlock_stage"] == stage
        ]

    def public_role_sheet(self) -> list[dict[str, str]]:
        return [
            {
                "role_id": role["role_id"],
                "role_name": role["role_name"],
                "public_identity": role["public_identity"],
            }
            for role in self._roles.values()
        ]

    def visible_text(self, role_id: str, stage: int) -> str:
        return "\n".join(block["content"] for block in self.visible_blocks(role_id, stage))
