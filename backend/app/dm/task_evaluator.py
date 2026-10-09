from __future__ import annotations

from typing import Any


ACTION_EVENTS = {
    "search", "public_speech", "public_response", "autonomous_public_speech",
    "autonomous_public_response", "private_speech", "private_response",
    "autonomous_private_speech", "autonomous_private_response", "clue_disclosure",
}


def validate_task_checks(checks: Any, role_ids: set[str]) -> None:
    if not isinstance(checks, list) or not checks:
        raise ValueError("task checks must be a non-empty list")
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("label"), str) or not check["label"].strip():
            raise ValueError("task check must have a non-empty label")
        kind = check.get("type")
        allowed = {"type", "label", "event_types", "minimum"} if kind == "activity_count" else {
            "type", "label", "channel", "disclosure_mode", "clue_id", "target_role_id", "new_public",
        }
        if not set(check).issubset(allowed):
            raise ValueError("task check contains unsupported fields")
        if kind == "activity_count":
            events = check.get("event_types")
            if not isinstance(events, list) or not events or not all(isinstance(event, str) and event in ACTION_EVENTS for event in events):
                raise ValueError("task check event_types is invalid")
            if len(events) != len(set(events)):
                raise ValueError("task check event_types must be unique")
            minimum = check.get("minimum")
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
                raise ValueError("task check minimum must be a positive integer")
        elif kind == "clue_disclosure":
            if check.get("channel") not in ("public", "private"):
                raise ValueError("task check channel is invalid")
            if check.get("disclosure_mode", "truthful") not in ("truthful", "distorted"):
                raise ValueError("task check disclosure_mode is invalid")
            if "clue_id" in check and (not isinstance(check["clue_id"], str) or not check["clue_id"].strip()):
                raise ValueError("task check clue_id is invalid")
            target = check.get("target_role_id")
            if target is not None and (not isinstance(target, str) or target not in role_ids or check["channel"] != "private"):
                raise ValueError("task check target_role_id is invalid")
            if not isinstance(check.get("new_public", False), bool):
                raise ValueError("task check new_public must be boolean")
            if check.get("new_public") and (check["channel"] != "public" or check.get("disclosure_mode", "truthful") != "truthful"):
                raise ValueError("new_public requires truthful public disclosure")
        else:
            raise ValueError("unsupported task check type")


def evaluate_task_check(check: dict[str, Any], *, role_id: str, stage: int,
                        counts: dict[str, int], audit_log: list[dict[str, Any]]) -> dict[str, Any]:
    if check["type"] == "activity_count":
        count = sum(counts.get(event, 0) for event in check["event_types"])
        minimum = check["minimum"]
    else:
        count = 0
        already_public: set[str] = set()
        minimum = 1
        for event in audit_log:
            if event.get("type") != "clue_disclosure":
                continue
            clue_id = str(event.get("clue_id", ""))
            matches = (
                event.get("stage") == stage and event.get("actor_role_id") == role_id
                and event.get("scope") == check["channel"]
                and event.get("disclosure_mode") == check.get("disclosure_mode", "truthful")
                and ("clue_id" not in check or clue_id == check["clue_id"])
                and ("target_role_id" not in check or event.get("target_role_id") == check["target_role_id"])
                and (not check.get("new_public") or clue_id not in already_public)
            )
            count += int(matches)
            if event.get("scope") == "public" and event.get("disclosure_mode") == "truthful":
                already_public.add(clue_id)
    return {
        "label": check["label"], "type": check["type"],
        "status": "completed" if count >= minimum else "failed",
        "count": count, "minimum": minimum,
    }
