"""Read-only derivation of live acceptance metrics; never calls a provider."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def records(call: dict) -> list[dict]:
    for message in call.get("messages", []):
        content = message.get("content", "")
        if content.startswith("[ROLE_MEMORY_DATA]\n"):
            return json.loads(content.partition("\n")[2])
    return []


def group(call: dict) -> str:
    profile = next((entry for entry in records(call) if entry["kind"] == "role_profile"), None)
    if profile and profile.get("owner_role_id", "").startswith("qa_"):
        return "synthetic_wrong_endings"
    return call["section"]


def summarize(report_path: Path) -> dict:
    report = load(report_path)
    ledger_path = report_path.with_name(report_path.stem + "-calls.json")
    ledger = load(ledger_path)
    calls = ledger["calls"]
    groups = defaultdict(list)
    for call in calls:
        groups[group(call)].append(call)

    def metrics(items):
        latencies = sorted(call["latency_ms"] for call in items if call["status"] == "completed")
        return {
            "requests": len(items), "statuses": dict(Counter(call["status"] for call in items)),
            "usage_known": sum(call.get("usage") is not None for call in items),
            "usage_unknown": sum(call.get("usage") is None for call in items),
            "usage_totals": {key: sum((call.get("usage") or {}).get(key, 0) for call in items)
                             for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                                         "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")},
            "completed_latency_ms": {"sample_count": len(latencies),
                "median": round(statistics.median(latencies), 2) if latencies else None,
                "sample_p95_nearest_rank": latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
                "max": max(latencies) if latencies else None},
        }

    result = {"paid_requests": len(calls), "hard_request_cap": ledger["limit"],
              "within_cap": len(calls) <= ledger["limit"], "prior_six_request_run_not_in_current_ledger": 6,
              "combined_with_prior_six": len(calls) + 6, "finished": report.get("finished", False),
              "global": metrics(calls), "groups": {key: metrics(items) for key, items in groups.items()},
              "engineering_checks": dict(Counter(check["status"] for check in report["checks"])),
              "memory_checks": {}, "games": [], "evidence_hashes": {}}
    for game in report["games"]:
        overview = {key: value for key, value in game.items() if key != "stages"}
        overview["stages"] = [{key: value for key, value in stage.items() if key != "commands"}
                              for stage in game.get("stages", [])]
        result["games"].append(overview)
    for mode in ("memory_provider_default", "memory_non_thinking_comparison"):
        checks = [check for check in report["memory_checks"] if check["mode"] == mode]
        result["memory_checks"][mode] = {"count": len(checks),
            "strict_statuses": dict(Counter(check["status"] for check in checks)),
            "boundary_passes": sum(check.get("boundary_ok", False) for check in checks),
            "certainty_passes": sum(check.get("certainty_ok", False) for check in checks)}

    data_path = PROJECT / "backend/data/verification" / report_path.stem
    audit_path = data_path / "full-game-role-records.json"
    events_path = data_path / "full-game-wire-events.json"
    if audit_path.exists():
        audit = load(audit_path)
        result["role_records"] = [{"role_id": role["role_id"],
            "operation_counts": dict(Counter(op["event_type"] for op in role["operations"])),
            "call_count": len(role["agent_context_audits"]),
            "notebook_count": len(role["reasoning_notebook"]),
            "manual_stages": [item["stage"] for item in role["reasoning_notebook"] if item["source_type"] == "manual"]}
            for role in audit["roles"]]
    if events_path.exists():
        events = load(events_path)
        result["search_results"] = [event["payload"] for event in events if event["type"] == "search_result"]
        result["phase_changes"] = [{"event_id": event.get("event_id"), "created_at": event.get("created_at"),
                                   "payload": event["payload"]} for event in events if event["type"] == "phase_changed"]
        result["end_votes"] = [event["payload"] for event in events if event["type"] == "investigation_end_vote"]

    # Scope and trust checks use typed records actually sent, not a keyword scan of all story text.
    violations = []
    for call in calls:
        for entry in records(call):
            if entry.get("scope") == "role_private" and entry.get("owner_role_id") not in entry.get("recipients", []):
                violations.append({"call": call["number"], "source_key": entry["source_key"]})
    result["record_scope_inconsistencies"] = violations
    result["scope_check_is_not_semantic_leakage_proof"] = True
    for path in (report_path, ledger_path, audit_path, events_path):
        if path.exists():
            result["evidence_hashes"][str(path.relative_to(PROJECT) if path.is_absolute() else path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.report)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("paid_requests", "within_cap", "combined_with_prior_six", "finished", "global", "memory_checks")},
                     ensure_ascii=False, indent=2))
