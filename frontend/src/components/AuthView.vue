<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const username = ref("");
const password = ref("");
const loginTab = ref<HTMLButtonElement | null>(null);
const registerTab = ref<HTMLButtonElement | null>(null);
const mode = computed<"login" | "register">(() => (
  route.name === "register" ? "register" : "login"
));
const submitting = computed(() => auth.status === "submitting");

watch(mode, () => {
  auth.error = "";
});

async function selectMode(nextMode: "login" | "register"): Promise<void> {
  await router.push({ name: nextMode });
}

async function handleModeKeydown(event: KeyboardEvent): Promise<void> {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const nextMode = event.key === "Home" ? "login"
    : event.key === "End" ? "register"
      : mode.value === "login" ? "register" : "login";
  await selectMode(nextMode);
  (nextMode === "login" ? loginTab.value : registerTab.value)?.focus();
}

async function submit(): Promise<void> {
  await auth.authenticate(mode.value, username.value, password.value);
  if (auth.status === "authenticated") password.value = "";
}
</script>

<template>
  <section class="auth-scene">
    <div class="auth-brand">
      <div class="brand-lockup">
        <span class="brand-seal">剧</span>
        <span>悬疑推理</span>
      </div>
      <div class="auth-copy">
        <h1>剧镜</h1>
        <p class="auth-lead">每一份证词，都藏着另一面真相。</p>
      </div>
      <div class="scene-status">
        <span>独自入局</span>
        <span>多角色演绎</span>
        <span>案件随时续查</span>
      </div>
    </div>
  </section>

  <section class="auth-panel">
    <div class="auth-panel-inner">
      <h2>进入调查室</h2>
      <p class="auth-subtitle">登录后继续你的案件，或建立新的调查员档案。</p>
      <div class="auth-tabs" role="tablist" aria-label="账户操作">
        <button
          id="loginTab"
          ref="loginTab"
          class="tab-button"
          :class="{ active: mode === 'login' }"
          type="button"
          role="tab"
          :aria-selected="mode === 'login'"
          :tabindex="mode === 'login' ? 0 : -1"
          aria-controls="authModePanel"
          @click="selectMode('login')"
          @keydown="handleModeKeydown"
        >登录</button>
        <button
          id="registerTab"
          ref="registerTab"
          class="tab-button"
          :class="{ active: mode === 'register' }"
          type="button"
          role="tab"
          :aria-selected="mode === 'register'"
          :tabindex="mode === 'register' ? 0 : -1"
          aria-controls="authModePanel"
          @click="selectMode('register')"
          @keydown="handleModeKeydown"
        >注册</button>
      </div>
      <div id="authModePanel" role="tabpanel" :aria-labelledby="mode === 'login' ? 'loginTab' : 'registerTab'">
        <form id="authForm" @submit.prevent="submit">
          <label>
            <span>调查员代号</span>
            <input
              id="usernameInput"
              v-model="username"
              autocomplete="username"
              minlength="3"
              maxlength="32"
              placeholder="输入用户名"
              :disabled="submitting"
              required
            />
          </label>
          <label>
            <span>访问密码</span>
            <input
              id="passwordInput"
              v-model="password"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              minlength="6"
              placeholder="至少 6 位"
              :disabled="submitting"
              required
            />
          </label>
          <p id="authError" class="form-error" aria-live="polite">{{ auth.error }}</p>
          <button id="authSubmit" class="primary-button wide" type="submit" :disabled="submitting">
            {{ submitting ? "处理中" : mode === "login" ? "登录" : "创建账户" }}
          </button>
        </form>
      </div>
      <p class="local-note"><span>●</span>账户与案件记录保存在本机</p>
    </div>
  </section>
</template>
