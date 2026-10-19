// @vitest-environment happy-dom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { appEvents } from "../app-events";
import { gameRecordsQueryKey, type GameSummary } from "../queries/game-records";
import { useAuthStore } from "../stores/auth";
import PersonalCenterView from "./PersonalCenterView.vue";

const apiRequest = vi.hoisted(() => vi.fn());
vi.mock("../runtime", () => ({ getApiClient: () => ({ request: apiRequest }) }));
const base: GameSummary = { id: 12, title: "雾港档案", category: "mystery", mode: "deduction", player_role_id: "r1", ai_agent_count: 3,
  current_stage: 2, current_phase: "investigation", total_stages: 4, status: "playing", created_at: "2026-10-10T10:00:00Z", updated_at: "2026-10-18T12:00:00Z" };
const games: GameSummary[] = [
  base,
  { ...base, id: 13, title: "雨夜终章", status: "completed", current_stage: 4, current_phase: "replay", updated_at: "2026-10-18T10:00:00Z" },
  { ...base, id: 14, title: "已取消的故事", status: "abandoned", current_stage: 1, current_phase: "preparing", updated_at: "2026-10-18T08:00:00Z" },
  { ...base, id: 15, title: "暂歇的开幕", status: "paused", current_stage: 1, current_phase: "opening", updated_at: "2026-10-18T11:00:00Z" },
  { ...base, id: 16, title: "待选角色的故事", status: "preparing", current_stage: 1, current_phase: "preparing", updated_at: "2026-10-18T09:00:00Z" },
];
const cleanups: (() => void)[] = [];
async function setup(path = "/personal-center") {
  const pinia = createPinia(); setActivePinia(pinia);
  const auth = useAuthStore(); auth.setSession({ id: 7, username: "investigator" });
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/personal-center", name: "personal-center", component: { render: () => null } },
    { path: "/cases", name: "case-list", component: { render: () => null } },
  ] });
  await router.push(path); await router.isReady();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = mount(PersonalCenterView, { global: { plugins: [pinia, router, [VueQueryPlugin, { queryClient }]] } });
  cleanups.push(() => { wrapper.unmount(); queryClient.clear(); });
  await flushPromises();
  return { wrapper, router, queryClient, auth };
}
afterEach(() => { cleanups.splice(0).reverse().forEach(cleanup => cleanup()); apiRequest.mockReset(); });

describe("PersonalCenterView", () => {
  it("shows only real account fields and derives counts and recent records from the current user's cases", async () => {
    apiRequest.mockResolvedValue(games);
    const { wrapper } = await setup();
    expect(wrapper.get(".personal-center-avatar").text()).toBe("I");
    expect(wrapper.get(".personal-center-account h3").text()).toBe("investigator");
    expect(wrapper.get(".personal-center-account-fields").text()).toBe("账号 ID#7账户类型本地账户");
    expect(wrapper.findAll(".personal-center-stat strong").map(value => value.text())).toEqual(["5", "3", "1"]);
    expect(wrapper.get(".personal-center-stats-note").text()).toContain("包含已取消入场记录");
    const records = wrapper.findAll(".personal-center-recent-list > li");
    expect(records).toHaveLength(3);
    expect(records.map(record => record.get(".personal-center-record-id").text())).toEqual(["CASE #12", "CASE #15", "CASE #13"]);
    expect(records[0]!.text()).toContain("自由调查 · 第 2 / 4 幕");
    expect(records[1]!.text()).toContain("故事开幕 · 共 4 幕");
    expect(records[2]!.text()).toContain("终局复盘 · 第 4 / 4 幕");
    expect(records[1]!.get(".personal-center-record-status").text()).toBe("已暂停");
    expect(wrapper.find("input").exists()).toBe(false);
    expect(wrapper.text()).not.toMatch(/邮箱|注册日期|徽章|成就/);
    expect(apiRequest).toHaveBeenCalledWith("/api/games", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("uses pending placeholders instead of zero counts before the request resolves", async () => {
    let resolve: (value: GameSummary[]) => void = () => {};
    apiRequest.mockImplementation(() => new Promise<GameSummary[]>(done => { resolve = done; }));
    const { wrapper } = await setup();
    expect(wrapper.findAll(".personal-center-stat strong").map(value => value.text())).toEqual(["—", "—", "—"]);
    expect(wrapper.get('[role="status"]').text()).toContain("正在读取案件概览");
    expect(wrapper.find(".personal-center-empty").exists()).toBe(false);
    resolve([]); await flushPromises();
    expect(wrapper.findAll(".personal-center-stat strong").map(value => value.text())).toEqual(["0", "0", "0"]);
    expect(wrapper.get(".personal-center-empty").text()).toContain("暂无案件记录");
  });

  it("reports a failed load and retries without fabricating records or counts", async () => {
    apiRequest.mockRejectedValueOnce(new Error("案件服务暂时不可用")).mockResolvedValueOnce([base]);
    const { wrapper } = await setup();
    expect(wrapper.get('[role="alert"]').text()).toBe("案件服务暂时不可用");
    expect(wrapper.findAll(".personal-center-stat strong").map(value => value.text())).toEqual(["—", "—", "—"]);
    expect(wrapper.find(".personal-center-recent-list").exists()).toBe(false);
    await wrapper.get(".personal-center-error button").trigger("click"); await flushPromises();
    expect(apiRequest).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.get(".personal-center-recent-list").text()).toContain("雾港档案");
    expect(wrapper.findAll(".personal-center-stat strong").map(value => value.text())).toEqual(["1", "1", "0"]);
  });

  it("enables the shared records query only on the personal-center route", async () => {
    apiRequest.mockResolvedValue([base]);
    const { router, queryClient } = await setup("/cases");
    expect(apiRequest).not.toHaveBeenCalled();
    await router.push("/personal-center"); await flushPromises();
    expect(apiRequest).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(gameRecordsQueryKey(7))).toEqual([base]);
  });

  it("keeps query data isolated when the signed-in account changes", async () => {
    let resolveSecond: (value: GameSummary[]) => void = () => {};
    apiRequest.mockResolvedValueOnce([base]).mockImplementationOnce(() => new Promise<GameSummary[]>(resolve => { resolveSecond = resolve; }));
    const { wrapper, auth, queryClient } = await setup();
    expect(wrapper.get(".personal-center-recent-list").text()).toContain("雾港档案");
    auth.setSession({ id: 11, username: "二号调查员" }); await flushPromises();
    expect(wrapper.get(".personal-center-account h3").text()).toBe("二号调查员");
    expect(wrapper.get(".personal-center-avatar").text()).toBe("二");
    expect(wrapper.find(".personal-center-recent-list").exists()).toBe(false);
    expect(wrapper.findAll(".personal-center-stat strong").map(value => value.text())).toEqual(["—", "—", "—"]);
    resolveSecond([]); await flushPromises();
    expect(queryClient.getQueryData(gameRecordsQueryKey(11))).toEqual([]);
    expect(wrapper.get(".personal-center-empty").text()).toContain("暂无案件记录");
  });

  it("delegates shortcuts through existing navigation events and never opens a recent game", async () => {
    apiRequest.mockResolvedValue([base]);
    const navigate = vi.fn(); const openGame = vi.fn();
    cleanups.push(appEvents.on("navigation:view", navigate), appEvents.on("records:open", openGame));
    const { wrapper, router } = await setup();
    for (const button of wrapper.findAll(".personal-center-shortcuts button")) await button.trigger("click");
    await wrapper.get(".personal-center-recent-list h4").trigger("click");
    await wrapper.get(".personal-center-recent-list").trigger("click");
    expect(navigate.mock.calls.map(([value]) => value)).toEqual([{ view: "library" }, { view: "create" }, { view: "records" }]);
    expect(openGame).not.toHaveBeenCalled();
    expect(router.currentRoute.value.name).toBe("personal-center");
    expect(apiRequest.mock.calls.every(([path, options]) => path === "/api/games" && !options?.method)).toBe(true);
  });

  it("signs out through the existing auth action and clears the account session", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      if (path === "/api/games") return [base];
      if (path === "/api/auth/logout") return { ok: true };
      throw new Error(`unexpected request: ${path}`);
    });
    const loggedOut = vi.fn(); cleanups.push(appEvents.on("auth:logout", loggedOut));
    const { wrapper, auth } = await setup();
    await wrapper.get(".personal-center-logout").trigger("click"); await flushPromises();
    expect(apiRequest).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
    expect(auth.user).toBeNull();
    expect(loggedOut).toHaveBeenCalledWith({ preserveReturnPath: false, broadcast: true });
    expect(wrapper.find(".personal-center-recent-list").exists()).toBe(false);
  });
});
