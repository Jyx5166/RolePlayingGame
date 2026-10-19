// @vitest-environment happy-dom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { appEvents } from "../app-events";
import type { CatalogScript } from "../scripts";
import { useAuthStore } from "../stores/auth";
import ScriptLibraryView from "./ScriptLibraryView.vue";

const apiRequest = vi.hoisted(() => vi.fn());
vi.mock("../runtime", () => ({ getApiClient: () => ({ request: apiRequest }) }));
const scripts: CatalogScript[] = [
  { catalog_id: "rainy_night_letter", script_id: "rainy_night_letter", version: "v1", title: "雨夜来信", source: "builtin", tags: ["悬疑", "身份"], role_count: 3, total_stages: 2, ai_agent_count: 2, story_background: "雨夜一封信，让三位故人重聚。", playable_roles: [{ role_id: "rnl_qin_he", role_name: "秦禾", public_identity: "收到信的记者" }] },
  { catalog_id: "silent_theater", script_id: "silent_theater", version: "v1", title: "无声剧院", source: "builtin", tags: ["推理"], role_count: 6, total_stages: 4, ai_agent_count: 5, story_background: "演出结束，真相尚未谢幕。", playable_roles: [{ role_id: "shen_yi", role_name: "沈奕", public_identity: "剧团演员" }] },
  { catalog_id: "my-script", script_id: "custom-script", version: "v2", title: "我的雨夜", source: "imported", tags: ["悬疑"], role_count: 2, total_stages: 1, ai_agent_count: 1, story_background: "自创故事。", playable_roles: [{ role_id: "custom-role", role_name: "林音", public_identity: "钢琴家" }] },
];
const cleanups: (() => void)[] = [];

async function setup(path = "/play", attached = false) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().setSession({ id: 7, username: "investigator" });
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/play", name: "script-library", component: { render: () => null } },
    { path: "/scripts/new", name: "script-create", component: { render: () => null } },
    { path: "/games/:gameId/prepare", name: "game-prepare", component: { render: () => null } },
  ] });
  await router.push(path);
  await router.isReady();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement("div");
  if (attached) document.body.append(host);
  const wrapper = mount(ScriptLibraryView, { attachTo: attached ? host : undefined, global: { plugins: [pinia, router, [VueQueryPlugin, { queryClient }]] } });
  cleanups.push(() => { wrapper.unmount(); host.remove(); queryClient.clear(); });
  await flushPromises();
  return { wrapper, router };
}
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); apiRequest.mockReset(); });

describe("ScriptLibraryView", () => {
  it("renders actual role and stage counts across the real catalog", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper } = await setup();
    const cards = wrapper.findAll(".case-browser-row");
    expect(cards).toHaveLength(3);
    expect(cards[0].get(".case-browser-row-meta").text()).toBe("3 位角色2 幕故事");
    expect(cards[1].get(".case-browser-row-meta").text()).toBe("6 位角色4 幕故事");
    expect(cards[2].get(".case-browser-row-meta").text()).toBe("2 位角色1 幕故事");
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("雨夜来信");
    expect(wrapper.get(".case-browser-cast figcaption").text()).toBe("秦禾");
    expect(wrapper.get(".case-browser-cast img").attributes("src")).toContain("portrait-01.png");
  });

  it("switches the selected preview without entering details or creating a game", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper, router } = await setup();
    await wrapper.findAll(".case-browser-row-button")[1].trigger("click");
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("无声剧院");
    expect(wrapper.get(".case-browser-synopsis").text()).toBe("演出结束，真相尚未谢幕。");
    expect(wrapper.get(".case-browser-preview-meta").text()).toBe("6 位角色4 幕故事");
    expect(wrapper.get(".case-browser-cast figcaption").text()).toBe("沈奕");
    expect(wrapper.findAll(".case-browser-row-button")[1].attributes("aria-pressed")).toBe("true");
    expect(router.currentRoute.value.query.script).toBeUndefined();
    expect(wrapper.find(".detail-story").exists()).toBe(false);
    expect(apiRequest.mock.calls.every(([, options]) => !options?.method)).toBe(true);
    await wrapper.get(".case-browser-details").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.script).toBe("silent_theater");
    await wrapper.get(".detail-breadcrumb button").trigger("click");
    await flushPromises();
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("无声剧院");
  });

  it("scrolls and focuses between preview and list on mobile while respecting reduced motion", async () => {
    apiRequest.mockResolvedValue(scripts);
    let compact = false;
    const media = vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: compact && (query.includes("max-width") || query.includes("prefers-reduced-motion")),
      media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    }));
    const previousScroll = HTMLElement.prototype.scrollIntoView;
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    cleanups.push(() => { media.mockRestore(); focus.mockRestore(); HTMLElement.prototype.scrollIntoView = previousScroll; });
    const { wrapper } = await setup();
    await wrapper.findAll(".case-browser-row-button")[1].trigger("click");
    await flushPromises();
    expect(scroll).not.toHaveBeenCalled();
    compact = true;
    await wrapper.findAll(".case-browser-row-button")[0].trigger("click");
    await flushPromises();
    expect(scroll).toHaveBeenLastCalledWith({ behavior: "auto", block: "start" });
    expect(scroll.mock.contexts.at(-1)).toBe(wrapper.get("#scriptPreviewHeading").element);
    expect(focus.mock.contexts.at(-1)).toBe(wrapper.get("#scriptPreviewHeading").element);
    await wrapper.get(".case-browser-back-to-list").trigger("click");
    expect(scroll.mock.contexts.at(-1)).toBe(wrapper.get(".case-browser-list").element);
    expect(focus.mock.contexts.at(-1)).toBe(wrapper.get(".case-browser-list").element);
  });

  it("preserves a visible selection and synchronizes the preview when filters hide it", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper, router } = await setup();
    await wrapper.findAll(".case-browser-row-button")[1].trigger("click");
    await wrapper.findAll(".case-browser-source-tabs button")[1].trigger("click");
    await flushPromises();
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("无声剧院");
    await wrapper.get(".case-browser-more-trigger").trigger("click");
    await wrapper.findAll('[role="option"]').find((option) => option.text() === "身份")!.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.tag).toBe("身份");
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(1);
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("雨夜来信");
    await wrapper.findAll(".case-browser-source-tabs button")[2].trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("没有匹配的剧本");
    expect(wrapper.find(".case-browser-preview").exists()).toBe(false);
  });

  it("restores a selected extra type from the URL and resets it without losing other filters", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper, router } = await setup("/play?source=builtin&tag=身份&order=title", true);
    const trigger = wrapper.get(".case-browser-more-trigger");
    expect(trigger.text()).toBe("身份");
    expect(trigger.classes()).toContain("active");
    expect(trigger.attributes("aria-haspopup")).toBe("listbox");
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find(".case-browser-more select").exists()).toBe(false);
    await trigger.trigger("click");
    await flushPromises();
    const list = wrapper.get('[role="listbox"]');
    expect(document.activeElement).toBe(list.element);
    expect(list.get('[aria-selected="true"]').text()).toBe("身份");
    expect(document.getElementById(list.attributes("aria-activedescendant")!)?.textContent).toBe("身份");
    const reset = wrapper.findAll('[role="option"]').find((option) => option.text() === "全部类型")!;
    await reset.trigger("pointerdown");
    await reset.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ source: "builtin", order: "title" });
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false);
    expect(trigger.text()).toBe("更多");
    expect(trigger.classes()).not.toContain("active");
    expect(document.activeElement).toBe(trigger.element);
    expect(wrapper.get('.case-browser-genres > button').attributes("aria-pressed")).toBe("true");
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(2);
  });

  it("supports arrow, Home, End, Enter and Space selection without changing the URL while browsing", async () => {
    apiRequest.mockResolvedValue([{ ...scripts[0], tags: ["悬疑", "身份", "情感"] }, ...scripts.slice(1)]);
    const previousScroll = HTMLElement.prototype.scrollIntoView;
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    cleanups.push(() => { HTMLElement.prototype.scrollIntoView = previousScroll; });
    const { wrapper, router } = await setup("/play?source=builtin&order=title", true);
    const trigger = wrapper.get(".case-browser-more-trigger");
    await trigger.trigger("keydown", { key: "ArrowDown" });
    await flushPromises();
    let list = wrapper.get('[role="listbox"]');
    await list.trigger("keydown", { key: "ArrowDown" });
    expect(document.getElementById(list.attributes("aria-activedescendant")!)?.textContent).toBe("身份");
    expect(router.currentRoute.value.query.tag).toBeUndefined();
    await list.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ source: "builtin", order: "title", tag: "身份" });
    expect(document.activeElement).toBe(trigger.element);

    await trigger.trigger("keydown", { key: "ArrowUp" });
    await flushPromises();
    list = wrapper.get('[role="listbox"]');
    expect(list.get('[aria-selected="true"]').text()).toBe("身份");
    await list.trigger("keydown", { key: "End" });
    expect(document.getElementById(list.attributes("aria-activedescendant")!)?.textContent).toBe("情感");
    await list.trigger("keydown", { key: " " });
    await flushPromises();
    expect(router.currentRoute.value.query.tag).toBe("情感");
    await trigger.trigger("click");
    await wrapper.get('[role="listbox"]').trigger("keydown", { key: "Home" });
    await wrapper.get('[role="listbox"]').trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(router.currentRoute.value.query.tag).toBeUndefined();
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("dismisses the extra types with Escape, outside pointer input, and focus leaving the filter", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper, router } = await setup("/play?tag=身份", true);
    const trigger = wrapper.get(".case-browser-more-trigger");
    await trigger.trigger("click");
    await wrapper.get('[role="listbox"]').trigger("keydown", { key: "Escape" });
    await flushPromises();
    expect(trigger.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger.element);
    expect(router.currentRoute.value.query.tag).toBe("身份");
    await trigger.trigger("click");
    document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    await flushPromises();
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false);
    await trigger.trigger("click");
    (wrapper.get(".case-browser-sort select").element as HTMLSelectElement).focus();
    await flushPromises();
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get(".case-browser-sort select").element);
    expect(router.currentRoute.value.query.tag).toBe("身份");
  });

  it("clears a preview while a new search is loading and after that search fails", async () => {
    let rejectSearch: (reason: Error) => void = () => {};
    apiRequest.mockImplementation((path: string) => path.endsWith("q=") ? Promise.resolve(scripts) : new Promise((_, reject) => { rejectSearch = reject; }));
    const { wrapper } = await setup();
    expect(wrapper.find(".case-browser-preview").exists()).toBe(true);
    await wrapper.get('input[type="search"]').setValue("无结果");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("正在读取剧本");
    expect(wrapper.find(".case-browser-preview").exists()).toBe(false);
    rejectSearch(new Error("读取失败"));
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("读取失败");
    expect(wrapper.find(".case-browser-preview").exists()).toBe(false);
  });

  it("keeps the selected script across a pending search when it remains in the response", async () => {
    let resolveSearch: (value: CatalogScript[]) => void = () => {};
    apiRequest.mockImplementation((path: string) => path.endsWith("q=") ? Promise.resolve(scripts) : new Promise<CatalogScript[]>((resolve) => { resolveSearch = resolve; }));
    const { wrapper } = await setup();
    await wrapper.findAll(".case-browser-row-button")[1].trigger("click");
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("无声剧院");
    await wrapper.get('input[type="search"]').setValue("共同题材");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.find(".case-browser-preview").exists()).toBe(false);
    resolveSearch(scripts.slice(0, 2));
    await flushPromises();
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(2);
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("无声剧院");
    expect(wrapper.findAll(".case-browser-row-button")[1].attributes("aria-pressed")).toBe("true");
  });

  it("selects from the new search results and removes the preview for an empty result", async () => {
    apiRequest.mockImplementation(async (path: string) => {
      const term = new URL(path, "http://localhost").searchParams.get("q") || "";
      return scripts.filter((script) => script.title.includes(term));
    });
    const { wrapper, router } = await setup();
    await wrapper.get('input[type="search"]').setValue("剧院");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(router.currentRoute.value.query.q).toBe("剧院");
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(1);
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("无声剧院");
    await wrapper.get('input[type="search"]').setValue("不存在");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(0);
    expect(wrapper.find(".case-browser-preview").exists()).toBe(false);
    expect(wrapper.text()).toContain("没有匹配的剧本");
  });

  it("keeps the imported script edit action available in the list", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper, router } = await setup("/play?source=imported");
    expect(wrapper.get(".case-browser-preview-title").text()).toBe("我的雨夜");
    await wrapper.get(".case-browser-edit").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("script-create");
    expect(router.currentRoute.value.query.edit).toBe("my-script");
    expect(apiRequest.mock.calls.some(([, options]) => options?.method)).toBe(false);
  });

  it("opens details without creating a game and restores filters on return and browser history", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper, router } = await setup("/play?source=builtin&tag=悬疑&order=title");
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(1);
    await wrapper.get(".case-browser-details").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.script).toBe("rainy_night_letter");
    expect(wrapper.get(".detail-story").text()).toContain("雨夜来信");
    expect(wrapper.get(".detail-character").text()).toContain("秦禾");
    expect(wrapper.get(".detail-numbers").text()).toContain("3 位角色");
    expect(apiRequest.mock.calls.every(([, options]) => !options?.method)).toBe(true);
    await wrapper.get(".detail-breadcrumb button").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ source: "builtin", tag: "悬疑", order: "title" });
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(1);
    router.back();
    await flushPromises();
    expect(wrapper.find(".detail-story").exists()).toBe(true);
    router.forward();
    await flushPromises();
    expect(wrapper.findAll(".case-browser-row")).toHaveLength(1);
  });

  it("supports imported script deep links, portrait fallback, and the existing edit action", async () => {
    apiRequest.mockResolvedValue(scripts);
    const { wrapper, router } = await setup("/play?script=my-script");
    expect(wrapper.get(".detail-story").text()).toContain("我的雨夜");
    expect(wrapper.get(".detail-character strong").text()).toBe("林音");
    expect(wrapper.get(".detail-character img").attributes("src")).toMatch(/portraits\/portrait-\d+\.png$/);
    await wrapper.get(".detail-story .catalog-edit").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("script-create");
    expect(router.currentRoute.value.query.edit).toBe("my-script");
    expect(apiRequest.mock.calls.some(([, options]) => options?.method)).toBe(false);
  });

  it("resolves a refreshed detail link even when its search would hide that script", async () => {
    apiRequest.mockImplementation(async (path: string) => path.includes("q=unrelated") ? [] : scripts);
    const { wrapper } = await setup("/play?q=unrelated&script=my-script");
    await flushPromises();
    expect(wrapper.get(".detail-story").text()).toContain("我的雨夜");
    expect(apiRequest.mock.calls.some(([path]) => path === "/api/v1/scripts?q=")).toBe(true);
  });

  it("searches by keyword and creates a preparation only on choose-role, preserving retry identity", async () => {
    let failed = false;
    apiRequest.mockImplementation(async (path: string, options?: RequestInit) => {
      if (!options?.method) return scripts;
      if (path === "/api/v1/game-preparations") {
        if (!failed) { failed = true; throw new Error("连接中断，请重试"); }
        return { id: 12 };
      }
      throw new Error(`unexpected request: ${path}`);
    });
    const { wrapper, router } = await setup("/play?source=builtin&tag=悬疑&order=title");
    await wrapper.get('input[type="search"]').setValue("雨夜");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(apiRequest.mock.calls.some(([path]) => path === `/api/v1/scripts?q=${encodeURIComponent("雨夜")}`)).toBe(true);
    await wrapper.get(".case-browser-details").trigger("click");
    await flushPromises();
    const entered = vi.fn();
    cleanups.push(appEvents.on("games:prepare", entered));
    expect(apiRequest.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    await wrapper.get(".detail-choose").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("连接中断，请重试");
    expect(entered).not.toHaveBeenCalled();
    await wrapper.get(".detail-choose").trigger("click");
    await flushPromises();
    const bodies = apiRequest.mock.calls.filter(([path]) => path === "/api/v1/game-preparations").map(([, options]) => JSON.parse(String(options.body)));
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toEqual(bodies[1]);
    expect(bodies[0]).toMatchObject({ catalog_id: "rainy_night_letter", version: "v1" });
    expect(entered).toHaveBeenCalledWith({ gameId: 12 });
    expect(router.currentRoute.value.name).toBe("game-prepare");
    const from = router.resolve(String(router.currentRoute.value.query.from));
    expect(from.path).toBe("/play");
    expect(from.query).toMatchObject({ q: "雨夜", source: "builtin", tag: "悬疑", order: "title", script: "rainy_night_letter" });
    expect(apiRequest.mock.calls.some(([path]) => path.includes("/activate"))).toBe(false);
  });
});
