"""Exercise a short timeout/wrong-ending fixture on an already budget-guarded QA server."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.verification.live_game_check import PROJECT, WireSession


async def run(url: str, report_path: Path):
    if urlparse(url).hostname != "127.0.0.1":
        raise ValueError("分支验收只允许本机已受请求计数器保护的 QA 服务")
    script = json.loads((PROJECT / "backend/verification/fixtures/wrong_ending_timeout.json").read_text(encoding="utf-8"))
    report = {"fixture": script["script_meta"]["script_id"], "not_another_full_original_game": True,
              "shared_parent_request_cap": 100, "checks": [], "url": url}

    def check(name, passed, **details):
        item = {"id": name, "status": "PASS" if passed else "FAIL", "details": details}
        report["checks"].append(item)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(item, ensure_ascii=False), flush=True)

    async with httpx.AsyncClient(base_url=url, timeout=30) as http:
        registered = (await http.post("/api/v1/auth/register", json={"username": "branch_qa_" + uuid.uuid4().hex[:10],
            "password": uuid.uuid4().hex})).raise_for_status().json()
        http.headers["X-CSRF-Token"] = registered["csrf_token"]
        inspection = (await http.post("/api/v1/scripts/inspect", json={"mode": "deduction", "script": script})).raise_for_status().json()
        check("preview_has_no_truth", "truth" not in inspection and "stage_knowledge" not in json.dumps(inspection))
        game_id = (await http.post("/api/v1/games", json={"category": "mystery", "mode": "deduction",
            "player_role_id": "qa_a_reporter", "script": script})).raise_for_status().json()["id"]
        report["game_id"] = game_id
        # A second synthetic user must not be able to read or remove the first user's case.
        async with httpx.AsyncClient(base_url=url, timeout=30) as outsider:
            other = (await outsider.post("/api/v1/auth/register", json={"username": "outsider_qa_" + uuid.uuid4().hex[:10],
                "password": uuid.uuid4().hex})).raise_for_status().json()
            outsider.headers["X-CSRF-Token"] = other["csrf_token"]
            check("foreign_case_read_denied", (await outsider.get(f"/api/v1/games/{game_id}")).status_code == 404)
            check("foreign_case_delete_denied", (await outsider.delete(f"/api/v1/games/{game_id}")).status_code == 404)
        csrf = http.headers.pop("X-CSRF-Token")
        check("cookie_write_without_csrf_denied", (await http.put(f"/api/v1/games/{game_id}/notebook/manual", json={"content": "blocked"})).status_code == 403)
        http.headers["X-CSRF-Token"] = csrf
        session = WireSession(http, url, game_id)
        await session.connect()
        try:
            await session.command("advance_phase", terminal={"private_script"})
            await session.command("advance_phase", terminal={"investigation_open"})
            started = time.monotonic()
            bad_search = await session.command("search", {"target_id": "archive_fireplace"})
            bad_result = next(event["payload"] for event in bad_search if event["type"] == "search_result")
            check("unknown_search_target_is_not_success", not bad_result.get("clue") and bad_result.get("message") == "未知搜证目标。")
            good_search = await session.command("search", {"target_id": "fireplace"})
            good_result = next(event["payload"] for event in good_search if event["type"] == "search_result")
            check("correct_fireplace_search_obtains_clue", (good_result.get("clue") or {}).get("id") == "qa_burned_note")
            while (await http.get(f"/api/v1/games/{game_id}")).raise_for_status().json()["current_phase"] == "investigation":
                if time.monotonic() - started > 30:
                    raise RuntimeError("自然时限未触发主持阶段")
                await asyncio.sleep(0.1)
            elapsed = time.monotonic() - started
            check("natural_timeout_not_early", 4.8 <= elapsed <= 15, observed_seconds=round(elapsed, 3), configured_seconds=5)
            early = await session.command("advance_phase", terminal={"replay", "dm_narration_end"})
            check("unresolved_final_cannot_replay", any(event["type"] == "error" for event in early))
            decisions = await session.command("stage_vote", {"target_role_id": "qa_b_manager"}, terminal={"stage_resolution"})
            resolution = next(event["payload"]["resolution"] for event in decisions if event["type"] == "stage_resolution")
            report["final_vote"] = resolution["vote"]
            check("wrong_vote_has_explicit_result", not resolution["vote"]["pending"] and not resolution["vote"]["correct"] and bool(resolution["vote"]["outcome_text"]))
            result = await session.command("advance_phase", terminal={"replay"})
            replay = next(event["payload"] for event in result if event["type"] == "replay")
            report["replay"] = replay
            check("wrong_replay_does_not_publish_truth", not replay["truth_revealed"] and script["truth"]["full_story"] not in json.dumps(replay, ensure_ascii=False))
            audit = (await http.get(f"/api/v1/games/{game_id}/role-records")).raise_for_status().json()
            check("wrong_game_full_role_records_available", len(audit["roles"]) == 3)
            report["audit"] = audit
            await session.close()
            await session.connect()
            check("wrong_ending_persists_after_reconnect", session.snapshots[-1]["game"]["phase"]["phase"] == "replay")
            events = []
            cursor = 0
            while True:
                page = (await http.get(f"/api/v1/games/{game_id}/events", params={"limit": 100,
                    "after_event_id": cursor})).raise_for_status().json()
                events.extend(page["items"])
                if not page["has_more"]:
                    break
                cursor = page["next_cursor"]
            check("event_ids_are_unique_and_monotone", [e["event_id"] for e in events] == sorted({e["event_id"] for e in events}))
        except Exception as exc:
            check("branch_check_error", False, error=str(exc))
        finally:
            await session.close()
        report["finished"] = True
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return not any(c["status"] == "FAIL" for c in report["checks"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error("报告已存在，不能覆盖原始结果")
    raise SystemExit(0 if asyncio.run(run(args.url, args.report)) else 1)
