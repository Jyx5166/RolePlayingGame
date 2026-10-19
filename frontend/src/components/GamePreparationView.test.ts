// @vitest-environment happy-dom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { appEvents } from "../app-events";
import { rolePortrait } from "../script-artwork";
import GamePreparationView from "./GamePreparationView.vue";

const apiRequest = vi.hoisted(() => vi.fn());
vi.mock("../runtime", () => ({ getApiClient: () => ({ request: apiRequest }) }));
const preview = {
  game: { id: 12, status: "preparing" },
  script: { script_id: "rainy_night_letter", title: "雨夜来信", role_count: 3, total_stages: 2, ai_agent_count: 2, story_background: "雨夜，一封信。", playable_roles: [{ role_id: "rnl_qin_he", role_name: "秦禾", public_identity: "记者" }, { role_id: "rnl_shen_yu", role_name: "沈鱼", public_identity: "医生" }] },
  tags: ["悬疑"],
};
const cleanups: (() => void)[] = [];
beforeEach(() => {
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.open = false; });
  apiRequest.mockImplementation(async (_path: string, options?: RequestInit) => options?.method ? {} : preview);
});
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); apiRequest.mockReset(); vi.restoreAllMocks(); });
async function setup(path = "/games/12/prepare") {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/play", name: "script-library", component: { render: () => null } },
    { path: "/games/:gameId/prepare", name: "game-prepare", component: { render: () => null } },
  ] });
  await router.push(path);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = mount(GamePreparationView, { global: { plugins: [router, [VueQueryPlugin, { queryClient }]] } });
  cleanups.push(() => { wrapper.unmount(); queryClient.clear(); });
  await flushPromises();
  return { wrapper, router };
}
describe("GamePreparationView", () => {
  it("keeps the detail artwork behind role selection and activates only after an explicit choice", async () => {
    const { wrapper } = await setup();
    expect(wrapper.get(".detail-story").text()).toContain("雨夜来信");
    const portrait = wrapper.get(".detail-character img").attributes("src");
    expect(portrait).toBe(rolePortrait("rnl_qin_he"));
    expect(wrapper.get(".portrait-option img").attributes("src")).toBe(portrait);
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    expect(apiRequest.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    await wrapper.get('input[value="rnl_qin_he"]').setValue(true);
    const activated = vi.fn();
    cleanups.push(appEvents.on("games:activated", activated));
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/games/12/activate", { method: "POST", body: JSON.stringify({ player_role_id: "rnl_qin_he" }) });
    expect(activated).toHaveBeenCalledWith({ gameId: 12 });
  });
  it("cancels preparation and returns to the library when the role dialog is dismissed", async () => {
    const { wrapper, router } = await setup();
    await wrapper.get("dialog").trigger("cancel");
    await flushPromises();
    expect(apiRequest).toHaveBeenCalledWith("/api/v1/games/12/cancel-preparation", { method: "POST" });
    expect(router.currentRoute.value.name).toBe("script-library");
    expect(apiRequest.mock.calls.some(([path]) => path.includes("/activate"))).toBe(false);
  });
  it("does not reopen or activate an abandoned preparation from browser history", async () => {
    apiRequest.mockResolvedValue({ ...preview, game: { ...preview.game, status: "abandoned" } });
    const activated = vi.fn();
    cleanups.push(appEvents.on("games:activated", activated));
    const { wrapper } = await setup();
    expect(wrapper.text()).toContain("本次入场已取消");
    expect(wrapper.find("dialog").exists()).toBe(false);
    expect(activated).not.toHaveBeenCalled();
    expect(apiRequest.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  });
  it("restores the catalog search and filters after cancelling role selection", async () => {
    const from = "/play?q=雨夜&source=builtin&tag=悬疑&order=title&script=rainy_night_letter";
    const { wrapper, router } = await setup(`/games/12/prepare?from=${encodeURIComponent(from)}`);
    await wrapper.get("dialog").trigger("cancel");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("script-library");
    expect(router.currentRoute.value.query).toEqual({ q: "雨夜", source: "builtin", tag: "悬疑", order: "title" });
  });
  it.each(["https://example.com/play", "//example.com/play", "/games/13", "/player?q=hello"])("uses the default library for an invalid return path: %s", async (from) => {
    const { wrapper, router } = await setup(`/games/12/prepare?from=${encodeURIComponent(from)}`);
    await wrapper.get("dialog").trigger("cancel");
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/play");
  });
});
