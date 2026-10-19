"""Durable staged authoring, publication gates and model accounting regressions."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from authoring_fixtures import FixtureAuthoringLLM, review_error, staged_authoring_fixture
from llm.base import ModelOutputTruncated
from llm.openai_compatible import OpenAICompatibleLLM
from main import create_app


class AuthoringPipelineIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict(os.environ, {"LLM_PROVIDER": "echo"})
        env.start()
        self.addCleanup(env.stop)
        network = patch.object(OpenAICompatibleLLM, "_request", new=AsyncMock(
            side_effect=AssertionError("Authoring regression must not contact a paid provider")))
        self.network = network.start()
        self.addCleanup(network.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="authoring-regression-")
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "authoring.db"
        self.app = create_app(self.database)
        self.workshop = self.app.state.script_workshop
        self.store = self.app.state.game_service.store
        self.auth = self.store.register("authoring_owner", "secret12")
        self.user = self.auth["user"]["id"]
        self.other = self.store.register("authoring_other", "secret12")["user"]["id"]
        self.script, self.plan = staged_authoring_fixture()
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.network.assert_not_awaited()

    def create_job(self, *, request="authoring-0001", mode="ai", script=None, catalog_id=None, source_job_id=None):
        values = {"title": "失落的封蜡 · 回归", "tags": ["推理"], "topic": "旧宅的遗信"}
        if mode == "import":
            values["script"] = deepcopy(script or self.script)
        if source_job_id:
            values["source_job_id"] = source_job_id
        return self.workshop.create(self.user, request, mode, values, catalog_id)[0]

    def fake_factory(self, client):
        return patch("llm.factory.LLMFactory.create", return_value=client)

    def receipts(self, job_id):
        with self.store._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM authoring_model_requests WHERE job_id=? ORDER BY created_at,rowid", (job_id,))]

    def start_job(self, job):
        task = asyncio.create_task(self.workshop.execute(self.user, job["job_id"]))
        self.tasks.append(task)
        return task

    def review_step_ids(self, script=None, suffix=""):
        script = script or self.script
        return [step + suffix for step in [
            "review:public", *(f"review:role:{role['role_id']}" for role in script["roles"]),
            *(f"review:cross:stage_{stage}" for stage in range(1, script["script_meta"]["total_stages"] + 1)),
            "review:logic",
        ]]

    def assert_review_steps(self, job, script=None, *, repaired=False):
        expected = self.review_step_ids(script)
        if repaired:
            expected += self.review_step_ids(script, ":recheck")
        actual = [row["step_id"] for row in self.receipts(job["job_id"])
                  if row["step_id"].startswith("review:")]
        self.assertEqual(actual, expected)

    async def execute(self, client, job=None):
        job = job or self.create_job()
        with self.fake_factory(client):
            await self.workshop.execute(self.user, job["job_id"])
        return self.workshop.job(self.user, job["job_id"])

    async def test_real_pipeline_separates_material_and_requires_explicit_publication(self):
        client = FixtureAuthoringLLM()
        for stage_key, flow in client.script["stage_flow"].items():
            flow["personal_tasks"] = {role["role_id"]: f"{role['role_id']}_PRIVATE_TASK_{stage_key}：私下核对自己的旧信。"
                                      for role in client.script["roles"]}
        before = self.workshop.catalog.list(self.user)
        job = await self.execute(client)
        self.assertEqual(job["status"], "preview", job["error"])
        self.assertTrue(job["can_publish"])
        self.assertTrue(job["preview"]["authoring_validation"]["passed"])
        self.assertEqual(job["preview"]["semantic_review"]["status"], "passed")
        self.assertEqual(before, self.workshop.catalog.list(self.user))
        self.assertEqual([payload["output_schema"]["title"] for payload in client.calls],
                         ["StoryPlan", "Opening", "RoleReading", "RoleReading", "StageFlow", "StageFlow"]
                         + ["SemanticReview"] * len(self.review_step_ids()))
        self.assert_review_steps(job)
        opening_payload = client.calls[1]
        self.assertNotIn("truth", opening_payload)
        self.assertNotIn("private_history", json.dumps(opening_payload))
        for payload in client.calls[2:4]:
            own_id = payload["role_design"]["role_id"]
            other_id = "chen" if own_id == "qin" else "qin"
            self.assertIn(own_id + "_PRIVATE_HISTORY", json.dumps(payload))
            self.assertNotIn(other_id + "_PRIVATE_HISTORY", json.dumps(payload))
            self.assertNotIn("truth", payload)
        public_review = next(call for call in client.calls
                             if call["output_schema"]["title"] == "SemanticReview" and "public_cast" in call)
        for stage_key, flow in public_review["stage_flow"].items():
            self.assertEqual(set(flow), {"title", "public_briefing", "public_tasks", "dm_hosting"})
            self.assertNotIn("personal_tasks", flow)
            self.assertEqual(flow["public_briefing"], job["draft"]["stage_flow"][stage_key]["public_briefing"])
        self.assertNotIn("PRIVATE_TASK", json.dumps(public_review))
        role_reviews = [call for call in client.calls if "role" in call]
        self.assertEqual(len(role_reviews), len(client.script["roles"]))
        for payload in role_reviews:
            own_id = payload["role"]["role_id"]
            other_id = "chen" if own_id == "qin" else "qin"
            self.assertEqual(payload["personal_tasks"], {
                stage_key: flow["personal_tasks"][own_id] for stage_key, flow in job["draft"]["stage_flow"].items()})
            self.assertIn(own_id + "_PRIVATE_TASK", json.dumps(payload))
            self.assertNotIn(other_id + "_PRIVATE_TASK", json.dumps(payload))
        self.assertNotEqual(job["draft"]["opening"]["content"], job["draft"]["stage_flow"]["stage_1"]["public_briefing"])
        self.assertEqual(job["draft"]["truth"], client.plan["truth"])
        self.assertTrue(all(set(step) == {"step_id", "label", "status", "error"} for step in job["steps"]))
        self.assertTrue(all(step["status"] == "completed" for step in job["steps"]))
        self.assertNotIn("model_input_json", job)
        self.assertNotIn("model_output", job)
        completed_calls = deepcopy(client.calls)
        with self.fake_factory(client):
            await self.workshop.execute(self.user, job["job_id"])
        self.assertEqual(client.calls, completed_calls)

    async def test_every_call_has_distinct_durable_receipt_and_measured_usage(self):
        client = FixtureAuthoringLLM()
        job = await self.execute(client)
        rows = self.receipts(job["job_id"])
        self.assertEqual(len(rows), len(client.calls))
        self.assertEqual(len({row["request_id"] for row in rows}), len(rows))
        self.assert_review_steps(job)
        for row in rows:
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["provider"], "fixture")
            self.assertEqual(row["model"], client.model)
            self.assertEqual(row["provider_invoked"], 1)
            self.assertEqual(row["finish_reason"], "stop")
            self.assertGreaterEqual(row["duration_ms"], 0)
            self.assertIsNotNone(row["output_text"])
            self.assertIn("output_schema", json.loads(json.loads(row["input_json"])[-1]["content"]))
        self.assertEqual(job["usage"], {"prompt_tokens": 10 * len(rows), "completion_tokens": 20 * len(rows),
                                       "total_tokens": 30 * len(rows)})

    async def test_one_unknown_usage_is_null_and_never_reuses_previous_call_usage(self):
        client = FixtureAuthoringLLM(unknown_usage_at={2})
        job = await self.execute(client)
        rows = self.receipts(job["job_id"])
        self.assertIsNotNone(rows[0]["usage_json"])
        self.assertIsNone(rows[1]["usage_json"])
        self.assertIsNotNone(rows[2]["usage_json"])
        self.assertIsNone(job["usage"])

    async def test_failure_preserves_completed_opening_and_does_not_retry_provider(self):
        def fail_role(payload, output):
            if payload["output_schema"]["title"] == "RoleReading":
                raise ValueError("PROVIDER_SECRET_CANARY: upstream response includes credentials")
            return output
        client = FixtureAuthoringLLM(handler=fail_role)
        job = await self.execute(client)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["draft"]["opening"], self.script["opening"])
        self.assertEqual(job["draft"]["roles"], [])
        self.assertFalse(job["can_publish"])
        self.assertNotIn("PROVIDER_SECRET_CANARY", json.dumps(job))
        self.assertEqual([row["status"] for row in self.receipts(job["job_id"])], ["completed", "completed", "failed"])
        with self.fake_factory(client):
            await self.workshop.execute(self.user, job["job_id"])
        self.assertEqual(len(client.calls), 3)
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, job["job_id"])

    async def test_invalid_json_keeps_raw_receipt_without_exposing_it_in_safe_job(self):
        def invalid(payload, output):
            return "RAW_OUTPUT_CANARY broken json" if payload["output_schema"]["title"] == "Opening" else output
        job = await self.execute(FixtureAuthoringLLM(handler=invalid))
        self.assertEqual(job["status"], "failed")
        self.assertIsNone(job["draft"]["opening"])
        self.assertNotIn("RAW_OUTPUT_CANARY", json.dumps(job))
        self.assertEqual(self.receipts(job["job_id"])[-1]["output_text"], "RAW_OUTPUT_CANARY broken json")

    async def test_cancellation_while_waiting_for_lock_makes_zero_model_calls(self):
        client = FixtureAuthoringLLM()
        job = self.create_job()
        await self.workshop.generation_lock.acquire()
        try:
            with self.fake_factory(client):
                task = self.start_job(job)
                await asyncio.sleep(0)
                self.assertEqual(self.workshop.job(self.user, job["job_id"])["status"], "generating")
                self.workshop.cancel(self.user, job["job_id"])
                self.workshop.generation_lock.release()
                await asyncio.wait_for(task, 2)
        finally:
            if self.workshop.generation_lock.locked():
                self.workshop.generation_lock.release()
        result = self.workshop.job(self.user, job["job_id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(client.calls, [])
        self.assertEqual(self.receipts(job["job_id"]), [])
        self.assertFalse(result["can_publish"])

    async def test_cancelled_inflight_call_keeps_receipt_but_ignores_late_response(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def hold(payload, output):
            if payload["output_schema"]["title"] == "Opening":
                entered.set()
                await release.wait()
            return output
        client = FixtureAuthoringLLM(handler=hold)
        job = self.create_job()
        with self.fake_factory(client):
            task = self.start_job(job)
            await asyncio.wait_for(entered.wait(), 2)
            partial = self.workshop.job(self.user, job["job_id"])
            self.assertIsNone(partial["draft"]["opening"])
            self.assertTrue(any(step["status"] == "pending" for step in partial["steps"]))
            self.workshop.cancel(self.user, job["job_id"])
            release.set()
            await asyncio.wait_for(task, 2)
        result = self.workshop.job(self.user, job["job_id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertIsNone(result["draft"]["opening"])
        self.assertEqual(len(client.calls), 2)
        rows = self.receipts(job["job_id"])
        self.assertEqual(rows[-1]["status"], "interrupted")
        self.assertIsNotNone(rows[-1]["output_text"])
        self.assertFalse(result["can_publish"])

    async def test_task_cancellation_records_interrupted_call_with_unknown_output(self):
        entered = asyncio.Event()
        async def hold(payload, output):
            if payload["output_schema"]["title"] == "Opening":
                entered.set()
                await asyncio.Event().wait()
            return output
        job = self.create_job()
        with self.fake_factory(FixtureAuthoringLLM(handler=hold)):
            task = self.start_job(job)
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        result = self.workshop.job(self.user, job["job_id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertIsNone(result["draft"]["opening"])
        self.assertEqual(self.receipts(job["job_id"])[-1]["status"], "interrupted")
        self.assertIsNone(self.receipts(job["job_id"])[-1]["output_text"])

    async def test_restart_interrupts_work_and_preserves_partial_draft_without_resume(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def hold(payload, output):
            if payload["output_schema"]["title"] == "RoleReading":
                entered.set()
                await release.wait()
            return output
        client = FixtureAuthoringLLM(handler=hold)
        job = self.create_job()
        with self.fake_factory(client):
            task = self.start_job(job)
            await asyncio.wait_for(entered.wait(), 2)
            restored_app = create_app(self.database)
            restored = restored_app.state.script_workshop
            result = restored.job(self.user, job["job_id"])
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["draft"]["opening"], self.script["opening"])
            self.assertEqual(result["draft"]["roles"], [])
            self.assertEqual(self.receipts(job["job_id"])[-1]["status"], "interrupted")
            await restored.execute(self.user, job["job_id"])
            release.set()
            await asyncio.wait_for(task, 2)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(restored.job(self.user, job["job_id"])["status"], "interrupted")

    async def test_mechanical_failure_skips_semantic_calls_and_blocks_publish(self):
        def duplicate_opening(payload, output):
            if payload["output_schema"]["title"] == "Opening":
                return {**output, "content": self.script["stage_flow"]["stage_1"]["public_briefing"]}
            return output
        client = FixtureAuthoringLLM(handler=duplicate_opening)
        job = await self.execute(client)
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["preview"]["authoring_validation"]["passed"])
        self.assertEqual(job["preview"]["semantic_review"]["status"], "not_run")
        self.assertEqual(len(client.calls), 6)
        self.assertFalse(job["can_publish"])
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, job["job_id"])

    async def test_semantic_logic_failure_cannot_be_published_or_rewritten_as_prose(self):
        client = FixtureAuthoringLLM(review_issues=[[review_error("truth.evidence_chain[0].reasoning")]])
        job = await self.execute(client)
        self.assertTrue(job["preview"]["authoring_validation"]["passed"])
        self.assertEqual(job["preview"]["semantic_review"]["status"], "failed")
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["can_publish"])
        self.assert_review_steps(job)
        self.assertFalse(any("issues_to_fix" in call for call in client.calls))
        self.assertEqual(job["draft"]["truth"], self.plan["truth"])
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, job["job_id"])

    async def test_interrupted_review_retains_completed_findings_and_mechanical_validation(self):
        warning = {**review_error(), "severity": "warning", "code": "completed_review_warning"}

        def truncate_cross_review(payload, output):
            if "public_cast" in payload and payload["output_schema"]["title"] == "SemanticReview":
                return {"summary": "已完成公共文本检查并保留具体问题。", "issues": [warning]}
            if "role_readings" in payload:
                client.last_finish_reason = "length"
                raise ModelOutputTruncated("private-provider-detail")
            return output

        client = FixtureAuthoringLLM(handler=truncate_cross_review)
        job = await self.execute(client)
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["can_publish"])
        self.assertTrue(job["preview"]["authoring_validation"]["passed"])
        review = job["preview"]["semantic_review"]
        self.assertEqual(review["status"], "incomplete")
        self.assertEqual(review["completed_scopes"], 1 + len(self.script["roles"]))
        self.assertEqual(review["total_scopes"], len(self.review_step_ids()))
        self.assertIn("已完成公共文本检查", review["summary"])
        self.assertTrue(any(issue["code"] == warning["code"] for issue in review["issues"]))
        rows = self.receipts(job["job_id"])
        self.assertEqual([row["step_id"] for row in rows if row["status"] == "completed" and row["step_id"].startswith("review:")],
                         ["review:public", "review:role:qin", "review:role:chen"])
        self.assertEqual(rows[-1]["step_id"], "review:cross:stage_1")
        self.assertEqual(rows[-1]["status"], "failed")
        self.assertEqual(rows[-1]["finish_reason"], "length")
        self.assertIsNotNone(rows[-1]["usage_json"])
        step_status = {step["step_id"]: step["status"] for step in job["steps"]}
        self.assertEqual(step_status["plan"], "completed")
        self.assertEqual(step_status["review:cross:stage_1"], "failed")
        self.assertEqual(step_status["review:logic"], "pending")
        self.assertIn("截断", job["error"])
        self.assertNotIn("private-provider-detail", json.dumps(job))
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, job["job_id"])

        legacy_preview = deepcopy(job["preview"])
        legacy_preview["semantic_review"] = {"status": "not_run", "summary": "旧任务尚未记录完整报告。", "issues": []}
        with self.store._connect() as connection:
            connection.execute("UPDATE authoring_jobs SET preview_json=? WHERE job_id=?",
                               (json.dumps(legacy_preview, ensure_ascii=False), job["job_id"]))
        calls_before_restore = deepcopy(client.calls)
        restored = self.workshop.job(self.user, job["job_id"])
        self.assertEqual(restored["preview"]["semantic_review"]["status"], "incomplete")
        self.assertEqual(restored["preview"]["semantic_review"]["completed_scopes"], 1 + len(self.script["roles"]))
        self.assertTrue(any(issue["code"] == warning["code"] for issue in restored["preview"]["semantic_review"]["issues"]))
        self.assertIn("已完成公共文本检查", restored["preview"]["semantic_review"]["summary"])
        self.assertTrue(restored["preview"]["authoring_validation"]["passed"])
        self.assertFalse(restored["can_publish"])
        self.assertEqual(client.calls, calls_before_restore)

    async def test_one_target_repair_reruns_all_reviews_and_keeps_truth_frozen(self):
        client = FixtureAuthoringLLM(review_issues=[[review_error()], []])
        job = await self.execute(client)
        self.assertEqual(job["status"], "preview", job["error"])
        self.assertTrue(job["can_publish"])
        self.assertEqual(sum("issues_to_fix" in call for call in client.calls), 1)
        self.assert_review_steps(job, repaired=True)
        self.assertTrue(job["preview"]["semantic_review"]["repair_attempted"])
        self.assertTrue(job["preview"]["authoring_validation"]["passed"])
        self.assertEqual(job["draft"]["truth"], self.plan["truth"])
        self.assertIn("众人决定先各自回想", job["draft"]["opening"]["content"])
        rows = self.receipts(job["job_id"])
        self.assertEqual(sum(row["step_id"] == "repair" for row in rows), 1)
        self.assertEqual(sum(":recheck" in row["step_id"] for row in rows), len(self.review_step_ids()))

    async def test_persistent_semantic_failure_has_one_repair_limit(self):
        client = FixtureAuthoringLLM(review_issues=[[review_error()]])
        job = await self.execute(client)
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["can_publish"])
        self.assert_review_steps(job, repaired=True)
        self.assertEqual(sum("issues_to_fix" in call for call in client.calls), 1)
        self.assertEqual(job["preview"]["semantic_review"]["status"], "failed")

    async def test_repair_is_mechanically_revalidated_before_any_semantic_recheck(self):
        def break_repair(payload, output):
            if "issues_to_fix" in payload:
                return {**output, "content": self.script["stage_flow"]["stage_1"]["public_briefing"]}
            return output
        client = FixtureAuthoringLLM(handler=break_repair, review_issues=[[review_error()]])
        job = await self.execute(client)
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["can_publish"])
        self.assertFalse(job["preview"]["authoring_validation"]["passed"])
        self.assert_review_steps(job)
        self.assertEqual(sum(call["output_schema"]["title"] == "SemanticReview" for call in client.calls),
                         len(self.review_step_ids()))
        self.assertEqual(sum("issues_to_fix" in call for call in client.calls), 1)

    async def test_issues_in_multiple_sections_do_not_trigger_unbounded_rewrite(self):
        client = FixtureAuthoringLLM(review_issues=[[
            review_error(), review_error("stage_flow.stage_1.public_briefing")]])
        job = await self.execute(client)
        self.assertEqual(job["status"], "failed")
        self.assert_review_steps(job)
        self.assertFalse(any("issues_to_fix" in call for call in client.calls))

    async def test_metadata_revision_of_failed_ai_draft_still_requires_all_semantic_reviews(self):
        issue = review_error("truth.evidence_chain[0].reasoning")
        source = await self.execute(FixtureAuthoringLLM(review_issues=[[issue]]))
        self.assertEqual(source["status"], "failed")
        revised = self.create_job(request="authoring-source-failed", mode="import",
                                  script=source["draft"], source_job_id=source["job_id"])
        failing_reviewer = FixtureAuthoringLLM(review_issues=[[issue]])
        result = await self.execute(failing_reviewer, revised)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["can_publish"])
        self.assertTrue(result["preview"]["semantic_required"])
        self.assertEqual(len(failing_reviewer.calls), len(self.review_step_ids()))
        self.assert_review_steps(result)
        self.assertTrue(all(call["output_schema"]["title"] == "SemanticReview" for call in failing_reviewer.calls))
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, result["job_id"])

        revision = self.create_job(request="authoring-source-passed", mode="import",
                                   script=result["draft"], source_job_id=result["job_id"])
        passing_reviewer = FixtureAuthoringLLM()
        approved = await self.execute(passing_reviewer, revision)
        self.assertEqual(approved["status"], "preview", approved["error"])
        self.assertTrue(approved["can_publish"])
        self.assertTrue(approved["preview"]["semantic_required"])
        self.assertEqual(len(passing_reviewer.calls), len(self.review_step_ids()))
        self.assert_review_steps(approved)
        self.assertFalse(any("issues_to_fix" in call for call in passing_reviewer.calls))
        self.assertTrue(self.workshop.publish(self.user, approved["job_id"])["catalog_id"])

    async def test_foreign_ai_source_job_is_not_readable_or_usable_for_revision(self):
        source = await self.execute(FixtureAuthoringLLM())
        values = {"title": "越权修订", "tags": [], "topic": "", "script": source["draft"],
                  "source_job_id": source["job_id"]}
        with self.assertRaises(KeyError):
            self.workshop.create(self.other, "foreign-source-0001", "import", values)
        foreign = self.store.login("authoring_other", "secret12")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test",
            cookies={self.app.state.cookie_name: foreign["token"]},
            headers={"X-CSRF-Token": foreign["csrf_token"]}) as client:
            response = await client.post("/api/v1/authoring-jobs", json={
                **values, "mode": "import", "request_id": "foreign-source-0002"})
            self.assertEqual(response.status_code, 404, response.text)

    async def test_new_ai_publication_keeps_the_actual_authoring_job_id(self):
        source = await self.execute(FixtureAuthoringLLM())
        published = self.workshop.publish(self.user, source["job_id"])
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT authoring_job_id FROM published_scripts WHERE catalog_id=? AND user_id=?",
                (published["catalog_id"], self.user)).fetchone()
        self.assertEqual(row["authoring_job_id"], source["job_id"])
        self.assertEqual(published["authoring_job_id"], source["job_id"])

    async def test_catalog_ai_revision_inherits_semantic_review_when_source_is_omitted_or_null(self):
        source = await self.execute(FixtureAuthoringLLM())
        published = self.workshop.publish(self.user, source["job_id"])
        for source_field in ("omitted", "null"):
            with self.subTest(source_field=source_field):
                values = {"title": f"目录修订 {source_field}", "tags": ["推理"], "topic": "",
                          "script": deepcopy(source["draft"])}
                if source_field == "null":
                    values["source_job_id"] = None
                job = self.workshop.create(self.user, f"catalog-ai-{source_field}", "import", values,
                                           published["catalog_id"])[0]
                client = FixtureAuthoringLLM(review_issues=[[
                    review_error("truth.evidence_chain[0].reasoning")]])
                result = await self.execute(client, job)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["preview"]["semantic_required"])
                self.assertEqual(result["preview"]["semantic_review"]["status"], "failed")
                self.assertFalse(result["can_publish"])
                self.assert_review_steps(result)
                self.assertTrue(all(call["output_schema"]["title"] == "SemanticReview" for call in client.calls))
                with self.assertRaises(ValueError):
                    self.workshop.publish(self.user, result["job_id"])

    async def test_legacy_catalog_random_source_is_recovered_from_its_published_job_result(self):
        source = await self.execute(FixtureAuthoringLLM())
        published = self.workshop.publish(self.user, source["job_id"])
        with self.store._connect() as connection:
            connection.execute("UPDATE published_scripts SET authoring_job_id=? WHERE catalog_id=? AND user_id=?",
                               ("legacy-random-nonexistent-job", published["catalog_id"], self.user))
        job = self.create_job(request="legacy-catalog-ai-revision", mode="import", script=source["draft"],
                              catalog_id=published["catalog_id"])
        client = FixtureAuthoringLLM(review_issues=[[
            review_error("truth.evidence_chain[0].reasoning")]])
        result = await self.execute(client, job)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["preview"]["semantic_required"])
        self.assertFalse(result["can_publish"])
        self.assert_review_steps(result)
        public = next(call for call in client.calls if "public_cast" in call)
        self.assertEqual(public["timeline_events"], self.plan["timeline_events"])
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, result["job_id"])

    async def test_explicit_unrelated_import_source_cannot_bypass_catalog_ai_review(self):
        source = await self.execute(FixtureAuthoringLLM())
        published = self.workshop.publish(self.user, source["job_id"])
        independent = self.create_job(request="independent-import-source", mode="import")
        independent = await self.execute(FixtureAuthoringLLM(), independent)
        self.assertFalse(independent["preview"]["semantic_required"])
        try:
            job = self.create_job(request="catalog-ai-wrong-source", mode="import", script=source["draft"],
                                  catalog_id=published["catalog_id"], source_job_id=independent["job_id"])
        except ValueError:
            return  # Rejecting an unrelated source is also a valid publication gate.
        client = FixtureAuthoringLLM(review_issues=[[
            review_error("truth.evidence_chain[0].reasoning")]])
        result = await self.execute(client, job)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["preview"]["semantic_required"])
        self.assertFalse(result["can_publish"])
        self.assert_review_steps(result)
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, result["job_id"])

    async def test_old_import_preview_is_blocked_after_catalog_gains_ai_history(self):
        original = await self.execute(FixtureAuthoringLLM(), self.create_job(mode="import"))
        published = self.workshop.publish(self.user, original["job_id"])
        pending = self.create_job(request="old-source-free-preview", mode="import", catalog_id=published["catalog_id"])
        pending = await self.execute(FixtureAuthoringLLM(), pending)
        self.assertTrue(pending["can_publish"])
        self.assertFalse(pending["preview"]["semantic_required"])

        ai_revision = self.create_job(request="catalog-gains-ai-history", catalog_id=published["catalog_id"])
        ai_revision = await self.execute(FixtureAuthoringLLM(), ai_revision)
        self.workshop.publish(self.user, ai_revision["job_id"])
        restored = self.workshop.job(self.user, pending["job_id"])
        self.assertFalse(restored["can_publish"])
        with self.assertRaises(ValueError):
            self.workshop.publish(self.user, pending["job_id"])

    async def test_catalog_revision_request_replay_stays_idempotent_after_publication_advances_source(self):
        source = await self.execute(FixtureAuthoringLLM())
        published = self.workshop.publish(self.user, source["job_id"])
        values = {"title": "目录修订重放", "tags": ["推理"], "topic": "", "script": deepcopy(source["draft"])}
        job = self.workshop.create(self.user, "catalog-ai-idempotent-replay", "import", values,
                                   published["catalog_id"])[0]
        result = await self.execute(FixtureAuthoringLLM(), job)
        self.assertTrue(result["can_publish"])
        revision = self.workshop.publish(self.user, result["job_id"])
        again, created = self.workshop.create(self.user, "catalog-ai-idempotent-replay", "import", values,
                                              published["catalog_id"])
        self.assertFalse(created)
        self.assertEqual(again["job_id"], result["job_id"])
        self.assertEqual(again["status"], "published")
        self.assertEqual(again["result"], revision)
        self.assertEqual(len(self.receipts(again["job_id"])), len(self.review_step_ids()))

    async def test_revision_review_reads_edited_truth_and_matches_reordered_roles_by_id(self):
        source = await self.execute(FixtureAuthoringLLM(review_issues=[[
            review_error("truth.evidence_chain[0].reasoning")]]))
        revised = deepcopy(source["draft"])
        revised["truth"]["full_story"] += "修订核对：领料发生在同一天。"
        revised["roles"].reverse()
        for role in revised["roles"]:
            for stage_key, reading in role["stage_knowledge"].items():
                reading["blocks"][0]["content"] += f"手修成稿_{role['role_id']}_{stage_key}，此处以修订正文为准。"
        job = self.create_job(request="authoring-edited-truth", mode="import", script=revised,
                              source_job_id=source["job_id"])
        client = FixtureAuthoringLLM()
        result = await self.execute(client, job)
        self.assertEqual(result["status"], "preview", result["error"])
        self.assertTrue(result["can_publish"])
        self.assertEqual(len(client.calls), len(self.review_step_ids(revised)))
        self.assert_review_steps(result, revised)
        public = next(call for call in client.calls if "public_cast" in call)
        logic = next(call for call in client.calls if "role_designs" in call)
        self.assertEqual(public["truth"], revised["truth"])
        self.assertEqual(logic["truth"], revised["truth"])
        role_reviews = [call for call in client.calls if "role" in call]
        self.assertEqual([call["role"]["role_id"] for call in role_reviews], ["chen", "qin"])
        for call in role_reviews:
            self.assertEqual(call["role"]["role_id"], call["design"]["role_id"])
        cross_reviews = [call for call in client.calls if "role_readings" in call]
        self.assertEqual([call["stage_key"] for call in cross_reviews], ["stage_1", "stage_2"])
        for call in cross_reviews:
            stage_key = call["stage_key"]
            self.assertEqual(call["truth"], revised["truth"])
            self.assertEqual(call["stage_flow"], revised["stage_flow"][stage_key])
            self.assertEqual(call["role_readings"], [{
                "role_id": role["role_id"], "role_name": role["role_name"],
                "blocks": role["stage_knowledge"][stage_key]["blocks"],
            } for role in revised["roles"]])
            self.assertNotIn("public_cast", call)
            self.assertNotIn("role_designs", call)
            self.assertNotIn("stage_design", call)
            other_key = "stage_2" if stage_key == "stage_1" else "stage_1"
            for role in revised["roles"]:
                self.assertNotIn(f"手修成稿_{role['role_id']}_{other_key}", json.dumps(call, ensure_ascii=False))

    async def test_cross_review_uses_generated_prose_instead_of_role_design(self):
        def change_prose(payload, output):
            if payload["output_schema"]["title"] == "RoleReading":
                role_id = payload["role_design"]["role_id"]
                for key, reading in output["stage_knowledge"].items():
                    reading["blocks"][0]["content"] += f"实际成稿_{role_id}_{key}：你记得纸张上的折痕。"
            return output

        client = FixtureAuthoringLLM(handler=change_prose)
        original_design = deepcopy(client.plan["roles"])
        job = await self.execute(client)
        self.assertEqual(job["status"], "preview", job["error"])
        self.assertEqual(client.plan["roles"], original_design)
        cross_reviews = [call for call in client.calls if "role_readings" in call]
        self.assertEqual(len(cross_reviews), job["draft"]["script_meta"]["total_stages"])
        for call in cross_reviews:
            key = call["stage_key"]
            self.assertEqual(call["role_readings"], [{
                "role_id": role["role_id"], "role_name": role["role_name"],
                "blocks": role["stage_knowledge"][key]["blocks"],
            } for role in job["draft"]["roles"]])
            for role in job["draft"]["roles"]:
                marker = f"实际成稿_{role['role_id']}_{key}"
                self.assertIn(marker, json.dumps(call, ensure_ascii=False))
                self.assertNotIn(marker, json.dumps(original_design, ensure_ascii=False))

    async def test_role_repair_reruns_cross_review_with_repaired_actual_prose(self):
        stage_one_reviews = 0

        def contradict_then_repair(payload, output):
            nonlocal stage_one_reviews
            if payload["output_schema"]["title"] == "RoleReading" and "issues_to_fix" in payload:
                output["stage_knowledge"]["stage_1"]["blocks"][0]["content"] += "修复成稿：你在前厅看见原信交付。"
            if "role_readings" in payload and payload["stage_key"] == "stage_1":
                stage_one_reviews += 1
                if stage_one_reviews == 1:
                    return {"summary": "当幕两个角色的成稿需要交叉修订。", "issues": [
                        review_error("role_readings[0].blocks[0].content")
                    ]}
            return output

        client = FixtureAuthoringLLM(handler=contradict_then_repair)
        job = await self.execute(client)
        self.assertEqual(job["status"], "preview", job["error"])
        self.assertTrue(job["can_publish"])
        self.assertEqual(stage_one_reviews, 2)
        self.assert_review_steps(job, repaired=True)
        repaired = [call for call in client.calls if "issues_to_fix" in call]
        self.assertEqual([call["role_design"]["role_id"] for call in repaired], ["qin"])
        self.assertEqual(repaired[0]["issues_to_fix"][0]["path"],
                         "roles.qin.stage_knowledge.stage_1.blocks[0].content")
        stage_one = [call for call in client.calls if "role_readings" in call and call["stage_key"] == "stage_1"]
        self.assertNotIn("修复成稿", json.dumps(stage_one[0], ensure_ascii=False))
        self.assertIn("修复成稿", json.dumps(stage_one[1], ensure_ascii=False))
        self.assertEqual(stage_one[1]["role_readings"][0]["blocks"],
                         job["draft"]["roles"][0]["stage_knowledge"]["stage_1"]["blocks"])
        self.assertEqual(stage_one[0]["role_readings"][1], stage_one[1]["role_readings"][1])

    async def test_role_relative_issue_path_can_trigger_bounded_repair_and_cross_recheck(self):
        role_reviews = 0

        def relative_issue(payload, output):
            nonlocal role_reviews
            if "role" in payload and payload["role"]["role_id"] == "qin":
                role_reviews += 1
                if role_reviews == 1:
                    return {"summary": "角色正文与既定经历冲突。", "issues": [
                        review_error("stage_knowledge.stage_1.blocks[0].content")
                    ]}
            if payload["output_schema"]["title"] == "RoleReading" and "issues_to_fix" in payload:
                output["stage_knowledge"]["stage_1"]["blocks"][0]["content"] += "相对路径修订：你重新核对了送信日期。"
            return output

        client = FixtureAuthoringLLM(handler=relative_issue)
        job = await self.execute(client)
        self.assertEqual(job["status"], "preview", job["error"])
        self.assertTrue(job["can_publish"])
        self.assert_review_steps(job, repaired=True)
        repairs = [call for call in client.calls if "issues_to_fix" in call]
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["role_design"]["role_id"], "qin")
        self.assertEqual(repairs[0]["issues_to_fix"][0]["path"],
                         "roles.qin.stage_knowledge.stage_1.blocks[0].content")
        cross_reviews = [call for call in client.calls if "role_readings" in call]
        self.assertEqual([call["stage_key"] for call in cross_reviews],
                         ["stage_1", "stage_2", "stage_1", "stage_2"])
        self.assertIn("相对路径修订", json.dumps(cross_reviews[2], ensure_ascii=False))

    async def test_import_is_zero_model_owner_bound_idempotent_and_retains_game_snapshot(self):
        client = FixtureAuthoringLLM()
        job = self.create_job(mode="import")
        again, created = self.workshop.create(self.user, job["request_id"], "import", job["input"])
        self.assertFalse(created)
        self.assertEqual(again["job_id"], job["job_id"])
        with self.assertRaises(ValueError):
            self.workshop.create(self.user, job["request_id"], "import", {**job["input"], "title": "不同内容"})
        job = await self.execute(client, job)
        self.assertEqual(job["status"], "preview", job["error"])
        self.assertTrue(job["can_publish"])
        self.assertEqual(job["preview"]["semantic_review"]["status"], "not_run")
        self.assertEqual(client.calls, [])
        self.assertEqual(self.receipts(job["job_id"]), [])
        published = self.workshop.publish(self.user, job["job_id"])
        self.assertEqual(self.workshop.publish(self.user, job["job_id"]), published)
        catalog_id = published["catalog_id"]
        original = self.workshop.catalog.resolve(self.user, catalog_id)
        game = self.store.prepare_game(self.user, original["script"], catalog_id, original["version"])
        revision = deepcopy(original["script"])
        revision["story_background"] += "十年后，这份旧信再次被人提起。"
        revised_job = self.create_job(request="authoring-revision-0001", mode="import", script=revision, catalog_id=catalog_id)
        revised_job = await self.execute(client, revised_job)
        self.assertEqual(revised_job["status"], "preview", revised_job["error"])
        updated = self.workshop.publish(self.user, revised_job["job_id"])
        self.assertNotEqual(updated["version"], published["version"])
        self.assertEqual(len(self.workshop.revisions(self.user, catalog_id)), 2)
        self.assertEqual(self.workshop.catalog.resolve(self.user, catalog_id, original["version"])["script"], original["script"])
        self.assertEqual(self.store.get_game(self.user, game["id"], include_script=True)["script"], original["script"])
        for action in (self.workshop.job, self.workshop.cancel, self.workshop.publish):
            with self.assertRaises(KeyError):
                action(self.other, job["job_id"])
        self.assertEqual(client.calls, [])

    async def test_http_restores_safe_draft_and_rejects_foreign_owner(self):
        job = await self.execute(FixtureAuthoringLLM())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test",
            cookies={self.app.state.cookie_name: self.auth["token"]}) as client:
            response = await client.get("/api/v1/authoring-jobs/" + job["job_id"])
            self.assertEqual(response.status_code, 200, response.text)
            restored = response.json()
            self.assertEqual(restored["draft"], job["draft"])
            self.assertTrue(restored["can_publish"])
            self.assertTrue(restored["steps"])
            self.assertNotIn("input_json", response.text)
            self.assertNotIn("PRIVATE_HISTORY", response.text)
            other_auth = self.store.login("authoring_other", "secret12")
            client.cookies.set(self.app.state.cookie_name, other_auth["token"])
            self.assertEqual((await client.get("/api/v1/authoring-jobs/" + job["job_id"])).status_code, 404)

    async def test_legacy_publication_api_accepts_valid_import_and_rejects_duplicate_opening(self):
        before = self.workshop.catalog.list(self.user)
        invalid = deepcopy(self.script)
        invalid["opening"]["content"] = invalid["stage_flow"]["stage_1"]["public_briefing"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test",
            cookies={self.app.state.cookie_name: self.auth["token"]},
            headers={"X-CSRF-Token": self.auth["csrf_token"]}) as client:
            rejected = await client.post("/api/v1/scripts", json={
                "script": invalid, "title": "重复开幕不能直发", "tags": ["推理"]})
            self.assertEqual(rejected.status_code, 400, rejected.text)
            self.assertEqual(self.workshop.catalog.list(self.user), before)
            accepted = await client.post("/api/v1/scripts", json={
                "script": self.script, "title": "正常旧版导入", "tags": ["推理"]})
            self.assertEqual(accepted.status_code, 201, accepted.text)
            self.assertTrue(accepted.json()["catalog_id"])
        self.assertEqual(len(self.workshop.catalog.list(self.user)), len(before) + 1)


if __name__ == "__main__":
    unittest.main()
