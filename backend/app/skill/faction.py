from __future__ import annotations

from typing import Any


class FactionSkill:
    name = "faction"

    def build_system_prompt(self, role: dict[str, Any], stage_info: list[dict[str, Any]]) -> str:
        return (
            "你正在参与阵营博弈模式的剧本杀。你不是助手，只能扮演指定角色。\n"
            "判断敌友、选择性透露信息并争取角色阵营胜利，不得泄露尚未解锁的信息。\n"
            "角色身份、性格、目标和知识由后续授权游戏数据提供。"
        )
