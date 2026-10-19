// @vitest-environment happy-dom

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import { appEvents } from "../app-events";
import { useAuthStore } from "../stores/auth";
import { useUiStore } from "../stores/ui";
import AppSidebar from "./AppSidebar.vue";

describe("AppSidebar", () => {
  it("renders store state and delegates legacy workspace actions through typed events", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    const ui = useUiStore();
    auth.setSession({ id: 7, username: "investigator" });
    ui.setGameActive(true);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/cases", name: "case-list", component: { render: () => null } },
        { path: "/cases/new", name: "case-create", component: { render: () => null } },
      ],
    });
    await router.push("/cases/new");
    await router.isReady();

    const onNavigate = vi.fn();
    const onSidebar = vi.fn();
    const stopNavigate = appEvents.on("navigation:view", onNavigate);
    const stopSidebar = appEvents.on("sidebar:set", onSidebar);
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } });

    expect(wrapper.get("#currentUsername").text()).toBe("investigator");
    expect(wrapper.get("#userAvatar").classes()).toContain("is-thinking");
    expect(wrapper.get(".nav-button.active").text()).toContain("新建剧本");

    await wrapper.findAll(".nav-button")[2].trigger("click");
    await wrapper.get('[aria-label="个人中心"]').trigger("click");
    await wrapper.get("#collapseSidebarBtn").trigger("click");
    expect(onNavigate).toHaveBeenCalledWith({ view: "records" });
    expect(onNavigate).toHaveBeenCalledWith({ view: "profile" });
    expect(onSidebar).toHaveBeenCalledWith({ collapsed: true, focusTarget: true });
    ui.setSidebarCollapsed(true);
    await wrapper.vm.$nextTick();
    expect(wrapper.get("#collapseSidebarBtn").attributes("aria-label")).toBe("展开导航栏");
    expect(wrapper.find('[aria-label="新建游戏"]').exists()).toBe(true);
    await wrapper.get("#collapseSidebarBtn").trigger("click");
    expect(onSidebar).toHaveBeenLastCalledWith({ collapsed: false, focusTarget: true });

    stopNavigate();
    stopSidebar();
  });

  it("keeps one library entry selected while browsing and preparing a script", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.setSession({ id: 11, username: "新的调查员" });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/play", name: "script-library", component: { render: () => null } },
        { path: "/personal-center", name: "personal-center", component: { render: () => null } },
        { path: "/play/prepare/:preparationId", name: "game-prepare", component: { render: () => null } },
      ],
    });
    await router.push("/play");
    await router.isReady();
    const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } });

    expect(wrapper.findAll(".nav-button")).toHaveLength(3);
    expect(wrapper.findAll('[aria-label="新建游戏"]')).toHaveLength(1);
    expect(wrapper.get('[aria-current="page"]').attributes("aria-label")).toBe("新建游戏");
    expect(wrapper.get("#currentUsername").text()).toBe("新的调查员");
    expect(wrapper.get("#userAvatarInitial").text()).toBe("新");

    await router.push("/play/prepare/42");
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('[aria-current="page"]')).toHaveLength(1);
    expect(wrapper.get('[aria-current="page"]').attributes("aria-label")).toBe("新建游戏");
    await router.push("/personal-center");
    await wrapper.vm.$nextTick();
    expect(wrapper.get('[aria-current="page"]').attributes("aria-label")).toBe("个人中心");
    expect(wrapper.findAll(".nav-button.active")).toHaveLength(0);
    expect(wrapper.findAll(".nav-button")).toHaveLength(3);
  });
});
