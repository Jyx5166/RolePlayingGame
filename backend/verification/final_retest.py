"""Bounded final-stage regression using cloned historical blind-game state.

No previous answer or oracle is sent to actors. The original evidence/database
is read-only; paid runs append to the original CNY 20 ledger.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.verification.blind_play_check import (
    BlindAcceptance, PROJECT, SCRIPT_IDS, PRICE_SOURCE, account_balance, load_settings, write_json,
)
from backend.verification.blind_budget import MoneyRequestLedger, Pricing
from backend.verification.blind_oracles import check_ending
from llm.budget import ContextBudget
from loader.script_loader import ScriptLoader


TARGETS = {
    "rainy_night_letter": ["rnl_shen_yu"],
    "last_train": ["lt_tao_wen"],
    "deep_sea_echo": ["chen_cheng"],
    "old_house_corridor": ["meng_lan"],
    "silent_theater": ["gan_ji"],
}


def clone_database(source: Path, destination: Path):
    if destination.exists() or source.resolve() == destination.resolve():
        raise ValueError("Fixture database must be a new copy")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as old:
        with closing(sqlite3.connect(destination)) as new:
            old.backup(new)


def final_proposal(raw, roles, clues):
    """Normalize only a complete JSON fence; never repair a decision's contents."""
    body = raw.strip()
    fenced = body.startswith("```json\n") and body.endswith("\n```")
    if fenced:
        body = body[8:-4]
    value = json.loads(body)
    if not isinstance(value, dict) or value.get("vote_role_id") not in roles:
        raise ValueError("Final proposal must select a visible role")
    evidence = value.get("evidence_ids", [])
    if not isinstance(evidence, list) or any(item not in clues for item in evidence):
        raise ValueError("Final proposal cites an unavailable clue")
    if not isinstance(value.get("explanation"), str):
        raise ValueError("Final proposal must explain its evidence")
    return value, fenced


class FinalRetest(BlindAcceptance):
    def __init__(self, args):
        self.args = args
        self.settings = load_settings()
        self.source_root = PROJECT / "backend/data/verification/blind-five-20261014-live"
        self.root = PROJECT / "backend/data/verification" / args.name
        self.root.mkdir(parents=True, exist_ok=False)
        if not args.echo and (self.settings.llm_model != "deepseek-v4-pro"
                              or self.settings.llm_base_url.rstrip("/") not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}):
            raise ValueError("Retest uses only the previously authorized provider/model")
        self.source = json.loads((self.source_root / "report.json").read_text(encoding="utf-8"))
        self.source_cases = {game["script_id"]: game for game in self.source["games"] if game.get("attempt") == "attempt2"}
        ledger_path = self.source_root / "requests.json"
        baseline = ledger_path.read_bytes()
        if args.echo:
            self.ledger = MoneyRequestLedger(self.root / "requests.json", Pricing("9", "27", PRICE_SOURCE, "2026-10-14", self.settings.llm_model))
        else:
            # Preserve the completed prior batch before extending its single ledger.
            baseline_path = self.root / "requests-before-retest.json"
            if not baseline_path.exists():
                baseline_path.write_bytes(baseline)
            self.ledger = MoneyRequestLedger(ledger_path, Pricing("9", "27", PRICE_SOURCE, "2026-10-14", self.settings.llm_model), resume=True)
        self.budget = ContextBudget(self.settings.llm_context_window, 8000 if args.votes_only else self.settings.llm_input_limit,
                                    512 if args.votes_only else 4096, self.settings.llm_safety_margin)
        self.player_budget = ContextBudget(131072, 64000, 4096, 1024)
        self.case, self.dm, self.purpose = None, None, "setup"
        self.captures, self.received, self.working = [], [], []
        self.user_id = self.source["qa_user_id"]
        self.baseline_calls = len(self.ledger.calls)
        self.report = {"client_date": "2026-10-15", "started_at": datetime.now(timezone.utc).isoformat(),
                       "paid": not args.echo, "model": self.settings.llm_model, "output_limit": self.budget.output_limit,
                       "role_input_limit": self.budget.input_limit, "votes_only": args.votes_only,
                       "probe_only": getattr(args, "probe_only", False),
                       "baseline_ledger_entries": self.baseline_calls,
                       "baseline_confirmed_guarded_calls": sum(not row.get("accounting_placeholder", False) for row in self.ledger.calls),
                       "baseline_unknown_request_placeholders": sum(row.get("accounting_placeholder", False) for row in self.ledger.calls),
                       "baseline_upper_cny": str(self.ledger.accounted_upper_cny),
                       "original_ledger_sha256": hashlib.sha256(baseline).hexdigest(), "automatic_api_retries": 0,
                       "source_db_sha256": hashlib.sha256((self.source_root / "app.db").read_bytes()).hexdigest(),
                       "protocol": ("clone previous five failed final snapshots; reuse original paid blind player proposal; fresh real AI ballots and replay; compact 8000/512 actor budgets" if args.votes_only else "clone previous five failed final-stage snapshots; controlled reopen final investigation; targeted native public turns; fresh player-visible final proposal; real AI ballots; replay"),
                       "not_covered": ["full restart/all earlier acts", "browser and WebSocket", "multiple seeds"],
                       "selected_script_ids": getattr(args, "script", None) or SCRIPT_IDS,
                       "games": []}
        if getattr(args, "probe_only", False):
            self.report["protocol"] = "clone selected failed final-stage snapshots; targeted public-source regression only; no new inference, ballots or ending"
        clone_database(self.source_root / "app.db", self.root / "app.db")
        os.environ["AI_MURDER_MYSTERY_DATA_DIR"] = str(self.root)
        from main import build_dm
        from game_service import GameService
        from storage import AppStore
        self.build_dm = build_dm
        self.store = AppStore(self.root / "app.db")
        self.service = GameService(self.store, self.factory)
        self.save()

    def context(self, actor):
        return {**super().context(actor), "attempt": "final_retest_20261015"}

    async def decide(self, purpose):
        self.purpose = purpose
        visible = self.visible()
        messages = [{"role": "system", "content": "你是这场案件的玩家替身。只根据自己的可见卷宗独立形成最终指认，其他角色说法只是证词，不自动当成事实；没有开发者答案。输出一个JSON对象：vote_role_id为公开角色ID，evidence_ids只引用卷宗中实际已得线索ID，explanation简要区分事实/证词/推测并排除最强替代嫌疑，uncertainties说明仍不确定处。不要Markdown。"},
                    {"role": "user", "content": json.dumps({"task": purpose, "visible_state": visible}, ensure_ascii=False)}]
        if self.args.echo:
            shot = self.capture(self.dm.state.human_player_role_id, messages, None)
            raw = json.dumps({"vote_role_id": visible["public_roles"][0]["role_id"], "evidence_ids": [], "explanation": "Echo mechanical regression, not independent inference."})
            shot.update(status="completed", output=raw, paid_request_numbers=[])
            self.finish_capture(shot)
        else:
            raw = await self.client(self.dm.state.human_player_role_id).chat(messages)
        value, fenced = final_proposal(raw, {item["role_id"] for item in visible["public_roles"]},
                                      {item["clue_id"] for item in visible["notebook"]["clues"]})
        self.case["player_decisions"].append({"stage": self.dm.state.current_stage_num, "purpose": purpose,
                                               "decision": value, "markdown_envelope_removed": fenced})
        self.save()
        return value

    async def run_case(self, script_id):
        from domain.state import ScenePhase
        from runtime.workflow import GameWorkflow
        source = self.source_cases[script_id]
        self.original = ScriptLoader(PROJECT / "backend/resources/scripts").load(script_id)
        self.case = {"script_id": script_id, "title": source["title"], "game_id": source["game_id"],
                     "capture_directory": script_id, "status": "started", "commands": [], "player_decisions": [],
                     "player_role_id": source["player_role_id"], "private_probe": source.get("private_probe"),
                     "private_canary": source.get("private_canary"), "source_sha256": source["source_sha256"],
                     "paid_calls_before": len(self.ledger.calls), "upper_before": str(self.ledger.accounted_upper_cny)}
        self.report["games"].append(self.case)
        self.captures = []
        self.received = [event for command in source["commands"] for event in command["events"]]
        # These are prior player hypotheses, excluding the already-scored final answer.
        self.working = [{"stage": item["stage"], "suspects": item["decision"].get("suspects"),
                         "explanation": item["decision"].get("explanation")} for item in source["player_decisions"]
                        if not item["purpose"].startswith("最终指认")]
        self.dm = None
        _, self.dm = await self.service.get_engine(self.user_id, source["game_id"])
        state = self.dm.state
        if state.current_stage_num != state.total_stages or state.scene_phase.value != "dm_hosting":
            raise ValueError("Source is not the previously failed final-stage snapshot")
        for actor in state.ai_role_ids:
            self.dm.agent_pool.get(actor)._llm.qa_actor = actor
        with self.store._connect() as connection:
            prior_models = {row[0] for row in connection.execute("SELECT model_request_id FROM model_requests WHERE game_id=?", (source["game_id"],))}
            prior_tools = {row[0] for row in connection.execute("SELECT tool_call_id FROM tool_calls WHERE game_id=?", (source["game_id"],))}
        if not self.args.votes_only:
            state.scene_phase = ScenePhase.INVESTIGATION
            state.phase_started_at = time.time()
            state.investigation_deadline_at = time.time() + 3600
            self.service.persist_engine_events(source["game_id"], self.dm)
            self.service.runtime_store.bump_state(source["game_id"], phase_changed=True)
        self.workflow = GameWorkflow(self.service, self.user_id, self.dm)
        self.save()
        try:
            if not self.args.votes_only:
                for actor in TARGETS[script_id]:
                    name = self.dm.permission.role_name(actor)
                    await self.command("player_speech", content=f"{name}，请由你回应：只以你本人的身份核对行踪和已知证据；区分自己的经历、他人证词与推断。没有来源的交接或持有细节请明确说无法确认，不要把别人的第一人称经历当作自己的记忆。")
                if getattr(self.args, "probe_only", False):
                    self.case["status"] = "probe_completed"
                    self.case["scope"] = "Targeted public-source regression only; no new inference, ballots or ending"
                    return
                state.investigation_deadline_at = time.time() - 0.1
                self.service.persist_engine_events(source["game_id"], self.dm)
                await self.command("phase_timeout")
                decision = await self.decide("最终指认：依据你可见卷宗独立形成结论，不要读取开发者答案")
            else:
                decision = source["blind_vote"]
                decision = {"vote_role_id": decision["role_id"], "explanation": decision["explanation"], "evidence_ids": decision["evidence_ids"]}
                self.case["player_proposal_reused_from"] = {"source_game_id": source["game_id"], "source_attempt": "attempt2", "new_player_model_calls": 0}
            target = decision.get("vote_role_id")
            if target is None:
                raise ValueError("Missing player final proposal")
            self.case["blind_vote"] = {"role_id": target, "correct": target == self.original["truth"]["culprit_role_id"],
                                       "explanation": decision.get("explanation"), "evidence_ids": decision.get("evidence_ids", [])}
            await self.command("stage_vote", target_role_id=target)
            await self.command("advance_phase")
            replay = self.dm.get_replay()
            self.case["ending"] = replay
            self.case["ending_check"] = check_ending(self.original, replay["final_decision"], replay, reveal_truth_on_failure=True)
            self.case["status"] = "completed" if self.case["ending_check"]["status"] == "PASS" else "ending_failed"
        except Exception as exc:
            self.case.update(status="incomplete", error_type=type(exc).__name__, error=str(exc).replace(self.settings.llm_api_key, "[REDACTED]"))
        finally:
            self.case["paid_request_count"] = len(self.ledger.calls) - self.case["paid_calls_before"]
            self.case["upper_cost_cny"] = str(self.ledger.accounted_upper_cny - __import__("decimal").Decimal(self.case["upper_before"]))
            self.case["input_failures"] = [shot["capture_id"] for shot in self.captures if shot.get("input_audit", {}).get("status") == "FAIL"]
            self.case["workflow_problems"] = [event for command in self.case["commands"] for event in command["events"] if event.get("type") in {"error", "actor_turn_stopped"} or event.get("fallback")]
            if getattr(self.args, "probe_only", False):
                published = {event.get("role_id") for command in self.case["commands"] for event in command["events"] if event.get("type") == "ai_speech" and not event.get("fallback")}
                self.case["probe_response_published"] = set(TARGETS[script_id]).issubset(published)
                if not self.case["probe_response_published"] or self.case["input_failures"] or self.case["workflow_problems"]:
                    self.case["status"] = "probe_failed"
            with self.store._connect() as connection:
                models = [dict(row) for row in connection.execute("SELECT * FROM model_requests WHERE game_id=?", (source["game_id"],)) if row["model_request_id"] not in prior_models]
                tools = [dict(row) for row in connection.execute("SELECT * FROM tool_calls WHERE game_id=?", (source["game_id"],)) if row["tool_call_id"] not in prior_tools]
            write_json(self.root / script_id / "runtime-models.json", models)
            write_json(self.root / script_id / "runtime-tools.json", tools)
            self.save()
            print(json.dumps({"case": script_id, "status": self.case["status"], "calls": self.case["paid_request_count"], "cumulative_upper": str(self.ledger.accounted_upper_cny)}, ensure_ascii=True), flush=True)

    async def run(self):
        if not self.args.echo:
            self.report["balance_before"] = account_balance(self.settings)
        for script_id in (getattr(self.args, "script", None) or SCRIPT_IDS):
            await self.run_case(script_id)
        self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        if not self.args.echo:
            self.report["balance_after"] = account_balance(self.settings)
        self.report["original_db_unchanged"] = hashlib.sha256((self.source_root / "app.db").read_bytes()).hexdigest() == self.report["source_db_sha256"]
        self.save()
        return 0 if all(game["status"] in {"completed", "probe_completed"} for game in self.report["games"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--echo", action="store_true")
    parser.add_argument("--script", choices=SCRIPT_IDS, action="append", help="Explicit targeted follow-up; never auto-retry a failed trial")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--votes-only", action="store_true", help="Reuse prior blind human proposal; verify real native ballots/replay with compact budget")
    mode.add_argument("--probe-only", action="store_true", help="Explicit public-source follow-up only; does not count as a new ending trial")
    raise SystemExit(asyncio.run(FinalRetest(parser.parse_args()).run()))
