import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia, setActivePinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { mountLegacyApp } from "./legacy-app.js";
import { createAppRouter } from "./router";
import { initializeFrontendRuntime } from "./runtime";
import { useAuthStore } from "./stores/auth";

const pinia = createPinia();
setActivePinia(pinia);
const router = createAppRouter();
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
    mutations: { retry: 0 },
  },
});
const authStore = useAuthStore();
initializeFrontendRuntime(authStore, router);

const app = createApp(App);
app.use(pinia);
app.use(router);
app.use(VueQueryPlugin, { queryClient });
app.mount("#vueRoot");

router.isReady().then(() => mountLegacyApp());
