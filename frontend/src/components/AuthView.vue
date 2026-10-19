<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Eye, EyeOff, LockKeyhole, UserRound } from "@lucide/vue";

import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const username = ref("");
const password = ref("");
const showPassword = ref(false);
const mode = computed<"login" | "register">(() => (
  route.name === "register" ? "register" : "login"
));
const submitting = computed(() => auth.status === "submitting");

watch(mode, () => {
  auth.error = "";
  showPassword.value = false;
});

async function selectMode(nextMode: "login" | "register"): Promise<void> {
  await router.push({ name: nextMode });
}

async function switchTab(event: KeyboardEvent): Promise<void> {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const nextMode = event.key === "Home" ? "login" : event.key === "End" ? "register" : mode.value === "login" ? "register" : "login";
  await selectMode(nextMode);
  await nextTick();
  document.getElementById(nextMode === "login" ? "loginTab" : "registerTab")?.focus();
}

async function submit(): Promise<void> {
  await auth.authenticate(mode.value, username.value, password.value);
  if (auth.status === "authenticated") {
    password.value = "";
    showPassword.value = false;
  }
}
</script>

<template>
  <div class="auth-book-stage">
    <section class="auth-dossier" aria-label="剧镜调查员档案">
      <p class="auth-case-number">CASE FILE / 01</p>
      <div class="auth-cover-art" role="img" aria-label="剧镜：调查员借放大镜探寻书页中的真相" />
      <h1 class="auth-book-title">调查员档案</h1>
      <p class="auth-book-quote">每一份证词，<br />都藏着另一面真相。</p>
    </section>

    <div class="auth-book-tabs" role="tablist" aria-label="账户操作" @keydown="switchTab">
        <button
          id="loginTab"
          class="auth-book-tab"
          :class="{ active: mode === 'login' }"
          type="button"
          role="tab"
          aria-controls="authForm"
          :aria-selected="mode === 'login'"
          :tabindex="mode === 'login' ? 0 : -1"
          :disabled="submitting"
          @click="selectMode('login')"
        >登录</button>
        <button
          id="registerTab"
          class="auth-book-tab"
          :class="{ active: mode === 'register' }"
          type="button"
          role="tab"
          aria-controls="authForm"
          :aria-selected="mode === 'register'"
          :tabindex="mode === 'register' ? 0 : -1"
          :disabled="submitting"
          @click="selectMode('register')"
        >注册</button>
    </div>

    <section class="auth-paper" aria-labelledby="authTitle">
      <p class="auth-access-label">INVESTIGATOR ACCESS</p>
      <h2 id="authTitle" :class="{ 'is-register': mode === 'register' }">{{ mode === "login" ? "进入调查室" : "建立调查员档案" }}</h2>
      <p class="auth-paper-subtitle">{{ mode === "login" ? "登录后继续你的调查" : "创建账户，开启你的调查" }}</p>
      <form id="authForm" role="tabpanel" :aria-labelledby="mode === 'login' ? 'loginTab' : 'registerTab'" :aria-busy="submitting" @submit.prevent="submit">
        <div class="auth-form-field">
          <label for="usernameInput">调查员代号</label>
          <div class="auth-input-wrap">
            <UserRound aria-hidden="true" class="auth-field-icon" />
          <input
            id="usernameInput"
            v-model="username"
            autocomplete="username"
            minlength="3"
            maxlength="32"
            placeholder="输入你的代号"
            :disabled="submitting"
            required
          />
          </div>
        </div>
        <div class="auth-form-field">
          <label for="passwordInput">访问密码</label>
          <div class="auth-input-wrap">
            <LockKeyhole aria-hidden="true" class="auth-field-icon" />
          <input
            id="passwordInput"
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            minlength="6"
            :placeholder="mode === 'login' ? '输入密码' : '设置密码（至少 6 位）'"
            :aria-describedby="auth.error ? 'authError' : undefined"
            :disabled="submitting"
            required
          />
            <button
              class="auth-password-toggle"
              type="button"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              :aria-pressed="showPassword"
              aria-controls="passwordInput"
              :disabled="submitting"
              @click="showPassword = !showPassword"
            ><EyeOff v-if="showPassword" aria-hidden="true" /><Eye v-else aria-hidden="true" /></button>
          </div>
        </div>
        <p id="authError" class="auth-paper-error" aria-live="polite">{{ auth.error }}</p>
        <button id="authSubmit" class="auth-book-submit" type="submit" :disabled="submitting">
          {{ submitting ? "正在核验…" : mode === "login" ? "登录" : "创建账户" }}
        </button>
      </form>
      <p class="auth-storage-note"><span aria-hidden="true" />账户与案件记录保存在本机</p>
    </section>
  </div>
</template>
