// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({
  request: vi.fn(),
  navigation: {
    current: () => ({ name: "case-detail", gameId: 28 }),
    consumeReturnPath: () => null,
    push: vi.fn(),
    replace: vi.fn(),
    replacePath: vi.fn(),
  },
}));

vi.mock("./runtime", () => ({
  getApiClient: () => ({ request: fixture.request }),
  getNavigation: () => fixture.navigation,
}));

import { mountLegacyApp } from "./legacy-app.js";

class TestSocket extends EventTarget {
  static OPEN = 1;
  static instances: TestSocket[] = [];
  readyState = 1;
  send = vi.fn();
  close = vi.fn();

  constructor() {
    super();
    TestSocket.instances.push(this);
  }

  receive(payload: unknown) {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

it("restores failed votes and keeps unrelated autonomous responses from unlocking pending speech", async () => {
  setActivePinia(createPinia());
  vi.stubGlobal("WebSocket", TestSocket);
  vi.stubGlobal("BroadcastChannel", class extends EventTarget {});
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  const html = readFileSync("index.html", "utf8");
  const shell = document.createElement("template");
  shell.innerHTML = html;
  shell.content.querySelectorAll("script, link").forEach(element => element.remove());
  document.body.replaceChildren(shell.content);
  fixture.request.mockImplementation(async (path: string) => {
    if (path === "/api/me") return { id: 1, username: "qa" };
    if (path === "/api/catalog") return { categories: [], modes: [] };
    if (path.endsWith("/ws-ticket")) return { ticket: "test-only" };
    if (path.endsWith("/notebook")) return { automatic: [], clues: [], manual_notes: "" };
    return { id: 28, title: "test", current_stage: 2, total_stages: 3, player_role_id: "human" };
  });
  mountLegacyApp();
  await vi.waitFor(() => expect(TestSocket.instances).toHaveLength(1));
  const socket = TestSocket.instances[0];
  const submit = document.getElementById("submitStageVoteBtn") as HTMLButtonElement;
  const continueButton = document.getElementById("phaseContinueBtn") as HTMLButtonElement;

  for (const kind of ["stage", "final"]) {
    socket.receive({
      type: "phase_changed",
      phase: {
        phase: "dm_hosting", stage: kind === "final" ? 3 : 2, total_stages: 3,
        resolution: {
          stage: kind === "final" ? 3 : 2,
          role_results: [],
          vote: {
            kind, pending: true, prompt: "test vote",
            eligible_roles: [{ role_id: "agent", role_name: "test agent", public_identity: "test" }],
          },
        },
      },
    });
    (document.querySelector('[data-vote-role-id="agent"]') as HTMLButtonElement).click();
    submit.click();
    expect(submit.disabled).toBe(true);
    socket.receive({ type: "error", message: "invalid vote" });
    expect(submit.disabled).toBe(false);
    expect(submit.textContent).toContain(kind === "final" ? "确认最终指认" : "提交本幕投票");
    expect(document.querySelector('[data-vote-role-id="agent"]')?.getAttribute("aria-checked")).toBe("true");
    expect(continueButton.disabled).toBe(true);
  }

  socket.receive({
    type: "phase_changed",
    phase: { phase: "investigation", stage: 3, total_stages: 3, enabled_actions: ["public_speech"] },
  });
  const speechInput = document.getElementById("speechInput") as HTMLInputElement;
  const speechSubmit = document.getElementById("speechSubmitBtn") as HTMLButtonElement;
  speechInput.value = "my pending statement";
  document.getElementById("speechForm")!.dispatchEvent(new Event("submit", { cancelable: true }));
  expect(speechSubmit.disabled).toBe(true);
  socket.receive({
    type: "ai_speech", role_id: "agent", target_role_id: "other",
    content: "unrelated autonomous reply", proactive_response: true,
  });
  expect(speechSubmit.disabled).toBe(true);
  socket.receive({ type: "ai_speech", role_id: "agent", content: "reply to the player" });
  expect(speechSubmit.disabled).toBe(false);
});
