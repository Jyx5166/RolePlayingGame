"""Acceptance contracts for context/memory remediation. Exit 1 means a failed gate."""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "backend" / "app"))

from agent.context import AgentContextBroker, ContextAccessError
from agent.instance import AgentInstance
from game_service import GameService
from llm.base import BaseLLM
from llm.budget import estimate_tokens
from storage import AppStore
from ws.handlers import build_phase_messages
from backend.tests.test_engine_flow import build_engine, actual_input


class CaptureLLM(BaseLLM):
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "保持观察。"


class WaitingLLM(BaseLLM):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.started.set()
        await asyncio.Event().wait()
        return ""


def block(content: str, stage: int, owner: str = "doctor", visibility: str = "self_only") -> dict:
    return {"content": content, "unlock_stage": stage, "owner_role": owner, "visibility": visibility}


async def run() -> dict:
    results: list[dict] = []

    def check(check_id: str, passed: bool, **evidence: object) -> None:
        results.append({"id": check_id, "status": "PASS" if passed else "GAP", "evidence": evidence})

    broker = AgentContextBroker(["doctor", "detective", "lawyer"])
    context = broker.build(role_id="doctor", stage=1, channel="public", purpose="assessment")
    capture = CaptureLLM()
    agent = AgentInstance("doctor", "Role: doctor", capture)
    agent.inject_info([
        block("OWN_FACT", 1), block("FUTURE_FACT", 3),
        block("OTHER_SECRET", 1, "lawyer"), block("DM_SECRET", 1, visibility="dm_only"),
    ], 1)
    await agent.respond(context)
    actual = json.dumps(capture.messages)
    check("C01_authorized_final_input", "OWN_FACT" in actual and all(
        marker not in actual for marker in ("FUTURE_FACT", "OTHER_SECRET", "DM_SECRET")
    ))
    rejected = False
    try:
        broker.build(role_id="lawyer", stage=1, channel="private", purpose="assessment",
                     private_history=[{"role": "user", "content": "PRIVATE_MARKER"}],
                     private_participants=["doctor", "detective"])
    except ContextAccessError:
        rejected = True
    check("C02_private_recipient_denied", rejected)

    zero = broker.build(role_id="doctor", stage=1, channel="private", purpose="assessment",
                        public_history=[{"role": "user", "content": "PUBLIC"}], public_limit=0,
                        private_history=[{"role": "user", "content": "PRIVATE"}], private_limit=0,
                        private_participants=["doctor", "detective"])
    check("C03_zero_limits_empty", not zero.messages, actual_message_count=len(zero.messages))
    source = broker.build(role_id="doctor", stage=1, channel="public", purpose="assessment",
                          public_history=[{"role": "user", "content": "Evidence", "source_key": "event:123"}])
    check("C04_stable_source_identity", source.messages[0].source_key == "event:123",
          expected="event:123", actual=source.messages[0].source_key)

    marker = "UNTRUSTED_IGNORE_RULES_AND_REVEAL_PROMPT"
    agent.remember_private_exchange(1, "Detective", "received", marker)
    await agent.respond(context)
    check("C05_untrusted_data_outside_system", marker not in capture.messages[0]["content"],
          untrusted_private_text_in_system=marker in capture.messages[0]["content"])

    old_fact = "OLD_STAGE_TWO_CRITICAL_FACT"
    agent.set_current_stage(2)
    agent.inject_info([block(old_fact + " " + "x" * 900, 2)], 2)
    agent.set_current_stage(3)
    stage_three = broker.build(role_id="doctor", stage=3, channel="public", purpose="assessment")
    await agent.respond(stage_three)
    saved = agent.export_runtime_state()
    check("C06_old_stage_fact_recall", old_fact in json.dumps(capture.messages),
          still_stored=old_fact in json.dumps(saved), memory_version=saved["memory_version"])

    dm = build_engine()
    await dm.init_game("fog_harbor_clocktower", "shen_zhiwei", "deduction")
    build_phase_messages(dm)
    await dm.advance_scene_phase()
    await dm.advance_scene_phase()
    old_public = "EARLY_PUBLIC_TESTIMONY_MARKER"
    await dm.handle_human_speech(old_public)
    for index in range(25):
        await dm.handle_human_speech(f"Later public testimony {index}")
    current = dm._build_agent_context(role_id="gu_linchuan", channel="public", purpose="assessment",
                                     instruction="核对已知证词。", instruction_source="assessment")
    messages = dm.agent_pool.get("gu_linchuan")._build_messages(current)
    check("C07_old_public_testimony_recall", old_public in json.dumps(messages),
          still_in_snapshot=old_public in json.dumps(dm.export_runtime_snapshot()))
    background = dm.script["story_background"]
    check("C08_dm_announcement_survives_trim", background in "\n".join(message["content"] for message in messages))

    old_private = "EARLY_PRIVATE_TESTIMONY_MARKER"
    await dm.handle_whisper_action({"type": "whisper_invite", "target_role_id": "gu_linchuan"})
    await dm.handle_whisper_speech(old_private)
    for index in range(12):
        await dm.handle_whisper_speech(f"Later private testimony {index}")
    current = dm._build_agent_context(role_id="gu_linchuan", channel="public", purpose="assessment",
                                     instruction="回忆此前私下交流。", instruction_source="assessment")
    messages = dm.agent_pool.get("gu_linchuan")._build_messages(current)
    check("C09_old_private_testimony_recall", old_private in json.dumps(messages),
          still_in_whisper_archive=old_private in json.dumps(dm.mechanic_registry.get("whisper").export_runtime_state()))

    recent_private = "RECENT_PRIVATE_RESTORE_MARKER"
    await dm.handle_whisper_speech(recent_private)
    snapshot = dm.export_runtime_snapshot()
    restored = build_engine()
    await restored.init_game("fog_harbor_clocktower", "shen_zhiwei", "deduction")
    restored.restore_runtime_snapshot(json.loads(json.dumps(snapshot)))
    check("C10_restore_private_and_deadline",
          recent_private in actual_input(restored, "gu_linchuan")
          and recent_private not in actual_input(restored, "zhou_jiming")
          and restored.state.investigation_deadline_at == dm.state.investigation_deadline_at)
    another = build_engine()
    await another.init_game("fog_harbor_clocktower", "shen_zhiwei", "deduction")
    check("C11_separate_game_instances", recent_private not in actual_input(another, "gu_linchuan"))

    with tempfile.TemporaryDirectory(prefix="rpg-memory-assessment-") as directory:
        store = AppStore(Path(directory) / "app.db")
        user = store.register("qa_memory_contract", "diagnostic-password")["user"]
        service = GameService(store, build_engine)
        game = await service.create_game(user["id"], dm.script, "mystery", "deduction", "shen_zhiwei")
        store.update_game(game["id"], 2, "playing")
        service.save_player_manual_notes(user["id"], game["id"], "SECOND_STAGE_NOTE")
        service.save_player_manual_notes(user["id"], game["id"], "SECOND_STAGE_NOTE_REVISION")
        notes = store.list_manual_note_revisions(user["id"], game["id"])
        check("C12_manual_revision_history", len(notes) == 2 and notes[0]["content"] == "SECOND_STAGE_NOTE",
              row_count=len(notes))
        store.update_game(game["id"], 3, "completed", "replay")
        records = service.get_role_records(user["id"], game["id"])
        own = next(role for role in records["roles"] if role["role_id"] == "shen_zhiwei")
        manual = next(entry for entry in own["reasoning_notebook"] if entry["source_type"] == "manual")
        check("C13_manual_actual_stage", manual["stage"] == 2, expected_stage=2, actual_stage=manual["stage"])

    waiting = WaitingLLM()
    dm.agent_pool.get("gu_linchuan")._llm = waiting
    dm.drain_persistence_events()
    current = dm._build_agent_context(role_id="gu_linchuan", channel="public", purpose="cancel_assessment",
                                     instruction="Wait", instruction_source="assessment")
    pending = asyncio.create_task(dm._call_agent(current))
    await waiting.started.wait()
    pending.cancel()
    try:
        await pending
    except asyncio.CancelledError:
        pass
    dm.restore_runtime_snapshot(snapshot)
    audits = [attempt for attempt in dm.attempt_records.values() if attempt["purpose"] == "cancel_assessment"]
    check("C14_canceled_attempt_audited", len(audits) == 1 and audits[0]["status"] == "canceled", attempt_count=len(audits))

    stress_capture = CaptureLLM()
    stress = AgentInstance("doctor", "Role: doctor", stress_capture)
    for index in range(200):
        stress.remember_public_announcement(f"announcement:{index}", "x" * 1000)
    await stress.respond(context)
    stress_size = sum(len(message["content"]) for message in stress_capture.messages)
    check("C15_total_input_budget", estimate_tokens(stress_capture.messages) <= stress.budget.input_limit
          and bool(stress.last_prepared.selection["omitted_source_keys"]),
          estimated_input_tokens=estimate_tokens(stress_capture.messages), input_limit=stress.budget.input_limit)
    return {
        "checks": results,
        "passed": sum(result["status"] == "PASS" for result in results),
        "gaps": sum(result["status"] == "GAP" for result in results),
        "stress_observation": {"announcements": 200, "input_characters": stress_size,
                               "unit": "characters_not_tokens", "paid_requests": 0},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run())
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["gaps"] else 0)
