import type { Router } from "vue-router";

import { createApiClient, type ApiClient } from "./api-client";
import { appEvents } from "./app-events";
import { createBrowserRouter } from "./router";
import type { AuthStore } from "./stores/auth";

let apiClient: ApiClient | null = null;
let navigation: ReturnType<typeof createBrowserRouter> | null = null;

export function initializeFrontendRuntime(authStore: AuthStore, router: Router): void {
  navigation = createBrowserRouter(router);
  apiClient = createApiClient({
    getCsrfToken: () => authStore.csrfToken,
    onUnauthorized: (requestPath) => {
      if (requestPath.includes("/auth/login") || requestPath.includes("/auth/register")) return;
      authStore.clearSession();
      appEvents.emit("auth:logout", { preserveReturnPath: true, broadcast: false });
    },
  });
}

export function getApiClient(): ApiClient {
  if (!apiClient) throw new Error("前端 API runtime 尚未初始化");
  return apiClient;
}

export function getNavigation() {
  if (!navigation) throw new Error("前端 Router runtime 尚未初始化");
  return navigation;
}
