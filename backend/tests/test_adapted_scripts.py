"""Content, upload, privacy and complete Echo playthroughs for the adapted cases."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from agent.pool import AgentPool
from dm.engine import DMEngine, GamePhase, ScenePhase
from dm.permission import PermissionMatrix
from dm.validator import SpeechValidator
from game_service import GameService
from llm.echo import EchoLLM
from llm.factory import LLMFactory
from loader.script_loader import ScriptLoader
from registry.mechanic_registry import MechanicRegistry
from registry.skill_registry import SkillRegistry
from skill.deduction import DeductionSkill
from storage import AppStore


CASES = {
    "floorboard_echo": (3, 2),
    "white_tower_guest": (4, 3),
    "moonstone_transfer": (5, 3),
}
FLOW_REPORTS: list[dict] = []


class BallotEcho(EchoLLM):
    """Scripted valid ballots exercise endings; all other calls use real Echo."""

    def __init__(self, choice: str) -> None:
        self.choice = choice

    async def chat(self, messages: list[dict[str, str]]) -> str:
        latest = messages[-1]["content"] if messages else ""
        if "[STAGE_VOTE]" in latest:
            candidates = [
                line.split("=", 1)[1].split("；", 1)[0].strip()
                for line in latest.splitlines() if line.startswith("- role_id=")
            ]
            # An AI cannot vote for itself. Its one dissenting vote leaves a
            # majority for the requested fixture outcome with these 3-5 roles.
            return self.choice if self.choice in candidates else candidates[0]
        return await super().chat(messages)


class BallotEchoFactory:
    def __init__(self, choice: str) -> None:
        self.choice = choice

    def create(self) -> BallotEcho:
        return BallotEcho(self.choice)


def build_engine(choice: str | None = None) -> DMEngine:
    skills = SkillRegistry()
    skills.register(DeductionSkill)
    return DMEngine(
        ScriptLoader(BACKEND_ROOT / "resources" / "scripts"),
        AgentPool(),
        LLMFactory({"provider": "echo"}) if choice is None else BallotEchoFactory(choice),
        MechanicRegistry(),
        skills,
    )


def agent_input(dm: DMEngine, role_id: str) -> str:
    context = dm._build_agent_context(
        role_id=role_id, channel="public", purpose="adapted_case_test",
        instruction="仅使用已解锁信息核对时间线。", instruction_source="test",
    )
    prepared = dm.agent_pool.get(role_id).prepare(context)
    return json.dumps(prepared.messages(), ensure_ascii=False)


class AdaptedContentTest(unittest.TestCase):
    def test_loader_evidence_references_and_stage_budgets(self) -> None:
        loader = ScriptLoader(BACKEND_ROOT / "resources" / "scripts")
        for script_id, (role_count, stage_count) in CASES.items():
            with self.subTest(script=script_id):
                script = loader.load(script_id)
                self.assertEqual(script["script_meta"]["total_stages"], stage_count)
                self.assertEqual(len(script["roles"]), role_count)
                role_ids = {role["role_id"] for role in script["roles"]}
                culprit = script["truth"]["culprit_role_id"]
                self.assertTrue(all(role["human_playable"] for role in script["roles"]))
                self.assertEqual(set(script["truth"]["innocent_explanations"]), role_ids - {culprit})
                self.assertIn("你知道自己", PermissionMatrix(script).visible_text(culprit, 1))
                source = script["script_meta"]["adaptation_source"]
                self.assertTrue(source["catalog_url"].startswith("https://www.gutenberg.org/ebooks/"))
                self.assertLessEqual(source["author_death_year"], 1930)

                search = script["mechanics_config"]["search"]
                clues = {clue["id"]: clue for target in search["search_targets"] for clue in target["clues"]}
                critical = set()
                for chain in script["truth"]["evidence_chain"]:
                    self.assertTrue(chain["inference"])
                    critical.update(chain["clue_ids"])
                for explanation in script["truth"]["innocent_explanations"].values():
                    critical.update(explanation["clue_ids"])
                    self.assertTrue(explanation["explanation"])
                self.assertTrue(critical.issubset(clues))
                self.assertTrue(all(clues[clue_id]["exclusivity"] == "shared" for clue_id in critical))

                block_ids = []
                for role in script["roles"]:
                    for stage in range(1, stage_count + 1):
                        for block in role["stage_knowledge"][f"stage_{stage}"]["blocks"]:
                            block_ids.append(block["block_id"])
                            self.assertEqual(block["owner_role"], role["role_id"])
                            self.assertEqual(block["unlock_stage"], stage)
                            self.assertEqual(block["visibility"], "self_only")
                            self.assertTrue(SpeechValidator(script).validate_ai_speech(role["role_id"], stage, block["content"]).passed)
                self.assertEqual(len(block_ids), len(set(block_ids)))
                for stage in range(1, stage_count + 1):
                    newly_available = sum(len(target["clues"]) for target in search["search_targets"] if target["unlock_stage"] == stage)
                    # A single human can still collect every newly unlocked
                    # clue even if selected for the preceding AP penalty.
                    self.assertGreaterEqual(search["ap_per_stage"][stage - 1] - int(stage > 1), newly_available)
                    flow = script["stage_flow"][f"stage_{stage}"]
                    self.assertEqual(set(flow["personal_tasks"]), role_ids)
                    self.assertFalse(flow["investigation"]["end_conditions"]["auto_end"])
                    for checks in flow["personal_task_checks"].values():
                        for check in checks:
                            if "clue_id" in check:
                                self.assertIn(check["clue_id"], clues)


class AdaptedFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_uploaded_cases_create_persist_and_restore(self) -> None:
        with tempfile.TemporaryDirectory(prefix="adapted-case-upload-") as directory:
            store = AppStore(Path(directory) / "test.db")
            user = store.register("case_tester", "local-test-password")
            service = GameService(store, build_engine)
            for script_id, (role_count, stage_count) in CASES.items():
                with self.subTest(script=script_id):
                    script = build_engine().script_loader.load(script_id)
                    role_id = script["roles"][0]["role_id"]
                    preview = service.inspect_script(script, "deduction")
                    self.assertEqual(preview["role_count"], role_count)
                    self.assertEqual(preview["total_stages"], stage_count)
                    self.assertNotIn("truth", preview)
                    self.assertNotIn("stage_knowledge", json.dumps(preview))
                    game = await service.create_game(user["user"]["id"], script, "mystery", "deduction", role_id)
                    _, dm = await service.get_engine(user["user"]["id"], game["id"])
                    await dm.advance_scene_phase()
                    await dm.advance_scene_phase()
                    target = script["mechanics_config"]["search"]["search_targets"][0]
                    found = await dm.handle_mechanic_action({"type": "search", "target_id": target["id"]})
                    service.persist_engine_events(game["id"], dm)
                    service.sessions.clear()
                    _, restored = await service.get_engine(user["user"]["id"], game["id"])
                    self.assertEqual(restored.state.scene_phase, ScenePhase.INVESTIGATION)
                    self.assertEqual(restored.get_human_clues()[0]["clue_id"], found["clue"]["id"])
                    self.assertEqual(restored.get_orchestration_summary()["total_roles"], role_count)
                    self.assertEqual(restored.get_private_assignment()["role_id"], role_id)

    async def test_every_playable_role_completes_all_stages_with_default_echo(self) -> None:
        for script_id in CASES:
            script = build_engine().script_loader.load(script_id)
            for role in script["roles"]:
                with self.subTest(script=script_id, human=role["role_id"]):
                    await self.play_case(script_id, role["role_id"])

    async def test_all_cases_publish_correct_endings(self) -> None:
        for script_id in CASES:
            script = build_engine().script_loader.load(script_id)
            with self.subTest(script=script_id):
                await self.play_case(script_id, script["roles"][0]["role_id"], script["truth"]["culprit_role_id"], True)

    async def test_all_cases_publish_incorrect_endings_without_truth_in_replay(self) -> None:
        for script_id in CASES:
            script = build_engine().script_loader.load(script_id)
            wrong_id = next(role["role_id"] for role in script["roles"][1:] if role["role_id"] != script["truth"]["culprit_role_id"])
            with self.subTest(script=script_id):
                await self.play_case(script_id, script["roles"][0]["role_id"], wrong_id, False)

    async def play_case(self, script_id: str, human_id: str, choice: str | None = None, expected_correct: bool | None = None) -> None:
        dm = build_engine(choice)
        state = await dm.init_game(script_id, human_id, "deduction")
        script = dm.script
        role_count, total_stages = CASES[script_id]
        self.assertEqual(len(state.ai_role_ids), role_count - 1)
        targets = script["mechanics_config"]["search"]["search_targets"]
        acquired = set()
        stage_reports = []

        for stage in range(1, total_stages + 1):
            self.assertEqual(state.current_stage_num, stage)
            self.assertEqual(state.scene_phase, ScenePhase.BRIEFING)
            self.assertNotIn(script["truth"]["full_story"], dm.get_briefing_narration())
            await dm.advance_scene_phase()
            assignment = dm.get_private_assignment()
            own = next(role for role in script["roles"] if role["role_id"] == human_id)
            self.assertEqual(assignment["blocks"], own["stage_knowledge"][f"stage_{stage}"]["blocks"])
            await dm.advance_scene_phase()
            self.assertEqual(state.scene_phase, ScenePhase.INVESTIGATION)

            # Inspect the actual prepared input, not only PermissionMatrix.
            for observer in state.ai_role_ids:
                actual = agent_input(dm, observer)
                for role in script["roles"]:
                    for unlock_stage in range(1, total_stages + 1):
                        for block in role["stage_knowledge"][f"stage_{unlock_stage}"]["blocks"]:
                            if unlock_stage > stage or role["role_id"] != observer:
                                self.assertNotIn(block["content"], actual)
                self.assertNotIn(script["truth"]["full_story"], actual)

            search = dm.mechanic_registry.get("search")
            for target in targets:
                if target["unlock_stage"] > stage:
                    before = search.remaining_ap(stage, human_id)
                    locked = await dm.handle_mechanic_action({"type": "search", "target_id": target["id"]})
                    self.assertIsNone(locked["clue"])
                    self.assertEqual(search.remaining_ap(stage, human_id), before)
                    self.assertNotIn(target["clues"][0]["content"], agent_input(dm, state.ai_role_ids[0]))

            stage_clues = []
            for target in targets:
                if target["unlock_stage"] != stage:
                    continue
                found = await dm.handle_mechanic_action({"type": "search", "target_id": target["id"]})
                self.assertIsNotNone(found["clue"], target["id"])
                clue = found["clue"]
                self.assertNotIn(clue["content"], agent_input(dm, state.ai_role_ids[0]))
                acquired.add(clue["id"])
                stage_clues.append(clue)

            first = stage_clues[0]
            counterpart, third_party = state.ai_role_ids[:2]
            actions = dm.get_scene_summary()["enabled_actions"]
            if "whisper" in actions:
                invite = await dm.handle_whisper_action({"type": "whisper_invite", "target_role_id": counterpart})
                self.assertEqual(invite["type"], "whisper_accepted")
                marker = f"PRIVATE_CASE_NOTE_{script_id}_{human_id}_{stage}"
                private = await dm.handle_whisper_speech(marker)
                self.assertEqual(len(private), 2)
                dm.handle_clue_disclosure({"clue_id": first["id"], "mode": "truthful", "scope": "private", "target_role_id": counterpart})
                self.assertIn(marker, agent_input(dm, counterpart))
                self.assertNotIn(marker, agent_input(dm, third_party))
                self.assertNotIn(first["content"], agent_input(dm, third_party))
                self.assertNotIn(marker, json.dumps(state.public_history, ensure_ascii=False))
                await dm.handle_whisper_action({"type": "whisper_close"})
            else:
                with self.assertRaises(ValueError):
                    await dm.handle_whisper_action({"type": "whisper_invite", "target_role_id": counterpart})

            for clue in stage_clues:
                dm.handle_clue_disclosure({"clue_id": clue["id"], "mode": "truthful", "scope": "public"})
            self.assertIn(first["content"], agent_input(dm, third_party))
            public = await dm.handle_human_speech("请核对本幕已公开的时间记录，并区分亲眼所见与推断。")
            self.assertTrue(await dm.schedule_ai_turns(public))
            state.autonomy_next_at = time.time() - 1
            self.assertTrue(await dm.run_autonomous_turn())

            self.assertFalse(dm.investigation_should_end())
            end_vote = await dm.request_investigation_end_vote()
            self.assertTrue(end_vote["approved"])
            self.assertEqual(end_vote["required_votes"], role_count // 2 + 1)
            dm.end_investigation("vote_majority")
            self.assertEqual(state.scene_phase, ScenePhase.DM_HOSTING)
            self.assertNotIn(script["truth"]["full_story"], dm.get_hosting_narration())
            with self.assertRaises(ValueError):
                await dm.advance_scene_phase()
            result = await dm.cast_stage_vote(choice or script["truth"]["culprit_role_id"])
            own_result = next(item for item in result["role_results"] if item["role_id"] == human_id)
            self.assertEqual(own_result["task_results"][0]["status"], "manual_review")
            self.assertTrue(all(item["status"] == "completed" for item in own_result["task_results"][1:]))
            stage_reports.append({"stage": stage, "acquired_clue_ids": [clue["id"] for clue in stage_clues],
                                  "private_chat_enabled": "whisper" in actions,
                                  "required_end_votes": end_vote["required_votes"],
                                  "selected_role_id": result["vote"]["selected_role_id"]})
            transition = await dm.advance_scene_phase()
            if stage < total_stages:
                self.assertTrue(transition["stage_advanced"])
                self.assertIsNone(transition["replay"])
            else:
                replay = transition["replay"]
                correct = result["vote"]["correct"]
                if expected_correct is not None:
                    self.assertEqual(correct, expected_correct)
                self.assertEqual(replay["truth_revealed"], correct)
                if correct:
                    self.assertEqual(replay["full_story"], script["truth"]["full_story"])
                    self.assertEqual(replay["timeline"], script["truth"]["complete_timeline"])
                else:
                    self.assertEqual(replay["timeline"], {})
                    self.assertNotIn(script["truth"]["full_story"], json.dumps(replay, ensure_ascii=False))
                    self.assertNotIn("evidence_chain", json.dumps(replay))
        self.assertEqual(state.phase, GamePhase.REPLAY)
        self.assertEqual(state.scene_phase, ScenePhase.REPLAY)
        self.assertEqual(len(state.stage_resolutions), total_stages)
        for chain in script["truth"]["evidence_chain"]:
            self.assertTrue(set(chain["clue_ids"]).issubset(acquired))
        FLOW_REPORTS.append({"script_id": script_id, "human_role_id": human_id,
                             "provider": "echo" if choice is None else "echo_with_scripted_ballots",
                             "correct": correct, "stages": stage_reports, "completed": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "tests": result.testsRun, "passed": result.wasSuccessful(),
            "duration_seconds": round(time.perf_counter() - started, 3),
            "paid_requests": 0, "production_config_read": False,
            "flows": FLOW_REPORTS,
            "limitations": ["Echo does not evaluate blind deduction or dialogue quality.",
                            "Wrong-ending checks cover public verdict/replay, not all-role audit authorization."]
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
