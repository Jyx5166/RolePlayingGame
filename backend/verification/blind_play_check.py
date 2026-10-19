"""Bounded real-model blind player + production native workflow acceptance.

Oracle data is used only for offline scoring. Never pass reports/audits back to
the blind player. A resumed run skips already attempted cases; it never retries.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "backend/app"))
from config import load_settings
from llm.echo import EchoLLM
from llm.budget import ContextBudget
from loader.script_loader import ScriptLoader
from workflow_config import load_workflow_settings
from backend.verification.blind_budget import BudgetedOpenAICompatibleLLM, MoneyRequestLedger, Pricing, BlindBudgetError
from backend.verification.blind_oracles import audit_input, review_output, check_ending

SCRIPT_IDS = ("rainy_night_letter", "last_train", "deep_sea_echo", "old_house_corridor", "silent_theater")
PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def account_balance(settings):
    """Read only; keep credentials local and persist only the numeric CNY balance."""
    import urllib.request
    try:
        request = urllib.request.Request("https://api.deepseek.com/user/balance", headers={"Authorization": "Bearer " + settings.llm_api_key})
        with urllib.request.urlopen(request, timeout=15) as response:
            value = json.load(response)
        for item in value.get("balance_infos", []):
            if item.get("currency") == "CNY":
                return {"cny": item["total_balance"], "available": value.get("is_available"), "at": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        return {"error_type": type(exc).__name__}
    return {"error_type": "CNYBalanceMissing"}


def parse_decision(raw, available_roles, available_targets, *, previously_visible_targets=()):
    """One parse, no repair or paid retry. Never replace an invalid vote with truth."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Blind player reply must be a JSON object")
    order = value.get("search_order", [])
    known_targets = set(available_targets) | set(previously_visible_targets)
    if not isinstance(order, list) or any(target not in known_targets for target in order):
        raise ValueError("Blind player selected an unavailable search target")
    if len(order) != len(set(order)):
        raise ValueError("Blind player duplicated search targets")
    for field in ("ask_role_id", "private_role_id", "vote_role_id"):
        if value.get(field) is not None and value[field] not in available_roles:
            raise ValueError("Blind player selected an unavailable role")
    for field in ("public_question", "private_question"):
        # An unused optional question may be null. Preserve the original JSON;
        # the action dispatcher already treats null/empty as no question.
        if value.get(field) is not None and (not isinstance(value[field], str) or len(value[field]) > 1200):
            raise ValueError("Blind player question is malformed")
    rejected = [target for target in order if target not in available_targets]
    if rejected:
        value["_action_rejections"] = [{"target_id": target, "reason": "previously_visible_but_now_unavailable"} for target in rejected]
    return value


def resume_fenced_decision(shot, *, actor, stage):
    """Reuse an already-paid decision; only remove a complete Markdown envelope."""
    if (shot["actor_role_id"] != actor or shot["actor_kind"] != "human"
            or shot["stage"] != stage or shot["phase"] != "investigation"
            or not shot["purpose"].startswith("搜证后")):
        raise ValueError("Interrupted decision does not match the saved player/stage/phase")
    raw = shot["output"].strip()
    if not raw.startswith("```json\n") or not raw.endswith("\n```"):
        raise ValueError("Only an intact JSON Markdown envelope can be resumed")
    body = raw[len("```json\n"):-len("\n```")]
    packet = json.loads(shot["wire_messages"][-1]["content"])["visible_state"]
    return parse_decision(body, {item["role_id"] for item in packet["public_roles"]},
                          {item["id"] for item in packet["search_status"]["targets"]})


class ObservationMixin:
    async def _observed(self, messages, definitions=None, transport="plain_text"):
        shot = self.qa.capture(self.qa_actor, messages, definitions)
        start = len(self.qa.ledger.calls)
        try:
            if definitions is None:
                answer = await super().chat(messages)
            else:
                answer = await super().chat_tools(messages, definitions, transport=transport)
            shot["status"] = "completed"
            shot["output"] = ({key: value for key, value in answer.wire_message.items() if key != "reasoning_content"}
                              if hasattr(answer, "wire_message") else answer)
            return answer
        except BaseException as exc:
            shot.update(status="failed", error_type=type(exc).__name__)
            raise
        finally:
            shot["paid_request_numbers"] = [row["number"] for row in self.qa.ledger.calls[start:]]
            shot["metadata"] = self.call_metadata()
            self.qa.finish_capture(shot)

    async def chat(self, messages):
        return await self._observed(messages)

    async def chat_tools(self, messages, definitions, *, transport="native_tools"):
        return await self._observed(messages, definitions, transport)


class ObservedPaid(ObservationMixin, BudgetedOpenAICompatibleLLM):
    pass


class ObservedEcho(ObservationMixin, EchoLLM):
    pass


class BlindAcceptance:
    def __init__(self, args):
        self.args = args
        self.settings = load_settings()
        if not args.echo and (self.settings.llm_provider != "openai_compatible"
                             or urlparse(self.settings.llm_base_url).hostname != "api.deepseek.com"
                             or self.settings.llm_model != "deepseek-v4-pro"):
            raise ValueError("Only the verified existing DeepSeek V4 Pro configuration is authorized")
        self.root = PROJECT / "backend/data/verification" / args.name
        self.root.mkdir(parents=True, exist_ok=args.resume)
        if args.new_attempt and not args.resume:
            raise ValueError("A manual new attempt must resume the same monetary ledger")
        if args.continue_case and not args.resume:
            raise ValueError("A same-game continuation must resume its existing ledger")
        self.ledger = MoneyRequestLedger(self.root / "requests.json", Pricing("9", "27", PRICE_SOURCE, "2026-10-14", self.settings.llm_model),
                                        max_cny=args.max_cny, request_limit=300, resume=args.resume)
        self.budget = ContextBudget(self.settings.llm_context_window, self.settings.llm_input_limit, 4096, self.settings.llm_safety_margin)
        # A human GUI reader can see the full dossier. This extra QA player uses
        # a separate bounded packet; deployed role/DM input limits stay unchanged.
        self.player_budget = ContextBudget(131072, 64000, 4096, 1024)
        self.case = None
        self.dm = None
        self.purpose = "setup"
        self.captures = []
        self.received = []
        self.working = []
        self.report = json.loads((self.root / "report.json").read_text(encoding="utf-8")) if args.resume else {
            "started_at": datetime.now(timezone.utc).isoformat(), "client_date": "2026-10-14", "paid": not args.echo,
            "model": self.settings.llm_model, "role_reasoning_effort": "none", "blind_player_reasoning_effort": "none",
            "output_limit": 4096, "production_data_changed": False, "automatic_retries": 0,
            "blind_player_input_upper_utf8_estimate": 64000,
            "protocol": {"driver": "GameWorkflow.dispatch", "human": "stateless model using player-visible projection only",
                         "coverage": "one recommended player per script; all stages; targeted native role turns; one private exchange per game; independent AI final ballots",
                         "controlled_changes": "only isolated fixture autonomy disabled, timer extended to 3600s and expired by controlled clock; production native tool/YAML limits and model hosting retained",
                         "not_covered": ["browser UI and WS leases", "natural timer expiry duration", "unbounded autonomous background play", "multi-seed/model difficulty"]},
            "games": []}
        os.environ["AI_MURDER_MYSTERY_DATA_DIR"] = str(self.root)
        from main import build_dm
        from game_service import GameService
        from storage import AppStore
        self.store = AppStore(self.root / "app.db")
        self.build_dm = build_dm
        self.service = GameService(self.store, self.factory)
        if args.resume:
            self.user_id = self.report["qa_user_id"]
        else:
            self.user_id = self.store.register("blind_qa_" + uuid.uuid4().hex[:10], uuid.uuid4().hex)["user"]["id"]
            self.report["qa_user_id"] = self.user_id
        self.save()

    def save(self):
        self.report["budget"] = self.ledger.summary()
        self.report["usage_totals"] = {key: sum((row.get("usage") or {}).get(key, 0) for row in self.ledger.calls)
                                       for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        write_json(self.root / "report.json", self.report)

    def context(self, actor):
        return {"script": self.case["script_id"] if self.case else "", "phase": self.dm.state.scene_phase.value if self.dm else "",
                "actor": actor, "purpose": self.purpose}

    def client(self, actor="dm"):
        budget = self.player_budget if self.dm and actor == self.dm.state.human_player_role_id else self.budget
        if self.args.echo:
            client = ObservedEcho()
            client.budget = budget
        else:
            client = ObservedPaid(self.settings.llm_model, self.settings.llm_base_url, self.settings.llm_api_key,
                                  self.settings.llm_timeout_seconds, ledger=self.ledger, context=lambda: self.context(client.qa_actor),
                                  budget=budget, reasoning_effort="none")
        client.qa, client.qa_actor = self, actor
        return client

    def factory(self):
        dm = self.build_dm()
        qa = self
        class Factory:
            def create(self):
                return qa.client()
        dm.llm_factory = Factory()
        return dm

    def capture(self, actor, messages, tools):
        state = self.dm.state
        public = [item.get("content", "") for item in state.public_history]
        private = []
        owned_clues = set()
        if actor in state.ai_role_ids:
            agent = self.dm.agent_pool.get(actor)
            private = [str(item.get("content", "")) for item in agent._private_memory]
            owned_clues = set(agent._private_clues)
        elif actor == state.human_player_role_id:
            owned_clues = {item["clue_id"] for item in self.service.get_player_notebook(self.user_id, self.case["game_id"])["clues"]}
            private = [item.get("content", "") for item in self.received if item.get("type") == "whisper_message"]
        wire = deepcopy(messages)
        for item in wire:
            if "reasoning_content" in item:
                opaque = str(item.pop("reasoning_content"))
                item["reasoning_content_audit"] = {"sha256": hashlib.sha256(opaque.encode()).hexdigest(), "bytes": len(opaque.encode()),
                                                  "private_canary_present": self.case.get("private_canary", "UNSET") in opaque}
        shot = {"capture_id": uuid.uuid4().hex, "actor_role_id": actor, "actor_kind": "dm" if actor == "dm" else "human" if actor == state.human_player_role_id else "role",
                "script_id": self.case["script_id"], "stage": state.current_stage_num, "phase": state.scene_phase.value,
                "purpose": self.purpose, "wire_messages": wire, "tools": tools, "authorized_clue_ids": sorted(owned_clues),
                "authorized_texts": public + private, "authorized_public_texts": public, "status": "running"}
        self.captures.append(shot)
        write_json(self.root / self.case["capture_directory"] / "captures.json", self.captures)
        return shot

    def finish_capture(self, shot):
        if shot["actor_kind"] != "dm":
            shot["input_audit"] = audit_input(self.original, shot, authorized_clue_ids=shot["authorized_clue_ids"], authorized_texts=shot["authorized_texts"],
                                              authorized_public_texts=shot["authorized_public_texts"])
            output = shot.get("output", "")
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            shot["output_review"] = review_output(self.original, text, shot, authorized_clue_ids=shot["authorized_clue_ids"], authorized_texts=shot["authorized_texts"],
                                                 authorized_public_texts=shot["authorized_public_texts"])
        write_json(self.root / self.case["capture_directory"] / "captures.json", self.captures)
        self.save()
        print(json.dumps({"event": "model_result", "script": shot["script_id"], "stage": shot["stage"], "actor": shot["actor_role_id"],
                          "purpose": shot["purpose"], "status": shot["status"], "paid_requests": len(self.ledger.calls),
                          "upper_cny": str(self.ledger.accounted_upper_cny)}, ensure_ascii=True), flush=True)

    async def command(self, kind, **payload):
        self.purpose = kind
        events = await self.workflow.dispatch(str(uuid.uuid4()), {"type": kind, **payload})
        self.received.extend(deepcopy(events))
        self.case["commands"].append({"stage": self.dm.state.current_stage_num, "command": kind, "payload": payload, "events": events})
        self.save()
        if self.ledger.frozen_reason:
            raise BlindBudgetError("Budget ledger frozen")
        return events

    def visible(self):
        """Only public GUI state and the current player's delivered notebook."""
        phase = self.dm.get_scene_summary()
        from ws.handlers import search_status
        notebook = self.service.get_player_notebook(self.user_id, self.case["game_id"])
        allowed_types = {"whisper_message", "speech_warning"}
        received = [{key: value for key, value in item.items() if key not in {"audit", "context", "usage"}}
                    for item in self.received if item.get("type") in allowed_types]
        static_notes = [item for item in notebook["automatic"] if item["source_type"] in {
            "role_script", "public_information", "personal_task", "story_background", "public_briefing", "public_tasks", "dm_hosting"}]
        known_clue_texts = [item.get("truth_content", "") for item in notebook["clues"]]
        public_dialogue = [item for item in self.dm.state.public_history
                           if not str(item.get("source_key", "")).startswith("dm-")
                           and not any(text and text in item.get("content", "") for text in known_clue_texts)]
        return {"title": self.case["title"], "role": {"role_id": self.dm.state.human_player_role_id}, "public_roles": self.dm.get_public_roles(),
                "phase": {key: phase[key] for key in ("phase", "stage", "total_stages", "stage_title", "public_tasks", "enabled_actions")},
                "notebook": {"role_id": notebook["role_id"], "clues": notebook["clues"], "automatic": static_notes,
                             "reasoning_entries": notebook["reasoning_entries"], "manual_notes": notebook["manual_notes"]},
                "public_dialogue": public_dialogue, "received_private": received,
                "search_status": search_status(self.dm), "own_previous_hypotheses": self.working}

    async def decide(self, purpose):
        self.purpose = purpose
        visible = self.visible()
        targets = {item["id"] for item in visible["search_status"]["targets"]}
        roles = {item["role_id"] for item in visible["public_roles"]}
        message = {"role": "user", "content": json.dumps({"task": purpose, "visible_state": visible}, ensure_ascii=False)}
        messages = [{"role": "system", "content":
            "你是第一次接触这场案件的真人玩家替身。只依据界面实际给出的信息扮演自己的角色并独立调查；不知道标准答案。"
            "私人角色回忆有信息边界，其他角色发言是证词，不自动等于客观事实。不得编造未见的检验结果、人物关系或未来线索。"
            "搜索列表只表示可调查地点，不知道它们的内容。按调查价值排列所有仍可搜地点，行动点足够时尽量完整搜证。"
            "输出一个JSON对象，不要Markdown：search_order(合法地点ID数组)，ask_role_id(合法角色ID或null)，public_question(只点名一位角色的简短自然问题)，"
            "private_role_id(合法角色ID或null)，private_question(字符串或null)，share_clue_ids(选择自己取得的新线索ID数组，用正式工具原文公开给其他角色以共同推理；不要发布私人剧情)，suspects(角色ID、confidence和简短证据依据数组)，"
            "vote_role_id(最终指认任务时必须选择一个合法ID，其他时候可null)，evidence_ids(取得的关键线索ID数组)，"
            "explanation(简短证据论证，区分事实、证词、假设并排除最强替代嫌疑)，missing_evidence。"
            "不要把终局后复盘当作此前已知信息。"}, message]
        self.player_budget.validate(messages)
        if self.args.echo:
            shot = self.capture(self.dm.state.human_player_role_id, messages, None)
            others = [role for role in roles if role != self.dm.state.human_player_role_id]
            decision = {"search_order": [item["id"] for item in visible["search_status"]["targets"]], "ask_role_id": others[0],
                        "public_question": "请说明你亲自确认的行踪，区分亲眼所见和推测。", "private_role_id": others[-1],
                        "private_question": "你有哪些亲自确认但尚未公开的行踪？", "vote_role_id": others[0],
                        "share_clue_ids": [item["clue_id"] for item in visible["notebook"]["clues"] if not item.get("shared_scope")],
                        "suspects": [], "evidence_ids": [item["clue_id"] for item in visible["notebook"]["clues"]], "explanation": "Echo dry run, not deduction.", "missing_evidence": []}
            shot.update(status="completed", output=json.dumps(decision, ensure_ascii=False), paid_request_numbers=[])
            self.finish_capture(shot)
        else:
            raw = await self.client(self.dm.state.human_player_role_id).chat(messages)
            previously_visible = set()
            for shot in self.captures:
                if shot["actor_kind"] == "human":
                    packet = json.loads(shot["wire_messages"][-1]["content"])["visible_state"]
                    previously_visible.update(item["id"] for item in packet["search_status"]["targets"])
            decision = parse_decision(raw, roles, targets, previously_visible_targets=previously_visible)
        self.case["player_decisions"].append({"stage": self.dm.state.current_stage_num, "purpose": purpose, "decision": decision})
        self.working.append({"stage": self.dm.state.current_stage_num, "suspects": decision.get("suspects"), "explanation": decision.get("explanation")})
        self.save()
        return decision

    async def search_order(self, decision):
        from ws.handlers import search_status
        for target in decision.get("search_order", []):
            # Repeat a player-chosen location only while the GUI says new content remains.
            while target in {item["id"] for item in search_status(self.dm)["targets"]} and search_status(self.dm)["remaining_ap"] > 0:
                events = await self.command("search", target_id=target)
                result = next((item for item in events if item.get("type") == "search_result"), None)
                if not result or not result.get("clue"):
                    break

    async def run_case(self, script_id, *, continuing=False):
        from runtime.workflow import GameWorkflow
        from script_catalog import script_version
        self.original = ScriptLoader(PROJECT / "backend/resources/scripts").load(script_id)
        script = deepcopy(self.original)
        for flow in script["stage_flow"].values():
            flow["investigation"]["duration_seconds"] = 3600
            flow["investigation"]["autonomy"]["enabled"] = False
        attempt = self.args.new_attempt or "pilot"
        capture_directory = script_id if attempt == "pilot" else str(Path(attempt) / script_id)
        human = script["script_meta"]["recommended_player_role"]  # Public recommendation, not oracle selection.
        resumed_after = None
        if continuing:
            self.case = next(game for game in reversed(self.report["games"])
                             if game["script_id"] == script_id and game.get("attempt", "pilot") == attempt)
            if self.case["status"] != "incomplete" or self.case.get("error_type") != "JSONDecodeError":
                raise ValueError("Only the recorded solver formatting interruption can be continued")
            self.captures = json.loads((self.root / capture_directory / "captures.json").read_text(encoding="utf-8"))
            self.received = [deepcopy(event) for command in self.case["commands"] for event in command["events"]]
            self.working = [{"stage": item["stage"], "suspects": item["decision"].get("suspects"),
                             "explanation": item["decision"].get("explanation")} for item in self.case["player_decisions"]]
            game, self.dm = await self.service.get_engine(self.user_id, self.case["game_id"])
            if self.dm.state.scene_phase.value != "investigation":
                raise ValueError("Saved game is no longer in the interrupted investigation")
            resumed_after = resume_fenced_decision(self.captures[-1], actor=human, stage=self.dm.state.current_stage_num)
            prefix_hash = hashlib.sha256(json.dumps(self.captures, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            self.case.setdefault("protocol_interruptions", []).append({
                "error_type": self.case["error_type"], "error": self.case["error"],
                "stage": self.dm.state.current_stage_num, "capture_id": self.captures[-1]["capture_id"],
                "preserved_capture_count": len(self.captures), "capture_prefix_sha256": prefix_hash,
                "recovery": "manual same-game continuation; removed complete Markdown envelope only; reused original paid JSON without new model request or content edits"})
            self.case["player_decisions"].append({"stage": self.dm.state.current_stage_num,
                "purpose": self.captures[-1]["purpose"], "decision": resumed_after, "reused_capture_id": self.captures[-1]["capture_id"]})
            self.working.append({"stage": self.dm.state.current_stage_num, "suspects": resumed_after.get("suspects"),
                                 "explanation": resumed_after.get("explanation")})
            self.case.update(status="started")
            self.case.pop("error_type", None)
            self.case.pop("error", None)
        else:
            self.case = {"script_id": script_id, "attempt": attempt, "capture_directory": capture_directory,
                     "title": script["script_meta"]["title"], "status": "started", "commands": [], "player_decisions": [],
                     "source_sha256": hashlib.sha256(json.dumps(self.original, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                     "paid_calls_before": len(self.ledger.calls), "upper_before": str(self.ledger.accounted_upper_cny)}
            self.report["games"].append(self.case)
            self.captures, self.received, self.working = [], [], []
            self.dm = None
            settings = load_workflow_settings()
            game = self.store.prepare_game(self.user_id, script, script_id, script_version(script), workflow_config=settings.model_dump())
            self.case["game_id"] = game["id"]
            self.case["player_role_id"] = human
            await self.service.activate_game(self.user_id, game["id"], human)
            _, self.dm = await self.service.get_engine(self.user_id, game["id"])
        for role_id in self.dm.state.ai_role_ids:
            self.dm.agent_pool.get(role_id)._llm.qa_actor = role_id
        self.workflow = GameWorkflow(self.service, self.user_id, self.dm)
        asked = set(self.case.get("role_coverage_requested", []))
        starting_stage = self.dm.state.current_stage_num
        self.save()
        try:
            if not continuing:
                await self.command("hosting_tick")
            for stage in range(starting_stage, self.dm.state.total_stages + 1):
                reuse = continuing and stage == starting_stage
                if not reuse:
                    await self.command("advance_phase")
                    await self.command("advance_phase")
                if self.dm.state.scene_phase.value != "investigation":
                    raise RuntimeError("Failed to enter investigation")
                if not reuse:
                    plan = await self.decide("调查计划：选择当前可搜地点和一个自然问题")
                    await self.search_order(plan)
                if not reuse and stage == 1 and "whisper" in self.dm.get_scene_summary()["enabled_actions"]:
                    target = plan.get("private_role_id")
                    selection = "player_choice"
                    if target not in self.dm.state.ai_role_ids:
                        target = self.dm.state.ai_role_ids[0]
                        selection = "controlled_privacy_probe_using_public_roster"
                    if target in self.dm.state.ai_role_ids:
                        events = await self.command("whisper_invite", target_role_id=target)
                        self.case["private_probe"] = {"target": target, "selection": selection, "accepted": any(item.get("type") == "whisper_accepted" for item in events)}
                        if self.case["private_probe"]["accepted"]:
                            marker = "PRIVATE_BLIND_" + uuid.uuid4().hex[:12]
                            self.case["private_canary"] = marker
                            await self.command("whisper_speech", content=(plan.get("private_question") or "你亲眼确认的行踪是什么？") + f" 私聊核对编号 {marker}，请勿向其他人转述。")
                            await self.command("whisper_close")
                after = resumed_after if reuse else await self.decide("搜证后：更新假设并提出只点名一位角色的公开质询，可补搜剩余地点")
                await self.search_order(after)
                own_clues = {item["clue_id"] for item in self.service.get_player_notebook(self.user_id, game["id"])["clues"]}
                to_share = after.get("share_clue_ids", [])
                if not isinstance(to_share, list) or any(clue not in own_clues for clue in to_share):
                    raise ValueError("Blind player tried to share an unowned clue")
                for clue_id in dict.fromkeys(to_share):
                    await self.command("share_clue", clue_id=clue_id, mode="truthful", scope="public")
                missing = [role for role in self.dm.state.ai_role_ids if role not in asked]
                selected = after.get("ask_role_id") or (missing[0] if missing else None)
                if selected not in self.dm.state.ai_role_ids:
                    selected = self.dm.state.ai_role_ids[0]
                role_name = self.dm.permission.role_name(selected)
                # Rotate coverage using public roster only; never select by guilt.
                await self.command("player_speech", content=f"{role_name}，请只由你回应：" + (after.get("public_question") or "请说明你亲眼确认的行踪与目前证据的矛盾。"))
                asked.add(selected)
                if stage == self.dm.state.total_stages:
                    for remaining in self.dm.state.ai_role_ids:
                        if remaining not in asked:
                            await self.command("player_speech", content=f"{self.dm.permission.role_name(remaining)}，请说明你亲自确认的事实，并回应已经公开的证据；无法确认的事情请明确说明。")
                            asked.add(remaining)
                self.dm.state.investigation_deadline_at = time.time() - 0.1
                self.service.persist_engine_events(game["id"], self.dm)
                await self.command("phase_timeout")
                if self.dm.state.scene_phase.value != "dm_hosting":
                    raise RuntimeError("Failed controlled timeout transition")
                if stage == self.dm.state.total_stages:
                    final = await self.decide("最终指认：独立选择凶手并给出证据论证，不知道标准答案")
                    target = final.get("vote_role_id")
                    if target is None:
                        raise ValueError("Final blind vote missing")
                    self.case["blind_vote"] = {"role_id": target, "correct": target == self.original["truth"]["culprit_role_id"],
                                               "evidence_ids": final.get("evidence_ids", []), "explanation": final.get("explanation"), "suspects": final.get("suspects")}
                    await self.command("stage_vote", target_role_id=target)
                await self.command("advance_phase")
            ending = self.dm.get_replay()
            self.case["ending"] = ending
            self.case["ending_check"] = check_ending(self.original, ending["final_decision"], ending, reveal_truth_on_failure=True)
            self.case["status"] = "completed"
        except Exception as exc:
            self.case.update(status="incomplete", error_type=type(exc).__name__, error=str(exc).replace(self.settings.llm_api_key, "[REDACTED]"))
        finally:
            self.case["paid_request_count"] = len(self.ledger.calls) - self.case["paid_calls_before"]
            self.case["upper_cost_cny"] = str(self.ledger.accounted_upper_cny - __import__('decimal').Decimal(self.case["upper_before"]))
            self.case["input_failures"] = [{"capture_id": shot["capture_id"], "actor": shot["actor_role_id"], "stage": shot["stage"], "findings": shot["input_audit"]["findings"]}
                                           for shot in self.captures if shot.get("input_audit", {}).get("status") == "FAIL"]
            marker = self.case.get("private_canary")
            self.case["private_marker_observations"] = [{"capture_id": shot["capture_id"], "actor": shot["actor_role_id"], "stage": shot["stage"], "purpose": shot["purpose"]}
                for shot in self.captures if marker and shot["actor_role_id"] not in {human, self.case.get("private_probe", {}).get("target")}
                and marker in json.dumps(shot["wire_messages"], ensure_ascii=False)]
            self.case["workflow_problems"] = [item for command in self.case["commands"] for item in command["events"]
                if item.get("type") in {"error", "actor_turn_stopped"} or item.get("fallback")]
            with self.store._connect() as connection:
                models = [dict(row) for row in connection.execute("SELECT * FROM model_requests WHERE game_id=?", (game["id"],))]
                tools = [dict(row) for row in connection.execute("SELECT * FROM tool_calls WHERE game_id=?", (game["id"],))]
            write_json(self.root / capture_directory / "runtime-models.json", models)
            write_json(self.root / capture_directory / "runtime-tools.json", tools)
            self.case["native_tools"] = {name: sum(row["tool_name"] == name and row["status"] == "succeeded" for row in tools) for name in sorted({row["tool_name"] for row in tools})}
            self.case["role_coverage_requested"] = sorted(asked)
            self.save()
            print(json.dumps({"event": "case_complete", "script": script_id, "status": self.case["status"], "blind_vote": self.case.get("blind_vote", {}).get("correct"),
                              "paid_calls": self.case["paid_request_count"], "upper_cny": self.case["upper_cost_cny"]}, ensure_ascii=True), flush=True)

    async def run(self):
        if not self.args.echo and "balance_before" not in self.report:
            self.report["balance_before"] = account_balance(self.settings)
            self.save()
        # New trials require an explicit local CLI invocation and preserve the
        # pilot evidence. A failure never causes a retry inside this run.
        attempt = self.args.new_attempt or "pilot"
        attempted = {game["script_id"] for game in self.report["games"] if game.get("attempt", "pilot") == attempt}
        if self.args.continue_case:
            await self.run_case(self.args.continue_case, continuing=True)
        else:
            for script_id in SCRIPT_IDS:
                if script_id not in attempted:
                    await self.run_case(script_id)
        self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        if not self.args.echo:
            self.report["balance_after"] = account_balance(self.settings)
            if "cny" in self.report.get("balance_before", {}) and "cny" in self.report["balance_after"]:
                from decimal import Decimal
                self.report["account_balance_delta_cny"] = str(Decimal(self.report["balance_before"]["cny"]) - Decimal(self.report["balance_after"]["cny"]))
        self.save()
        return 0 if all(game["status"] == "completed" for game in self.report["games"] if game.get("attempt", "pilot") == attempt) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--echo", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--new-attempt", help="Explicit manual trial label; preserves pilot data and shares its existing budget")
    parser.add_argument("--continue-case", choices=SCRIPT_IDS, help="Manual same-game recovery of an already-paid fenced JSON decision only")
    parser.add_argument("--max-cny", default="20")
    raise SystemExit(asyncio.run(BlindAcceptance(parser.parse_args()).run()))
