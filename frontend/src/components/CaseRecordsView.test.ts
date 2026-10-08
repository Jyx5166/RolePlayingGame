// @vitest-environment happy-dom

import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import { appEvents } from "../app-events";
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
  created_at: "2026-08-08T08:00:00Z",
  updated_at: "2026-08-08T09:00:00Z",
};

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
    const onOpen = vi.fn();
    const onDeleted = vi.fn();
    const onNavigate = vi.fn();
    const stopOpen = appEvents.on("records:open", onOpen);
    const stopDeleted = appEvents.on("records:deleted", onDeleted);
    const stopNavigate = appEvents.on("navigation:view", onNavigate);

    const wrapper = mount(CaseRecordsView, {
      global: {
        plugins: [pinia, router, [VueQueryPlugin, { queryClient }]],
      },
    });
    await flushPromises();

    expect(wrapper.get(".record-title strong").text()).toBe(game.title);
    expect(wrapper.get(".record-row").text()).toContain("悬疑推理");
    expect(wrapper.get(".record-row").text()).toContain("2/4");

    await wrapper.get(".record-actions .secondary-button").trigger("click");
    expect(onOpen).toHaveBeenCalledWith({ gameId: game.id });

    const deleteButton = wrapper.get(".record-delete-button");
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
    expect(wrapper.find(".record-row").exists()).toBe(false);
    expect(wrapper.text()).toContain("暂无游戏记录");
    await wrapper.get(".records-empty-state .primary-button").trigger("click");
    expect(onNavigate).toHaveBeenCalledWith({ view: "create" });

    wrapper.unmount();
    queryClient.clear();
    stopOpen();
    stopDeleted();
    stopNavigate();
    apiRequest.mockReset();
  });
});
