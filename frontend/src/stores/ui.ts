import { defineStore } from "pinia";

export const useUiStore = defineStore("ui", {
  state: () => ({
    sidebarCollapsed: false,
    gameActive: false,
  }),
  actions: {
    setSidebarCollapsed(collapsed: boolean): void {
      this.sidebarCollapsed = collapsed;
    },
    setGameActive(active: boolean): void {
      this.gameActive = active;
    },
  },
});

export type UiStore = ReturnType<typeof useUiStore>;
