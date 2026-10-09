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
    expect(wrapper.get(".nav-button.active").text()).toContain("新建案件");

    await wrapper.findAll(".nav-button")[1].trigger("click");
    await wrapper.get("#collapseSidebarBtn").trigger("click");
    expect(onNavigate).toHaveBeenCalledWith({ view: "records" });
    expect(onSidebar).toHaveBeenCalledWith({ collapsed: true, focusTarget: true });

    stopNavigate();
    stopSidebar();
  });
});
