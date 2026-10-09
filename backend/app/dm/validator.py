from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    message: str | None = None
    category: Literal["ok", "hard_constraint"] = "ok"


class SpeechValidator:
    def __init__(self, script: dict[str, Any]) -> None:
        self._hard_constraints = script.get("hard_constraints", [])

    def validate_human_speech(self, role_id: str, stage: int, content: str) -> ValidationResult:
        result = self._check_hard_constraints(role_id, stage, content)
        if result.passed:
            return result
        return ValidationResult(True, result.message, "hard_constraint")

    def validate_ai_speech(self, role_id: str, stage: int, content: str) -> ValidationResult:
        return self._check_hard_constraints(role_id, stage, content)

    def _check_hard_constraints(self, role_id: str, stage: int, content: str) -> ValidationResult:
        normalized = content.lower()
        for constraint in self._hard_constraints:
            target_role = constraint.get("role_id", "*")
            if target_role not in ("*", role_id):
                continue
            until_stage = int(constraint.get("until_stage", 0))
            if stage >= until_stage:
                continue
            for keyword in constraint.get("keywords", []):
                if str(keyword).lower() in normalized:
                    return ValidationResult(
                        False,
                        constraint.get("message", "发言包含当前阶段不应知道的信息。"),
                        "hard_constraint",
                    )
        return ValidationResult(True)
