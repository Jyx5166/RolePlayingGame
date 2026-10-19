// @vitest-environment happy-dom

import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { appEvents } from "../app-events";
import { gameRecordsQueryKey } from "../queries/game-records";
import { useAuthStore } from "../stores/auth";
import CaseRecordsView from "./CaseRecordsView.vue";

const apiRequest = vi.hoisted(() => vi.fn());

vi.mock("../runtime", () => ({
  getApiClient: () => ({ request: apiRequest }),
}));

const game = {
  id: 12,
  title: "雾港档案·钟楼夜宴",
  category: "mystery",
  mode: "deduction",
  player_role_id: "reporter",
  ai_agent_count: 3,
  current_stage: 2,
  current_phase: "investigation",
  total_stages: 4,
  status: "playing",
  catalog_script_id: "fog_harbor_clocktower",
  created_at: "2026-08-08T08:00:00Z",
  updated_at: "2026-08-08T09:00:00Z",
};

const cleanups: Array<() => void> = [];

afterEach(() => {
  for (const cleanup of cleanups.splice(0).reverse()) cleanup();
  vi.useRealTimers();
  apiRequest.mockReset();
});

async function mountArchive() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().setSession({ id: 7, username: "investigator" });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/cases", name: "case-list", component: { render: () => null } }],
  });
  await router.push("/cases");
  await router.isReady();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = mount(CaseRecordsView, {
    global: { plugins: [pinia, router, [VueQueryPlugin, { queryClient }]] },
  });
  cleanups.push(() => { wrapper.unmount(); queryClient.clear(); });
  await flushPromises();
  return { wrapper, queryClient };
}

function serveGames(records: Array<typeof game | Record<string, unknown>>) {
  apiRequest.mockImplementation(async (path: string) => {
    if (path === "/api/games") return records;
    throw new Error(`unexpected request: ${path}`);
  });
}

describe("CaseRecordsView", () => {
  it("queries, opens, confirms deletion, and reconciles the archive", async () => {
    let deleted = false;
    apiRequest.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === "/api/games" && !options?.method) return deleted ? [] : [game];
      if (path === `/api/games/${game.id}` && options?.method === "DELETE") {
        deleted = true;
        return { ok: true };
      }
      throw new Error(`unexpected request: ${path}`);
    });

    const onOpen = vi.fn();
    const onDeleted = vi.fn();
    const stopOpen = appEvents.on("records:open", onOpen);
    const stopDeleted = appEvents.on("records:deleted", onDeleted);
    cleanups.push(stopOpen, stopDeleted);

    const { wrapper } = await mountArchive();

    expect(wrapper.get(".case-archive-title").text()).toBe(game.title);
    expect(wrapper.get(".case-archive-card").text()).toContain("悬疑推理");
    expect(wrapper.get(".case-archive-card").text()).toContain("2/4");

    await wrapper.get(".case-archive-open").trigger("click");
    expect(onOpen).toHaveBeenCalledWith({ gameId: game.id });

    const deleteButton = wrapper.get(".case-archive-delete");
    await deleteButton.trigger("click");
    expect(deleteButton.text()).toContain("确认删除");
    expect(apiRequest).not.toHaveBeenCalledWith(
      `/api/games/${game.id}`,
      expect.objectContaining({ method: "DELETE" }),
    );

    await deleteButton.trigger("click");
    await flushPromises();
    expect(apiRequest).toHaveBeenCalledWith(
      `/api/games/${game.id}`,
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(onDeleted).toHaveBeenCalledWith({ gameId: game.id, title: game.title });
    expect(wrapper.find(".case-archive-card").exists()).toBe(false);
    expect(wrapper.text()).toContain("暂无游戏记录");

  });

  it("uses catalog IDs for covers and falls back without guessing from a title", async () => {
    serveGames([
      { ...game, id: 13, title: "重新命名的故事", catalog_script_id: "last_train" },
      { ...game, id: 14, title: "末班列车", catalog_script_id: null },
      { ...game, id: 15, title: "无声剧院", catalog_script_id: "imported-catalog-uuid" },
    ]);
    const { wrapper } = await mountArchive();
    const images = wrapper.findAll(".case-archive-cover img");
    expect(images.map((image) => image.attributes("src"))).toEqual([
      "/static/assets/script-covers/last-train.png",
      "/static/assets/noir-case-desk.png",
      "/static/assets/noir-case-desk.png",
    ]);
    expect(apiRequest.mock.calls.every(([path]) => path === "/api/games")).toBe(true);
  });

  it("shows real preparation, opening, private, and completed states", async () => {
    serveGames([
      { ...game, id: 21, status: "preparing", current_phase: "preparing", current_stage: 1 },
      { ...game, id: 22, status: "paused", current_phase: "opening", current_stage: 1 },
      { ...game, id: 23, status: "paused", current_phase: "private_reveal", current_stage: 1 },
      { ...game, id: 24, status: "completed", current_phase: "replay", current_stage: 4 },
    ]);
    const { wrapper } = await mountArchive();
    expect(wrapper.get('[data-game-id="21"]').text()).toContain("待选角色");
    const opening = wrapper.get('[data-game-id="22"]');
    expect(opening.text()).toContain("已暂停");
    expect(opening.text()).toContain("故事开幕 · 共 4 幕");
    expect(opening.text()).not.toContain("第一幕");
    expect(opening.text()).not.toContain("1/4");
    expect(wrapper.get('[data-game-id="23"]').text()).toContain("角色剧本 · 共 4 幕");
    const completed = wrapper.get('[data-game-id="24"]');
    expect(completed.text()).toContain("已完成");
    expect(completed.text()).toContain("4/4");
    expect(completed.get(".case-archive-open").text()).toBe("查看");
  });

  it("keeps abandoned records disabled without disabling their deletion", async () => {
    serveGames([{ ...game, status: "abandoned", current_phase: "preparing" }]);
    const onOpen = vi.fn();
    cleanups.push(appEvents.on("records:open", onOpen));
    const { wrapper } = await mountArchive();
    const open = wrapper.get(".case-archive-open");
    expect(open.attributes("disabled")).toBeDefined();
    expect(open.text()).toBe("已取消");
    await open.trigger("click");
    expect(onOpen).not.toHaveBeenCalled();
    const remove = wrapper.get(".case-archive-delete");
    expect(remove.attributes("disabled")).toBeUndefined();
    await remove.trigger("click");
    expect(remove.text()).toContain("确认删除");
  });

  it("restores an optimistically removed card when deletion fails", async () => {
    let rejectDelete!: (reason: Error) => void;
    const pendingDelete = new Promise<never>((_resolve, reject) => { rejectDelete = reject; });
    let reads = 0;
    apiRequest.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === "/api/games") return ++reads === 1 ? [game] : new Promise(() => {});
      if (path === `/api/games/${game.id}` && options?.method === "DELETE") return pendingDelete;
      throw new Error(`unexpected request: ${path}`);
    });
    const onDeleted = vi.fn();
    const onToast = vi.fn();
    cleanups.push(appEvents.on("records:deleted", onDeleted), appEvents.on("toast:show", onToast));
    const { wrapper } = await mountArchive();
    await wrapper.get(".case-archive-delete").trigger("click");
    await wrapper.get(".case-archive-delete").trigger("click");
    await flushPromises();
    expect(wrapper.find(".case-archive-card").exists()).toBe(false);
    rejectDelete(new Error("删除失败，请重试"));
    await flushPromises();
    expect(wrapper.get(".case-archive-title").text()).toBe(game.title);
    expect(onToast).toHaveBeenCalledWith({ message: "删除失败，请重试" });
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("expires delete confirmation and clears it when refreshing", async () => {
    serveGames([game]);
    const { wrapper } = await mountArchive();
    vi.useFakeTimers();
    await wrapper.get(".case-archive-delete").trigger("click");
    expect(wrapper.get(".case-archive-delete").text()).toContain("确认删除");
    await vi.advanceTimersByTimeAsync(3200);
    expect(wrapper.get(".case-archive-delete").text()).toBe("删除");
    await wrapper.get(".case-archive-delete").trigger("click");
    await wrapper.get("#refreshRecordsBtn").trigger("click");
    await flushPromises();
    expect(wrapper.get(".case-archive-delete").text()).toBe("删除");
    expect(apiRequest.mock.calls.filter(([path]) => path === "/api/games")).toHaveLength(2);
  });

  it("shows loading and allows a failed archive read to be retried", async () => {
    let rejectRead!: (reason: Error) => void;
    const pendingRead = new Promise<never>((_resolve, reject) => { rejectRead = reject; });
    apiRequest.mockReturnValueOnce(pendingRead).mockResolvedValue([game]);
    const { wrapper } = await mountArchive();
    expect(wrapper.get(".case-archive-message").text()).toContain("正在读取记录");
    expect(wrapper.get("#recordsList").attributes("aria-busy")).toBe("true");
    rejectRead(new Error("档案暂时无法读取"));
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("档案暂时无法读取");
    await wrapper.get(".case-archive-retry").trigger("click");
    await flushPromises();
    expect(wrapper.get(".case-archive-title").text()).toBe(game.title);
  });

  it("invalidates the authenticated archive on the existing records event", async () => {
    serveGames([game]);
    const { queryClient } = await mountArchive();
    appEvents.emit("records:invalidate", {});
    await flushPromises();
    expect(queryClient.getQueryState(gameRecordsQueryKey(7))?.isInvalidated).toBe(true);
    expect(apiRequest).toHaveBeenCalledTimes(1);
  });
});
