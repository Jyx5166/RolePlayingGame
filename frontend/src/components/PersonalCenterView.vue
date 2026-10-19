<script setup lang="ts">
import { ArrowRight, BookOpen, CircleCheck, FilePlus2, FolderOpen, LogOut, RefreshCw, UserRound } from "@lucide/vue";
import { computed } from "vue";
import { useRoute } from "vue-router";
import { appEvents } from "../app-events";
import { queryErrorMessage, useGameRecordsQuery, type GameSummary } from "../queries/game-records";
import { useAuthStore } from "../stores/auth";
import "../personal-center.css";

const route = useRoute();
const auth = useAuthStore();
const enabled = computed(() => route.name === "personal-center");
const { data, error, isPending, isFetching, refetch } = useGameRecordsQuery(enabled);
const games = computed(() => data.value || []);
const initial = computed(() => Array.from(auth.user?.username.trim() || "?")[0]!.toLocaleUpperCase());
const stats = computed(() => [
  { label: "案件总数", value: games.value.length, icon: FolderOpen },
  { label: "待续案件", value: games.value.filter(game => !["abandoned", "completed"].includes(game.status)).length, icon: BookOpen },
  { label: "已完成", value: games.value.filter(game => game.status === "completed").length, icon: CircleCheck },
]);
const recentGames = computed(() => [...games.value].sort((a, b) => (
  (Date.parse(b.updated_at) - Date.parse(a.updated_at)) || b.id - a.id
)).slice(0, 3));
const phases: Record<string, string> = { opening: "故事开幕", private_reveal: "角色剧本", briefing: "幕前通报", investigation: "自由调查", dm_hosting: "DM 主持", replay: "终局复盘" };
const statuses: Record<string, string> = { preparing: "待选角色", playing: "进行中", paused: "已暂停", completed: "已完成", abandoned: "已取消入场" };
const statusLabel = (game: GameSummary) => statuses[game.status] || game.status || "状态未记录";
function progressLabel(game: GameSummary): string {
  if (["preparing", "abandoned"].includes(game.status)) return `尚未开始 · 共 ${game.total_stages} 幕`;
  const phase = phases[game.current_phase] || game.current_phase || "阶段未记录";
  if (game.current_phase === "opening" || (game.current_phase === "private_reveal" && game.current_stage === 1)) return `${phase} · 共 ${game.total_stages} 幕`;
  return `${phase} · 第 ${game.current_stage} / ${game.total_stages} 幕`;
}
const navigate = (view: "library" | "create" | "records") => appEvents.emit("navigation:view", { view });
</script>

<template>
  <section class="personal-center-shell" aria-labelledby="personalCenterTitle">
    <header class="personal-center-header"><p>PERSONAL CENTER</p><div><h2 id="personalCenterTitle">个人中心</h2><span>查看账户信息、案件进度，继续你的故事。</span></div></header>
    <div class="personal-center-layout">
      <section class="personal-center-panel personal-center-account" aria-label="账户信息">
        <div class="personal-center-avatar" aria-hidden="true">{{ initial }}</div><h3>{{ auth.user?.username || '未登录' }}</h3><p class="personal-center-identity"><UserRound :size="15" aria-hidden="true" />本地调查员</p>
        <dl class="personal-center-account-fields"><div><dt>账号 ID</dt><dd>{{ auth.user ? `#${auth.user.id}` : '—' }}</dd></div><div><dt>账户类型</dt><dd>本地账户</dd></div></dl>
        <p class="personal-center-account-note">案件记录与剧本库关联当前账户。</p>
        <button class="personal-center-logout" type="button" :disabled="auth.status==='submitting' || !auth.user" @click="auth.logout()"><LogOut :size="17" aria-hidden="true" />{{ auth.status==='submitting'?'正在退出…':'退出登录' }}</button>
      </section>
      <div class="personal-center-content">
        <section class="personal-center-panel personal-center-overview" aria-labelledby="personalCenterOverviewTitle">
          <header class="personal-center-section-header"><h3 id="personalCenterOverviewTitle">调查概览</h3><button class="personal-center-text-button" type="button" :disabled="isFetching" @click="refetch()"><RefreshCw :size="16" aria-hidden="true" />{{ isFetching?'正在读取…':'刷新概览' }}</button></header>
          <div class="personal-center-stats" :aria-busy="isPending"><article v-for="stat in stats" :key="stat.label" class="personal-center-stat"><component :is="stat.icon" :size="21" aria-hidden="true" /><span>{{ stat.label }}</span><strong>{{ isPending || error ? '—' : stat.value }}</strong></article></div>
          <p v-if="isPending" class="personal-center-feedback" role="status">正在读取案件概览…</p>
          <div v-else-if="error" class="personal-center-error"><p role="alert">{{ queryErrorMessage(error) }}</p><button class="personal-center-outline-button" type="button" :disabled="isFetching" @click="refetch()">重新读取</button></div>
          <p v-else class="personal-center-stats-note">总数包含已取消入场记录；待续案件包含待选角色和已暂停的案件。</p>
        </section>
        <section class="personal-center-panel" aria-labelledby="personalCenterActionsTitle">
          <header class="personal-center-section-header"><h3 id="personalCenterActionsTitle">继续探索</h3><span>从这里开始下一段故事</span></header>
          <div class="personal-center-shortcuts"><button type="button" @click="navigate('library')"><BookOpen :size="23" aria-hidden="true" /><span><strong>新建游戏</strong><small>挑选剧本，进入故事</small></span><ArrowRight :size="17" aria-hidden="true" /></button><button type="button" @click="navigate('create')"><FilePlus2 :size="23" aria-hidden="true" /><span><strong>新建剧本</strong><small>导入或创作新的故事</small></span><ArrowRight :size="17" aria-hidden="true" /></button><button type="button" @click="navigate('records')"><FolderOpen :size="23" aria-hidden="true" /><span><strong>案件档案</strong><small>继续调查，回看案件</small></span><ArrowRight :size="17" aria-hidden="true" /></button></div>
        </section>
      </div>
      <section class="personal-center-panel personal-center-recent" aria-labelledby="personalCenterRecentTitle">
        <header class="personal-center-section-header"><h3 id="personalCenterRecentTitle">最近案件</h3><button class="personal-center-text-button" type="button" @click="navigate('records')">查看案件档案<ArrowRight :size="15" aria-hidden="true" /></button></header>
        <p v-if="isPending" class="personal-center-feedback">正在读取最近案件…</p><p v-else-if="error" class="personal-center-feedback">读取成功后将显示最近案件。</p>
        <ul v-else-if="recentGames.length" class="personal-center-recent-list"><li v-for="game in recentGames" :key="game.id"><div><p class="personal-center-record-id">CASE #{{ game.id }}</p><h4>{{ game.title }}</h4><p class="personal-center-record-progress">{{ progressLabel(game) }}</p></div><span class="personal-center-record-status" :data-status="game.status">{{ statusLabel(game) }}</span></li></ul>
        <div v-else class="personal-center-empty"><FolderOpen :size="30" aria-hidden="true" /><p>暂无案件记录</p><span>从新建游戏挑选一个剧本，开启你的第一场调查。</span></div>
      </section>
    </div>
  </section>
</template>
