// @vitest-environment happy-dom

import { readFileSync } from "node:fs";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({
  request: vi.fn(),
  navigation: {
    current: () => ({ name: "case-detail", gameId: 1 }),
    consumeReturnPath: () => null,
    push: vi.fn(),
    replace: vi.fn(),
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

  constructor() { super(); TestSocket.instances.push(this); }
  receive(payload: unknown) {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fixture.request.mockReset();
  fixture.navigation.push.mockReset();
  TestSocket.instances = [];
  document.body.innerHTML = "";
});

it.each([true, false, undefined])("offers the right replay action for truth_revealed=%s", async (truthRevealed) => {
  setActivePinia(createPinia());
  vi.stubGlobal("WebSocket", TestSocket);
  vi.stubGlobal("BroadcastChannel", class extends EventTarget {});
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: false, addEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  const shell = document.createElement("template");
  shell.innerHTML = readFileSync("index.html", "utf8");
  shell.content.querySelectorAll("script, link").forEach(element => element.remove());
  document.body.replaceChildren(shell.content);
  fixture.request.mockImplementation(async (path: string) => {
    if (path === "/api/me") return { id: 1, username: "qa" };
    if (path === "/api/catalog") return { categories: [], modes: [] };
    if (path.endsWith("/ws-ticket")) return { ticket: "test-only" };
    if (path.endsWith("/notebook")) return { automatic: [], clues: [], manual_notes: "" };
    if (path.endsWith("/role-records")) return { roles: [] };
    return { id: 1, title: "test", current_stage: 3, total_stages: 3, player_role_id: "human" };
  });
  mountLegacyApp();
  await vi.waitFor(() => expect(TestSocket.instances).toHaveLength(1));
  TestSocket.instances[0].receive({ type: "replay", verdict: "终局裁决", truth_revealed: truthRevealed });
  const button = document.getElementById("phaseContinueBtn") as HTMLButtonElement;
  expect(button.textContent).toContain(truthRevealed === true ? "查看全部角色记录" : "返回案件档案");
  button.click();
  if (truthRevealed === true) {
    await vi.waitFor(() => expect(fixture.request).toHaveBeenCalledWith("/api/games/1/role-records", {}));
    expect(fixture.navigation.push).not.toHaveBeenCalled();
  } else {
    expect(fixture.navigation.push).toHaveBeenCalledWith({ name: "case-list" });
    expect(fixture.request).not.toHaveBeenCalledWith("/api/games/1/role-records", expect.anything());
  }
});
