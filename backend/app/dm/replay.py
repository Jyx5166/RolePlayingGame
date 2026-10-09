from __future__ import annotations

from typing import Any


class ReplayEngine:
    def build(
        self,
        script: dict[str, Any],
        speech_history: list[dict[str, str]],
        final_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        truth = script["truth"]
        truth_revealed = (
            final_decision is None
            or bool(final_decision.get("truth_revealed"))
        )
        verdict = (
            str(final_decision.get("outcome_text", ""))
            if final_decision
            else ""
        )
        return {
            "full_story": (
                truth.get("full_story", "")
                if truth_revealed
                else verdict
            ),
            "timeline": (
                truth.get("complete_timeline", {})
                if truth_revealed
                else {}
            ),
            "role_arcs": (
                truth.get("role_arcs", {})
                if truth_revealed
                else {}
            ),
            "speech_count": len(speech_history),
            "truth_revealed": truth_revealed,
            "verdict": verdict,
            "final_decision": final_decision,
        }
