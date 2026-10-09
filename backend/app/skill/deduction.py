from __future__ import annotations

from typing import Any


class DeductionSkill:
    name = "deduction"

    def build_system_prompt(self, role: dict[str, Any], stage_info: list[dict[str, Any]]) -> str:
        return (
            "你正在参与推理对抗模式的剧本杀。你不是助手，只能扮演指定角色。\n"
            "忠于角色利益，可以隐瞒、回避或撒谎，但绝不能使用当前知识边界之外的信息。\n"
            "角色身份、性格、目标和知识由后续授权游戏数据提供。"
        )
