// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, expect, it, vi } from "vitest";
import { appEvents } from "./app-events";

const fixture = vi.hoisted(() => ({
  request: vi.fn(),
  navigation: {
    current: () => ({ name: "personal-center" }),
    consumeReturnPath: () => "",
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

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

it("restores the personal workspace on startup and hides it when navigating to other pages", async () => {
  setActivePinia(createPinia());
  vi.stubGlobal("BroadcastChannel", class extends EventTarget {});
  vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false, addEventListener: vi.fn() } as unknown as MediaQueryList);
  const shell = document.createElement("template");
  shell.innerHTML = readFileSync("index.html", "utf8");
  shell.content.querySelectorAll("script, link").forEach(element => element.remove());
  document.body.replaceChildren(shell.content);
  fixture.request.mockResolvedValue({ id: 7, username: "investigator" });
  mountLegacyApp();
  const personal = document.getElementById("personalCenterView")!;
  const library = document.getElementById("scriptLibraryView")!;
  await vi.waitFor(() => expect(personal.classList.contains("hidden")).toBe(false));
  expect(library.classList.contains("hidden")).toBe(true);
  expect(document.getElementById("recordsView")!.classList.contains("hidden")).toBe(true);

  appEvents.emit("navigation:view", { view: "library" });
  await vi.waitFor(() => expect(library.classList.contains("hidden")).toBe(false));
  expect(personal.classList.contains("hidden")).toBe(true);
  appEvents.emit("navigation:view", { view: "profile" });
  await vi.waitFor(() => expect(personal.classList.contains("hidden")).toBe(false));
  expect(library.classList.contains("hidden")).toBe(true);
  expect(fixture.navigation.push).toHaveBeenLastCalledWith({ name: "personal-center" });
  expect(fixture.request.mock.calls.map(([path]) => path)).toEqual(["/api/me"]);
});
