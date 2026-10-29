// @vitest-environment happy-dom

import { randomUUID } from "node:crypto";
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
  });

  it("reveals the password without submitting and hides it when changing modes", async () => {
    const password = randomUUID();
    const router = createTestRouter();
    await router.push("/login");
    await router.isReady();
    const wrapper = mount(AuthView, {
      global: { plugins: [createPinia(), router] },
    });

    await wrapper.get("#passwordInput").setValue(password);
    const toggle = wrapper.get(".auth-password-toggle");
    expect(toggle.attributes("type")).toBe("button");
    await toggle.trigger("click");
    expect(wrapper.get("#passwordInput").attributes("type")).toBe("text");
    expect(toggle.attributes("aria-label")).toBe("隐藏密码");
    expect(toggle.attributes("aria-pressed")).toBe("true");

    await wrapper.get("#registerTab").trigger("click");
    await flushPromises();
    expect(wrapper.get("#passwordInput").attributes("type")).toBe("password");
    expect((wrapper.get("#passwordInput").element as HTMLInputElement).value).toBe(password);
  });
});
