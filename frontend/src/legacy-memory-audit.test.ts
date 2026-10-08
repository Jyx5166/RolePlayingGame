// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./runtime", () => ({
  getApiClient: () => ({ request: fixture.request }),
  getNavigation: () => ({ current: () => ({ name: "case-detail", gameId: 1 }), consumeReturnPath: () => null, push: vi.fn(), replace: vi.fn() }),
}));
import { mountLegacyApp } from "./legacy-app.js";

class TestSocket extends EventTarget {
  static OPEN = 1;
  static instance: TestSocket;
  readyState = 1;
  send = vi.fn();
  close = vi.fn();
  constructor() { super(); TestSocket.instance = this; }
  receive(payload: unknown) { this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) })); }
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.innerHTML = ""; });

it("renders historical note stages, postgame revisions, canceled attempts and escaped actual inputs", async () => {
  setActivePinia(createPinia());
  vi.stubGlobal("WebSocket", TestSocket);
  vi.stubGlobal("BroadcastChannel", class extends EventTarget {});
  vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false, addEventListener: vi.fn() } as unknown as MediaQueryList);
  const template = document.createElement("template");
  template.innerHTML = readFileSync("index.html", "utf8");
  template.content.querySelectorAll("script, link").forEach(element => element.remove());
  document.body.replaceChildren(template.content);
  fixture.request.mockImplementation(async (path: string) => {
    if (path === "/api/me") return { id: 1, username: "qa" };
    if (path === "/api/catalog") return { categories: [], modes: [] };
    if (path.endsWith("/ws-ticket")) return { ticket: "test-only" };
    if (path.endsWith("/notebook")) return { automatic: [], clues: [], manual_notes: "" };
    if (path.endsWith("/role-records")) return { roles: [{
      role_id: "human", role_name: "测试角色", controller: "human", operations: [],
      reasoning_notebook: [
        { stage: null, source_type: "manual", title: "旧笔记", content: "legacy" },
        { stage: 2, source_type: "manual", title: "第二幕版本", content: "v2" },
        { stage: 3, phase: "replay", source_type: "manual", title: "终局版本", content: "v3" },
      ],
      agent_context_audits: [{ stage: 2, channel: "private", purpose: "test", status: "canceled", gameplay_committed: false,
        context: { prompt_version: "role-context-v2", latency_ms: 25, input_tokens: 50, output_tokens: null,
          messages: [{ role: "user", scope: "role_private", content: "<img src=x onerror=alert(1)>" }] } },
        { stage: 2, channel: "public", purpose: "budget-test", status: "failed", gameplay_committed: false,
          context: { prompt_version: "role-context-v2", input_prepared: false, provider_invoked: false, messages: [] } }],
    }] };
    return { id: 1, title: "test", current_stage: 3, total_stages: 3, player_role_id: "human" };
  });
  mountLegacyApp();
  await vi.waitFor(() => expect(TestSocket.instance).toBeDefined());
  TestSocket.instance.receive({ type: "phase_changed", phase: { phase: "replay", stage: 3, total_stages: 3 } });
  TestSocket.instance.receive({ type: "replay", verdict: "合成终局", truth_revealed: true });
  (document.getElementById("phaseContinueBtn") as HTMLButtonElement).click();
  await vi.waitFor(() => expect(document.getElementById("roleRecordsModal")!.classList.contains("hidden")).toBe(false));
  const notes = document.getElementById("auditReasoningEntries")!.textContent;
  expect(notes).toContain("幕次未记录");
  expect(notes).toContain("ACT 02");
  expect(notes).toContain("ACT 03 · 终局修订");
  const audit = document.getElementById("auditAgentContexts")!;
  expect(audit.textContent).toContain("已取消");
  expect(audit.textContent).toContain("游戏结果未提交");
  expect(audit.textContent).toContain("输出 未知");
  expect(audit.textContent).toContain("查看输入准备记录");
  expect(audit.textContent).toContain("查看实际输入");
  expect(audit.querySelector("img")).toBeNull();
});
