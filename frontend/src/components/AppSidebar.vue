<script setup lang="ts">
import { BookOpen, FilePlus, FolderArchive, LogOut, PanelLeftClose, PanelLeftOpen } from "@lucide/vue";
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
  if (["case-create", "script-create"].includes(String(route.name))) return "create";
  if (["script-library", "game-prepare"].includes(String(route.name))) return "library";
  return "";
});

function navigate(view: "create" | "records" | "library" | "profile"): void {
  appEvents.emit("navigation:view", { view });
}

function collapseSidebar(): void {
  appEvents.emit("sidebar:set", { collapsed: !ui.sidebarCollapsed, focusTarget: true });
}
</script>

<template>
  <div class="sidebar-brand">
    <span class="brand-seal brand-logo small">
      <img :src="'/static/assets/jujing-logo-original.jpg'" alt="剧镜游戏 Logo" width="1280" height="1280" decoding="async" draggable="false" />
    </span>
    <div class="sidebar-label"><strong>剧镜</strong><span>悬疑推理</span></div>
  </div>
  <nav aria-label="主要导航">
    <button class="nav-button" :class="{ active: activeView === 'library' }" :aria-current="activeView === 'library' ? 'page' : undefined" type="button" title="新建游戏" aria-label="新建游戏" @click="navigate('library')"><BookOpen :size="20" aria-hidden="true" /><span class="sidebar-label">新建游戏</span></button>
    <button
      class="nav-button"
      :class="{ active: activeView === 'create' }"
      :aria-current="activeView === 'create' ? 'page' : undefined"
      type="button"
      title="新建剧本"
      aria-label="新建剧本"
      @click="navigate('create')"
    ><FilePlus :size="20" aria-hidden="true" /><span class="sidebar-label">新建剧本</span></button>
    <button
      class="nav-button"
      :class="{ active: activeView === 'records' }"
      :aria-current="activeView === 'records' ? 'page' : undefined"
      type="button"
      title="案件档案"
      aria-label="案件档案"
      @click="navigate('records')"
    ><FolderArchive :size="20" aria-hidden="true" /><span class="sidebar-label">案件档案</span></button>
  </nav>
  <div class="sidebar-account">
    <button
      id="userAvatar"
      class="avatar account-avatar personal-center-trigger"
      :class="{ 'is-online': Boolean(auth.user), 'is-thinking': ui.gameActive, 'is-active': route.name === 'personal-center' }"
      type="button"
      aria-label="个人中心"
      :aria-current="route.name === 'personal-center' ? 'page' : undefined"
      :title="`${username} · 个人中心 · ${avatarStatus}`"
      @click="navigate('profile')"
    >
      <i class="account-avatar-aura" aria-hidden="true" />
      <b id="userAvatarInitial" class="account-avatar-initial">{{ avatarInitial }}</b>
      <span class="account-avatar-spectrum" aria-hidden="true"><i /><i /><i /><i /><i /></span>
    </button>
    <div class="sidebar-label"><strong id="currentUsername">{{ username }}</strong><span>个人中心</span></div>
    <button
      id="collapseSidebarBtn"
      class="icon-button sidebar-toggle-button"
      type="button"
      :title="ui.sidebarCollapsed ? '展开导航栏' : '收起导航栏'"
      :aria-label="ui.sidebarCollapsed ? '展开导航栏' : '收起导航栏'"
      aria-controls="appSidebar"
      :aria-expanded="!ui.sidebarCollapsed"
      @click="collapseSidebar"
    ><PanelLeftOpen v-if="ui.sidebarCollapsed" :size="17" aria-hidden="true" /><PanelLeftClose v-else :size="17" aria-hidden="true" /></button>
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
