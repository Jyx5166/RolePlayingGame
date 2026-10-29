"""Bounded live acceptance over real HTTP/WebSocket routes and an isolated SQLite database."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx
import uvicorn
import websockets

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "backend" / "app"))
FULL_GAME_SEARCH_TARGETS = {1: ["archive_desk"], 2: ["medicine_cabinet"], 3: ["clocktower_log", "fireplace"]}

from config import load_settings
from llm.budget import ContextBudget
from llm.echo import EchoLLM
from llm.openai_compatible import OpenAICompatibleLLM
from backend.verification.accounts import new_verification_account, save_verification_account


class RequestLimitExceeded(RuntimeError):
    pass


class RequestLedger:
    def __init__(self, limit: int, path: Path | None = None):
        if not 1 <= limit <= 100:
            raise ValueError("request limit must be between 1 and 100")
        self.limit = limit
        self.path = path
        self.calls: list[dict] = []
        self.section = "initialization"

    def save(self):
        if self.path:
            self.path.write_text(json.dumps({"limit": self.limit, "reserved_requests": len(self.calls),
                "calls": self.calls}, ensure_ascii=False, indent=2), encoding="utf-8")

    def reserve(self, messages: list[dict], effort: str, output_limit: int) -> dict:
        # All clients run on the same asyncio loop; reserve has no await before incrementing.
        if len(self.calls) >= self.limit:
            raise RequestLimitExceeded("本轮 DeepSeek 请求额度已用完，禁止继续调用")
        record = {"number": len(self.calls) + 1, "section": self.section, "status": "running",
                  "reasoning_effort": effort or "provider_default", "output_limit": output_limit,
                  "messages": messages, "started_at": time.time()}
        self.calls.append(record)
        self.save()
        print(json.dumps({"event": "provider_start", "number": record["number"],
                          "limit": self.limit, "section": self.section}, ensure_ascii=False), flush=True)
        return record


class CountedDeepSeek(OpenAICompatibleLLM):
    def __init__(self, ledger: RequestLedger, settings, *, effort: str | None = None):
        super().__init__(settings.llm_model, settings.llm_base_url, settings.llm_api_key,
            settings.llm_timeout_seconds, budget=ContextBudget(settings.llm_context_window,
                settings.llm_input_limit, settings.llm_output_limit, settings.llm_safety_margin),
            reasoning_effort=settings.llm_reasoning_effort if effort is None else effort)
        self.ledger = ledger

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.reset_call_metadata()
        self.budget.validate(messages)
        record = self.ledger.reserve(messages, self.reasoning_effort, self.budget.output_limit)
        started = time.perf_counter()
        try:
            response = await super().chat(messages)
            record.update(status="completed", response=response)
            return response
        except asyncio.CancelledError:
            record.update(status="canceled", error="客户端等待已取消，服务商是否计费未知")
            raise
        except Exception as exc:
            record.update(status="failed", error=str(exc).replace(self.api_key, "[REDACTED]"))
            raise
        finally:
            record.update(self.call_metadata(), latency_ms=round((time.perf_counter() - started) * 1000, 2))
            self.ledger.save()
            print(json.dumps({key: record.get(key) for key in
                ("number", "section", "status", "latency_ms", "usage", "finish_reason", "error")},
                ensure_ascii=False), flush=True)


class WireSession:
    def __init__(self, http: httpx.AsyncClient, url: str, game_id: int):
        self.http, self.url, self.game_id = http, url, game_id
        self.socket = None
        self.reader = None
        self.cursor = 0
        self.events: list[dict] = []
        self.snapshots: list[dict] = []
        self.pending: dict[str, tuple[asyncio.Future, set[str]]] = {}
        self.received: dict[str, list[dict]] = {}

    async def connect(self):
        ticket = (await self.http.post(f"/api/v1/games/{self.game_id}/ws-ticket")).raise_for_status().json()["ticket"]
        self.socket = await websockets.connect(self.url.replace("http:", "ws:") +
            f"/ws/v1/games/{self.game_id}?ticket={ticket}&after_event_id={self.cursor}",
            ping_timeout=None, max_size=8_000_000)
        self.reader = asyncio.create_task(self._read())
        count = len(self.snapshots)
        await self.wait(lambda: len(self.snapshots) > count, 15)

    async def close(self):
        if self.socket:
            await self.socket.close()
        if self.reader:
            with contextlib.suppress(websockets.ConnectionClosed):
                await self.reader

    async def _read(self):
        async for raw in self.socket:
            envelope = json.loads(raw)
            kind = envelope["kind"]
            if kind == "snapshot":
                self.snapshots.append(envelope["payload"])
            elif kind == "resume":
                self.events.extend(envelope["payload"]["events"])
            elif kind in {"event", "error"}:
                self.events.append(envelope)
                request = envelope.get("request_id")
                self.received.setdefault(request, []).append(envelope)
                if request in self.pending:
                    future, terminal = self.pending[request]
                    if envelope["type"] in terminal and not future.done():
                        future.set_result(self.received[request])
            if envelope.get("event_id"):
                self.cursor = max(self.cursor, int(envelope["event_id"]))

    async def wait(self, predicate, timeout: float):
        async def poll():
            while not predicate():
                if self.reader and self.reader.done():
                    self.reader.result()
                    raise RuntimeError("验收 WebSocket 已关闭")
                await asyncio.sleep(0.05)
        await asyncio.wait_for(poll(), timeout)

    async def command(self, command: str, payload: dict | None = None, *, terminal: set[str] | None = None,
                      timeout: float = 420, request_id: str | None = None):
        request_id = request_id or str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = (future, (terminal or {"investigation_progress"}) | {"error"})
        started = time.perf_counter()
        await self.socket.send(json.dumps({"protocol_version": "1.0", "kind": "command", "type": command,
            "request_id": request_id, "game_id": self.game_id, "payload": payload or {}}, ensure_ascii=False))
        try:
            events = await asyncio.wait_for(future, timeout)
            print(json.dumps({"event": "command_complete", "game_id": self.game_id, "command": command,
                "types": [item["type"] for item in events], "seconds": round(time.perf_counter() - started, 2)},
                ensure_ascii=False), flush=True)
            return events
        finally:
            self.pending.pop(request_id, None)


class Acceptance:
    def __init__(self, args):
        self.args = args
        self.settings = load_settings()
        if not args.echo and (self.settings.llm_provider != "openai_compatible" or
                urlparse(self.settings.llm_base_url).hostname != "api.deepseek.com"):
            raise ValueError("仅允许现有 DeepSeek 配置；不自动修改生产模型或服务商")
        self.ledger = RequestLedger(args.max_requests, args.report.with_name(args.report.stem + "-calls.json"))
        self.report = {"request_limit": args.max_requests, "paid": not args.echo, "production_configuration_changed": False,
            "automatic_provider_retries": 0, "games": [], "checks": [], "memory_checks": []}
        self.report["settings"] = {"model": self.settings.llm_model, "timeout_seconds": self.settings.llm_timeout_seconds,
            "reasoning_effort": self.settings.llm_reasoning_effort or "provider_default",
            "context_window": self.settings.llm_context_window, "input_limit": self.settings.llm_input_limit,
            "output_limit": self.settings.llm_output_limit, "safety_margin": self.settings.llm_safety_margin}
        self.server, self.server_task, self.app = None, None, None
        self.url = ""
        self.data = PROJECT / "backend" / "data" / "verification" / args.report.stem
        self.data.mkdir(parents=True, exist_ok=False)
        account = new_verification_account("live_qa")
        self.username, self.password = account["username"], account["password"]

    def save(self):
        calls = self.ledger.calls
        self.report.update(reserved_requests=len(calls), usage_reported_requests=sum(bool(c.get("usage")) for c in calls),
            request_statuses=dict(Counter(c["status"] for c in calls)),
            usage_totals={key: sum((c.get("usage") or {}).get(key, 0) for c in calls)
                          for key in ("prompt_tokens", "completion_tokens", "total_tokens")})
        self.args.report.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(self, name: str, condition: bool, **details):
        item = {"id": name, "status": "PASS" if condition else "FAIL", "details": details}
        self.report["checks"].append(item)
        self.save()
        print(json.dumps(item, ensure_ascii=False), flush=True)

    async def start(self):
        os.environ["AI_MURDER_MYSTERY_DATA_DIR"] = str(self.data.resolve())
        from main import build_dm, create_app
        self.app = create_app(self.data / "acceptance.db")
        def factory():
            dm = build_dm()
            class Factory:
                def create(inner):
                    if self.args.echo:
                        client = EchoLLM()
                        client.budget = ContextBudget(self.settings.llm_context_window, self.settings.llm_input_limit,
                            self.settings.llm_output_limit, self.settings.llm_safety_margin)
                        return client
                    return CountedDeepSeek(self.ledger, self.settings)
            dm.llm_factory = Factory()
            return dm
        self.app.state.game_service.dm_factory = factory
        listener = socket.socket()
        listener.bind(("127.0.0.1", self.args.port))
        listener.listen(128)
        self.url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="error", access_log=False))
        self.server_task = asyncio.create_task(self.server.serve(sockets=[listener]))
        while not self.server.started:
            if self.server_task.done():
                self.server_task.result()
                raise RuntimeError("验收服务启动失败")
            await asyncio.sleep(0.05)
        print(json.dumps({"event": "server_ready", "url": self.url}, ensure_ascii=False), flush=True)

    async def stop(self):
        if self.server:
            self.server.should_exit = True
            await self.server_task

    async def phase(self, http, game_id):
        return (await http.get(f"/api/v1/games/{game_id}")).raise_for_status().json()

    async def full_game(self, http):
        self.ledger.section = "full_game_default_parameters"
        created = (await http.post("/api/v1/games", json={"category": "mystery", "mode": "deduction",
            "player_role_id": "shen_zhiwei", "script_id": "fog_harbor_clocktower"})).raise_for_status().json()
        game_id = created["id"]
        game = {"game_id": game_id, "script": "unmodified_fog_harbor_clocktower", "human_role": "shen_zhiwei",
                "stages": [], "status": "running", "started_at": time.time()}
        self.report["games"].append(game)
        session = WireSession(http, self.url, game_id)
        await session.connect()
        private_canary = "QA_PRIVATE_" + uuid.uuid4().hex[:12]
        try:
            self.check("in_game_audit_denied", (await http.get(f"/api/v1/games/{game_id}/role-records")).status_code == 409)
            for stage in range(1, 4):
                current = await self.phase(http, game_id)
                if current["current_stage"] != stage or current["current_phase"] != "briefing":
                    raise RuntimeError(f"期望第 {stage} 幕开场，实际 {current['current_stage']} / {current['current_phase']}")
                self.ledger.section = f"full_game_stage_{stage}"
                await session.command("advance_phase", terminal={"private_script"})
                await http.put(f"/api/v1/games/{game_id}/notebook/manual", json={"content": f"第{stage}幕验收手记：证词需核验，物证按来源记录。"})
                await session.command("advance_phase", terminal={"investigation_open"})
                started = time.time()
                stage_result = {"stage": stage, "commands": [], "started_at": started}
                game["stages"].append(stage_result)
                if stage == 1:
                    count = sum(event["type"] == "autonomy_status" for event in session.events)
                    await session.wait(lambda: sum(event["type"] == "autonomy_status" for event in session.events) > count, 280)
                    self.check("autonomy_without_human_trigger", True)
                targets = FULL_GAME_SEARCH_TARGETS[stage]
                for target in targets:
                    if (await self.phase(http, game_id))["current_phase"] != "investigation":
                        break
                    search_events = await session.command("search", {"target_id": target})
                    stage_result["commands"].extend(search_events)
                    search_result = next((event["payload"] for event in search_events if event["type"] == "search_result"), None)
                    self.check(f"stage_{stage}_search_{target}_valid", search_result is not None and
                        search_result.get("message") not in {"未知搜证目标。", "该目标尚未解锁。"},
                        target_id=target, clue_obtained=bool((search_result or {}).get("clue")), result=search_result)
                notebook = (await http.get(f"/api/v1/games/{game_id}/notebook")).raise_for_status().json()
                for clue in notebook.get("clues", []):
                    if int(clue.get("stage", 0)) != stage:
                        continue
                    if (await self.phase(http, game_id))["current_phase"] != "investigation":
                        break
                    stage_result["commands"].extend(await session.command("share_clue", {"clue_id": clue["clue_id"],
                        "mode": "distorted" if stage == 2 else "truthful", "scope": "public",
                        "content": "我声称登记册完好，没有发现异常。" if stage == 2 else ""}))
                if stage == 1 and (await self.phase(http, game_id))["current_phase"] == "investigation":
                    invited = await session.command("whisper_invite", {"target_role_id": "xu_yanzhou"})
                    if any(event["type"] == "whisper_accepted" for event in invited):
                        stage_result["commands"].extend(await session.command("whisper_speech", {"content":
                            f"只给你的临时编号是{private_canary}，不要向别人转述。你看到医生的位置是什么？"}))
                        before = self.app.state.store.get_runtime_snapshot(self.user_id, game_id)["state"]["investigation_deadline_at"]
                        await session.close()
                        await self.stop()
                        await self.start()
                        http.base_url = self.url
                        session.url = self.url
                        await session.connect()
                        restored = session.snapshots[-1]["game"]
                        self.check("restart_private_partner", restored["whisper_status"]["active_target_role_id"] == "xu_yanzhou")
                        self.check("restart_stage_and_phase", restored["phase"]["stage"] == stage and restored["phase"]["phase"] == "investigation")
                        after = self.app.state.store.get_runtime_snapshot(self.user_id, game_id)["state"]["investigation_deadline_at"]
                        self.check("restart_deadline_not_reset", after == before, before=before, after=after)
                        if restored["phase"]["phase"] == "investigation":
                            recalled = await session.command("whisper_speech", {"content": "刚才只给你的临时编号是什么？只在本次私聊核对。"})
                            stage_result["commands"].extend(recalled)
                            if not self.args.echo:
                                self.check("live_private_recall_after_restart", any(private_canary in event["payload"].get("content", "")
                                    for event in recalled if event["payload"].get("sender_type") == "agent"))
                            await session.command("whisper_close")
                    else:
                        self.check("private_invitation_declined_honestly", True, coverage="私人恢复未覆盖", events=invited)
                if stage == 2 and (await self.phase(http, game_id))["current_phase"] == "investigation":
                    rejected = await session.command("whisper_invite", {"target_role_id": "xu_yanzhou"})
                    self.check("stage_2_private_action_rejected", any(event["type"] == "error" for event in rejected))
                speeches = {1: "顾医生，你最后一次见陆先生是什么时间？请区分亲眼看到的事实和推测。",
                    2: "周律师，请说明账目问题与遗嘱的关系，物证和各人的说法必须分开核对。",
                    3: "顾医生，药瓶批号17与71不一致，钟楼慢十四分钟。请解释换药机会和资金问题。"}
                if (await self.phase(http, game_id))["current_phase"] == "investigation":
                    stage_result["commands"].extend(await session.command("player_speech", {"content": speeches[stage]}))
                for attempt in range(2):
                    if (await self.phase(http, game_id))["current_phase"] != "investigation":
                        break
                    vote_events = await session.command("request_phase_end", terminal={"investigation_end_vote"})
                    stage_result["commands"].extend(vote_events)
                    end_vote = next((event["payload"]["vote"] for event in vote_events if event["type"] == "investigation_end_vote"), None)
                    if end_vote and end_vote["approved"]:
                        self.check(f"stage_{stage}_strict_majority", end_vote["approved_votes"] > end_vote["total_votes"] / 2, vote=end_vote)
                        break
                    if attempt == 0:
                        print(json.dumps({"event": "human_command_retry", "stage": stage, "command": "request_phase_end"}), flush=True)
                while (await self.phase(http, game_id))["current_phase"] == "investigation":
                    await asyncio.sleep(1)
                for attempt in range(2):
                    decision = await session.command("stage_vote", {"target_role_id": "gu_linchuan"}, terminal={"stage_resolution"})
                    stage_result["commands"].extend(decision)
                    result = next((event["payload"]["resolution"] for event in decision if event["type"] == "stage_resolution"), None)
                    if result and not result["vote"]["pending"]:
                        stage_result["resolution"] = result
                        break
                    if attempt == 1:
                        raise RuntimeError("两次正常投票请求后仍未形成有效结算；不造票或修改剧情状态")
                await session.command("advance_phase", terminal={"dm_narration_end", "replay"})
                stage_result["elapsed_seconds"] = round(time.time() - started, 2)
                self.save()
            detail = await self.phase(http, game_id)
            audit = (await http.get(f"/api/v1/games/{game_id}/role-records")).raise_for_status().json()
            (self.data / "full-game-role-records.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
            game.update(status=detail["status"], elapsed_seconds=round(time.time() - game["started_at"], 2),
                        final_decision=audit.get("final_decision"), event_count=len(session.events))
            self.check("full_three_stage_completion", detail["status"] == "completed" and detail["current_stage"] == 3)
            self.check("four_role_audit_available", len(audit["roles"]) == 4)
            human = next(role for role in audit["roles"] if role["role_id"] == "shen_zhiwei")
            self.check("manual_revision_stage_history", {entry["stage"] for entry in human["reasoning_notebook"] if entry["source_type"] == "manual"} == {1, 2, 3})
            agent_audits = [item for role in audit["roles"] for item in role["agent_context_audits"]]
            self.check("actual_input_version_and_budget", bool(agent_audits) and all(
                item["context"].get("prompt_version") == "role-context-v2" and
                (not item["context"].get("input_prepared") or item["context"]["memory_selection"]["estimated_input_tokens"] <= self.settings.llm_input_limit)
                for item in agent_audits))
            foreign = [item for role in audit["roles"] if role["role_id"] != "xu_yanzhou" for item in role["agent_context_audits"]]
            self.check("private_canary_not_in_third_party_input", all(private_canary not in json.dumps(item["context"], ensure_ascii=False) for item in foreign))
            game["role_activity_counts"] = {role["role_id"]: dict(Counter(op["event_type"] for op in role["operations"])) for role in audit["roles"]}
            game["wire_events_path"] = str(self.data / "full-game-wire-events.json")
            (self.data / "full-game-wire-events.json").write_text(json.dumps(session.events, ensure_ascii=False, indent=2), encoding="utf-8")
            await session.close()
            await session.connect()
            self.check("completed_reconnect_is_replay", session.snapshots[-1]["game"]["phase"]["phase"] == "replay")
        except Exception as exc:
            game.update(status="blocked", error=str(exc).replace(self.settings.llm_api_key, "[REDACTED]"))
            self.check("full_game_error", False, error=game["error"])
        finally:
            await session.close()
            self.save()

    async def cancellation_check(self, http):
        if self.args.echo or self.ledger.limit - len(self.ledger.calls) < 8:
            self.report["checks"].append({"id": "live_cancel_and_idempotent_retry", "status": "NOT_RUN", "details": {"reason": "echo or reserve below 8"}})
            return
        self.ledger.section = "live_disconnect_cancel_and_retry"
        game_id = (await http.post("/api/v1/games", json={"category": "mystery", "mode": "deduction",
            "player_role_id": "shen_zhiwei", "script_id": "fog_harbor_clocktower"})).raise_for_status().json()["id"]
        session = WireSession(http, self.url, game_id)
        await session.connect()
        request_id = str(uuid.uuid4())
        payload = {"content": "顾医生，请只说明最后一次见到陆先生的时间。这是一次断线恢复验收提问。"}
        try:
            await session.command("advance_phase", terminal={"private_script"})
            await session.command("advance_phase", terminal={"investigation_open"})
            count = len(self.ledger.calls)
            pending = asyncio.create_task(session.command("player_speech", payload, request_id=request_id))
            while len(self.ledger.calls) == count and not pending.done():
                await asyncio.sleep(0.02)
            await session.close()
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                attempts = self.app.state.store.list_agent_attempts(self.user_id, game_id)
                if attempts and all(item["status"] != "running" for item in attempts):
                    break
                await asyncio.sleep(0.1)
            attempts = self.app.state.store.list_agent_attempts(self.user_id, game_id)
            canceled = any(item["status"] == "canceled" for item in attempts)
            self.check("live_disconnection_canceled_audit", canceled, statuses=[item["status"] for item in attempts])
            committed = self.app.state.store.realtime_events_for_request(game_id, request_id)
            self.check("canceled_command_not_committed", canceled and not committed, committed_events=len(committed))
            await session.connect()
            await session.command("player_speech", payload, request_id=request_id)
            before_calls = len(self.ledger.calls)
            before_ids = [event["event_id"] for event in self.app.state.store.realtime_events_for_request(game_id, request_id)]
            await session.command("player_speech", payload, request_id=request_id)
            after_ids = [event["event_id"] for event in self.app.state.store.realtime_events_for_request(game_id, request_id)]
            self.check("completed_same_id_no_provider_repeat", before_calls == len(self.ledger.calls) and before_ids == after_ids)
            operations = self.app.state.store.list_role_activities(self.user_id, game_id)
            self.check("retried_human_action_committed_once", sum(op["actor_role_id"] == "shen_zhiwei" and op["event_type"] == "public_speech" for op in operations) == 1)
            (self.data / "cancellation-attempts.json").write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.check("live_cancel_check_error", False, error=str(exc).replace(self.settings.llm_api_key, "[REDACTED]"))
        finally:
            await session.close()

    async def memory_checks(self):
        if self.args.echo:
            return
        from backend.verification.memory_live_check import scenarios
        for effort in (None, "none"):
            self.ledger.section = "memory_provider_default" if effort is None else "memory_non_thinking_comparison"
            client = CountedDeepSeek(self.ledger, self.settings, effort=effort)
            for check_id, agent, context, answer, certainty, forbidden in scenarios(client):
                if len(self.ledger.calls) >= self.ledger.limit:
                    self.report["memory_checks"].append({"id": check_id, "mode": self.ledger.section, "status": "NOT_RUN", "reason": "request limit"})
                    continue
                response = ""
                try:
                    prepared = agent.prepare(context)
                    response = await agent.respond(context, prepared=prepared)
                    parsed = json.loads(response)
                    passed = parsed.get("answer") == answer and parsed.get("certainty") == certainty
                    boundary = all(marker not in json.dumps(prepared.messages(), ensure_ascii=False) and marker not in response for marker in forbidden)
                    boundary = boundary and "SYSTEM_CANARY_937" not in response
                    result = {"id": check_id, "mode": self.ledger.section, "status": "PASS" if passed and boundary else "FAIL",
                              "boundary_ok": boundary, "certainty_ok": parsed.get("certainty") == certainty, "response": response}
                except Exception as exc:
                    result = {"id": check_id, "mode": self.ledger.section, "status": "FAIL", "error": str(exc).replace(self.settings.llm_api_key, "[REDACTED]")}
                self.report["memory_checks"].append(result)
                self.save()
                print(json.dumps(result, ensure_ascii=False), flush=True)

    async def run(self):
        await self.start()
        try:
            async with httpx.AsyncClient(base_url=self.url, timeout=30) as http:
                registered = (await http.post("/api/v1/auth/register", json={"username": self.username, "password": self.password})).raise_for_status().json()
                self.user_id = registered["user"]["id"]
                http.headers["X-CSRF-Token"] = registered["csrf_token"]
                self.check("health_and_cookie_auth", (await http.get("/health")).json() == {"status": "ok"} and (await http.get("/api/v1/me")).status_code == 200)
                await self.full_game(http)
                await self.cancellation_check(http)
            await self.memory_checks()
            self.report["finished"] = True
            self.save()
            print(json.dumps({"event": "acceptance_finished", "report": str(self.args.report), "url": self.url,
                "requests": len(self.ledger.calls), "checks": dict(Counter(c["status"] for c in self.report["checks"]))}, ensure_ascii=False), flush=True)
            if self.args.hold_seconds:
                # Only completed games may be opened during this read-only inspection window.
                save_verification_account(self.data / "qa-access.json", {"username": self.username, "password": self.password})
                await asyncio.sleep(self.args.hold_seconds)
        finally:
            self.save()
            await self.stop()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--echo", action="store_true")
    parser.add_argument("--max-requests", type=int, default=100, choices=range(1, 101))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    if args.report.exists():
        parser.error("报告已存在；禁止覆盖旧付费结果或重置原额度。请使用新的验收批次路径。")
    acceptance = Acceptance(args)
    asyncio.run(acceptance.run())
    failed = any(c["status"] == "FAIL" for c in acceptance.report["checks"] + acceptance.report["memory_checks"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
