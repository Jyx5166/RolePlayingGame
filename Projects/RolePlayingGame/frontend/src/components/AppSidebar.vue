<script setup lang="ts">
import { Archive, LogOut, PanelLeftClose, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useRoute } from "vue-router";

import { appEvents } from "../app-events";
import { useAuthStore } from "../stores/auth";
import { useUiStore } from "../stores/ui";

const auth = useAuthStore();
const ui = useUiStore();
const route = useRoute();
const username = computed(() => auth.user?.username || "用户");
const avatarInitial = computed(() => username.value.slice(0, 1).toUpperCase());
const avatarStatus = computed(() => (
  ui.gameActive ? "剧本演绎中，正在思考" : auth.user ? "在线" : "离线"
));
const activeView = computed(() => {
  if (route.name === "case-list") return "records";
  if (route.name === "case-create") return "create";
  return "";
});

function navigate(view: "create" | "records"): void {
  appEvents.emit("navigation:view", { view });
}

function collapseSidebar(): void {
  appEvents.emit("sidebar:set", { collapsed: true, focusTarget: true });
}
</script>

<template>
  <div class="sidebar-brand">
    <span class="brand-seal small">剧</span>
    <div><strong>剧镜</strong><span>悬疑推理 MVP</span></div>
  </div>
  <nav aria-label="主要导航">
    <button
      class="nav-button"
      :class="{ active: activeView === 'create' }"
      type="button"
      @click="navigate('create')"
    ><Plus :size="18" aria-hidden="true" />新建案件</button>
    <button
      class="nav-button"
      :class="{ active: activeView === 'records' }"
      type="button"
      @click="navigate('records')"
    ><Archive :size="18" aria-hidden="true" />案件档案</button>
  </nav>
  <div class="mvp-scope">
    <span>当前版本</span>
    <strong>悬疑推理</strong>
    <small>DEDUCTION · MVP</small>
  </div>
  <div class="sidebar-account">
    <div
      id="userAvatar"
      class="avatar account-avatar"
      :class="{ 'is-online': Boolean(auth.user), 'is-thinking': ui.gameActive }"
      role="img"
      :aria-label="`${username}，${avatarStatus}`"
      :title="`${username} · ${avatarStatus}`"
    >
      <i class="account-avatar-aura" aria-hidden="true" />
      <b id="userAvatarInitial" class="account-avatar-initial">{{ avatarInitial }}</b>
      <span class="account-avatar-spectrum" aria-hidden="true"><i /><i /><i /><i /><i /></span>
    </div>
    <div><strong id="currentUsername">{{ username }}</strong><span>本地调查员</span></div>
    <button
      id="collapseSidebarBtn"
      class="icon-button sidebar-toggle-button"
      type="button"
      title="隐藏导航栏"
      aria-label="隐藏导航栏"
      aria-controls="appSidebar"
      :aria-expanded="!ui.sidebarCollapsed"
      @click="collapseSidebar"
    ><PanelLeftClose :size="17" aria-hidden="true" /></button>
    <button
      id="logoutBtn"
      class="icon-button"
      type="button"
      title="退出登录"
      aria-label="退出登录"
      :disabled="auth.status === 'submitting'"
      @click="auth.logout"
    ><LogOut :size="17" aria-hidden="true" /></button>
  </div>
</template>
