from __future__ import annotations

from typing import Any


class NarrativeSkill:
    name = "narrative"

    def build_system_prompt(self, role: dict[str, Any], stage_info: list[dict[str, Any]]) -> str:
        return (
            "你正在参与一个 AI 剧本杀 / 角色扮演故事。\n"
            "你不是助手，而是在扮演剧本中的角色。\n"
            "只能根据当前已知信息、公开发言和角色性格回应，不要预知未来剧情。\n"
            "剧情体验模式下不要恶意欺骗，但可以保留角色视角的局限。\n"
            "角色身份、性格、目标和知识由后续授权游戏数据提供。"
        )
