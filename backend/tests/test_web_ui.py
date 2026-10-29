from __future__ import annotations

from backend.tests.account_fixtures import new_test_account

import hashlib
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")
os.environ["LLM_PROVIDER"] = "echo"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "app"))
sys.path.insert(0, str(PROJECT_ROOT / "launcher"))

from fastapi.testclient import TestClient
from launch_local import HOST, PORT, URL
from main import create_app


class WebUiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(
            create_app(
                Path(self.temp_dir.name) / "test.db",
                allow_legacy_token_response=True,
            )
        )
        register = self.client.post("/api/auth/register", json=new_test_account('web_user'))
        self.token = register.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_root_starts_with_login_ui(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="vueRoot"', response.text)
        self.assertIn('id="authView"', response.text)
        self.assertIn('id="appSidebar"', response.text)
        self.assertIn('id="scriptLibraryView"', response.text)
        creator_component = (PROJECT_ROOT / "frontend" / "src" / "components" / "ScriptCreatorView.vue").read_text(encoding="utf-8")
        self.assertIn("新建剧本", creator_component)
        auth_component = (PROJECT_ROOT / "frontend" / "src" / "components" / "AuthView.vue").read_text(encoding="utf-8")
        sidebar_component = (PROJECT_ROOT / "frontend" / "src" / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
        self.assertIn("登录", auth_component)
        self.assertIn("案件档案", sidebar_component)

    def test_entry_assets_are_content_versioned(self) -> None:
        for route in ("/", "/login", "/cases/new"):
            html = self.client.get(route).text
            for asset in ("app.js", "styles.css"):
                digest = hashlib.sha256((PROJECT_ROOT / "frontend" / asset).read_bytes()).hexdigest()[:16]
                self.assertIn(f'/static/{asset}?v={digest}', html)

    def test_mutable_assets_require_cache_revalidation(self) -> None:
        for asset in ("app.js", "styles.css"):
            response = self.client.get(f"/static/{asset}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Cache-Control"), "no-cache")
            cached = self.client.get(f"/static/{asset}", headers={"If-None-Match": response.headers["etag"]})
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(cached.headers.get("Cache-Control"), "no-cache")

    def test_static_assets_contain_new_product_flow(self) -> None:
        css = self.client.get("/static/styles.css")
        js = self.client.get("/static/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        self.assertIn(".auth-view", css.text)
        self.assertIn(".channel-control", css.text)
        self.assertIn(".compact-game-tabs", css.text)
        self.assertIn("localStorage", js.text)
        self.assertIn("new WebSocket", js.text)
        self.assertIn("whisper_invite", js.text)
        self.assertIn("ai_proactive_speech", js.text)
        self.assertIn("agent_activity_start", js.text)
        self.assertIn("expectedSocketClosures", js.text)
        self.assertIn("scheduleGameReconnect", js.text)
        self.assertIn("history_events", js.text)
        records_component = (PROJECT_ROOT / "frontend" / "src" / "components" / "CaseRecordsView.vue").read_text(encoding="utf-8")
        self.assertIn("delete-game-record", js.text)
        self.assertIn("确认删除", records_component)
        self.assertIn("useGameRecordsQuery", records_component)
        self.assertIn("loadNotebook", js.text)
        self.assertIn("openRoleRecords", js.text)
        self.assertIn("roleAvatarMarkup", js.text)
        self.assertIn("setAvatarAction", js.text)
        self.assertIn("后端仍在运行旧版本", js.text)
        self.assertIn("setCompactGamePanel", js.text)
        self.assertIn("agent-autonomy-state", css.text)
        self.assertIn(".avatar-public", css.text)
        self.assertIn(".avatar-private-session", css.text)
        self.assertIn(".avatar-search", css.text)
        self.assertIn(".role-records-modal", css.text)
        self.assertIn(".audit-agent-contexts", css.text)
        self.assertIn('id="notebookManualNotes"', self.client.get("/").text)
        self.assertIn('id="ownedClues"', self.client.get("/").text)
        self.assertIn('id="auditClues"', self.client.get("/").text)
        self.assertIn('id="auditAgentContexts"', self.client.get("/").text)
        self.assertIn("renderAgentContextAudits", js.text)
        self.assertIn("share_clue", self.client.get("/static/app.js").text)
        self.assertIn('id="conversationParticipants"', self.client.get("/").text)
        self.assertIn('data-compact-panel="dialogue"', self.client.get("/").text)

    def test_script_preview_exposes_dynamic_agent_count(self) -> None:
        script = json.loads(
            (BACKEND_ROOT / "resources" / "scripts" / "flame_mountain.json").read_text(encoding="utf-8")
        )
        response = self.client.post(
            "/api/scripts/inspect",
            headers=self.headers,
            json={"mode": "narrative", "script": script},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role_count"], 3)
        self.assertEqual(response.json()["ai_agent_count"], 2)

    def test_game_sidebar_has_bidirectional_visibility_controls(self) -> None:
        html = self.client.get("/").text
        js = self.client.get("/static/app.js").text
        css = self.client.get("/static/styles.css").text
        sidebar_component = (PROJECT_ROOT / "frontend" / "src" / "components" / "AppSidebar.vue").read_text(encoding="utf-8")

        self.assertIn('id="appSidebar"', html)
        self.assertIn('id="collapseSidebarBtn"', sidebar_component)
        self.assertIn("展开导航栏", sidebar_component)
        self.assertIn("setSidebarCollapsed", js)
        self.assertNotIn('toggleAttribute("inert", active)', js)
        self.assertIn(".app-view.sidebar-collapsed", css)
        self.assertIn("grid-template-columns: 72px minmax(0, 1fr)", css)

    def test_account_avatar_has_online_and_in_game_motion_states(self) -> None:
        js = self.client.get("/static/app.js").text
        css = self.client.get("/static/styles.css").text
        sidebar_component = (PROJECT_ROOT / "frontend" / "src" / "components" / "AppSidebar.vue").read_text(encoding="utf-8")

        self.assertIn('id="userAvatarInitial"', sidebar_component)
        self.assertIn("account-avatar-spectrum", sidebar_component)
        self.assertIn("<i /><i /><i /><i /><i />", sidebar_component)
        self.assertIn("syncAccountAvatar", js)
        self.assertIn("'is-online': Boolean(auth.user)", sidebar_component)
        self.assertIn("'is-thinking': ui.gameActive", sidebar_component)
        self.assertIn(".account-avatar.is-online", css)
        self.assertIn(".account-avatar.is-thinking", css)
        self.assertIn("@keyframes account-avatar-thought-level", css)

    def test_stage_resolution_ui_exposes_scoring_vote_and_final_verdict(self) -> None:
        html = self.client.get("/").text
        js = self.client.get("/static/app.js").text
        css = self.client.get("/static/styles.css").text

        self.assertIn('id="stageResolutionPanel"', html)
        self.assertIn('id="resolutionCandidates"', html)
        self.assertIn('id="submitStageVoteBtn"', html)
        self.assertIn('id="auditStageResults"', html)
        self.assertIn("renderStageResolution", js)
        self.assertIn('type: "stage_vote"', js)
        self.assertIn("truth_revealed", js)
        self.assertIn("state.stageResolution?.vote?.pending", js)
        self.assertIn("请先完成本幕投票或最终指认", js)
        self.assertIn("renderInvestigationRules", js)
        self.assertIn('case "investigation_progress"', js)
        self.assertIn("建议目标已达成但不会自动结束", js)
        self.assertIn('id="investigationEndVoteStatus"', html)
        self.assertIn("renderInvestigationEndVote", js)
        self.assertIn('case "investigation_end_vote"', js)
        self.assertIn("正在征询所有角色", js)
        self.assertIn(".resolution-role-results", css)
        self.assertIn(".resolution-candidate.result-selected", css)
        self.assertIn(".phase-rules p.ready", css)
        self.assertIn(".end-vote-status.approved", css)
        self.assertIn(".end-vote-status.rejected", css)

    def test_catalog_only_exposes_mystery_mvp(self) -> None:
        response = self.client.get("/api/catalog", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["categories"]], ["mystery"])
        self.assertEqual([item["id"] for item in response.json()["modes"]], ["deduction"])

    def test_example_script_is_deduction_mystery(self) -> None:
        response = self.client.get("/api/scripts/example", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        script = response.json()
        self.assertEqual(script["script_id"], "fog_harbor_clocktower")
        self.assertEqual(script["supported_modes"], ["deduction"])
        self.assertEqual(script["role_count"], 4)
        self.assertNotIn("truth", script)
        self.assertNotIn("stage_knowledge", response.text)

    def test_launcher_constants(self) -> None:
        self.assertEqual(HOST, "127.0.0.1")
        self.assertEqual(PORT, 8000)
        self.assertEqual(URL, "http://127.0.0.1:8000")


if __name__ == "__main__":
    unittest.main()
