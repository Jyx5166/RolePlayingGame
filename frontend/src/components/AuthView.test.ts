// @vitest-environment happy-dom

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it } from "vitest";

import AuthView from "./AuthView.vue";

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/login", name: "login", component: { render: () => null } },
      { path: "/register", name: "register", component: { render: () => null } },
    ],
  });
}

describe("AuthView", () => {
  it("derives the selected auth mode and password semantics from the URL", async () => {
    const router = createTestRouter();
    await router.push("/register");
    await router.isReady();

    const wrapper = mount(AuthView, {
      global: { plugins: [createPinia(), router] },
    });

    expect(wrapper.get("#registerTab").attributes("aria-selected")).toBe("true");
    expect(wrapper.get("#passwordInput").attributes("autocomplete")).toBe("new-password");
    expect(wrapper.get("#authSubmit").text()).toBe("创建账户");

    await wrapper.get("#loginTab").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/login");
    expect(wrapper.get("#passwordInput").attributes("autocomplete")).toBe("current-password");
    expect(wrapper.get("#registerTab").attributes("tabindex")).toBe("-1");
    await wrapper.get("#loginTab").trigger("keydown", { key: "ArrowRight" });
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/register");
    expect(wrapper.get("#authModePanel").attributes("aria-labelledby")).toBe("registerTab");
    await wrapper.get("#registerTab").trigger("keydown", { key: "Home" });
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/login");
    wrapper.unmount();
  });
});
