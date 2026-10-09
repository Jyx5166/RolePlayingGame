from __future__ import annotations

from typing import Any


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, type] = {}

    def register(self, skill_cls: type) -> None:
        self._skills[skill_cls.name] = skill_cls

    def create(self, name: str) -> Any:
        if name not in self._skills:
            raise KeyError(f"Skill not registered: {name}")
        return self._skills[name]()

    def has(self, name: str) -> bool:
        return name in self._skills
