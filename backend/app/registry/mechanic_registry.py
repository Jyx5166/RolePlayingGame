from __future__ import annotations

from typing import Any


class MechanicRegistry:
    def __init__(self) -> None:
        self._mechanic_classes: dict[str, type] = {}
        self._active: dict[str, Any] = {}

    def register(self, mechanic_cls: type) -> None:
        self._mechanic_classes[mechanic_cls.name] = mechanic_cls

    def activate_from_script(self, script: dict[str, Any]) -> None:
        self._active.clear()
        enabled = script.get("mechanics_enabled", [])
        config = script.get("mechanics_config", {})
        for name in enabled:
            if name not in self._mechanic_classes:
                continue
            self._active[name] = self._mechanic_classes[name](config.get(name, {}))

    def active(self) -> list[Any]:
        return list(self._active.values())

    def get(self, name: str) -> Any:
        if name not in self._active:
            raise KeyError(f"Mechanic not active: {name}")
        return self._active[name]
