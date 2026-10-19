<script setup lang="ts">
import { BookOpen, Check, FolderOpen, Pause, RefreshCw, Trash2, UserRound } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { appEvents } from "../app-events";
import {
  gameRecordsQueryKey,
  invalidateGameRecords,
  queryErrorMessage,
  useGameRecordsQuery,
  type GameSummary,
} from "../queries/game-records";
import { useAuthStore } from "../stores/auth";
import { scriptCover } from "../script-artwork";
import "../case-archive.css";

const categoryNames: Record<string, string> = {
  mystery: "悬疑推理",
  adventure: "冒险探索",
  fantasy: "奇幻世界",
  history: "历史演绎",
  custom: "自定义",
};
const modeNames: Record<string, string> = {
  narrative: "剧情体验",
  deduction: "推理对抗",
  faction: "阵营博弈",
};
const phaseNames: Record<string, string> = {
  opening: "故事开幕",
  private_reveal: "角色剧本",
  briefing: "幕前通报",
  investigation: "自由调查",
  dm_hosting: "DM 主持",
  replay: "终局复盘",
};

const route = useRoute();
const auth = useAuthStore();
const queryClient = useQueryClient();
const enabled = computed(() => route.name === "case-list");
const {
  data,
  error,
  isFetching,
  isPending,
  refetch,
  deleteRecord,
  deletingGameId,
  invalidate,
} = useGameRecordsQuery(enabled);
const games = computed(() => data.value || []);
const confirmingGameId = ref<number | null>(null);
let confirmationTimer: number | null = null;
let stopInvalidationListener: (() => void) | null = null;

function clearDeleteConfirmation(): void {
  if (confirmationTimer !== null) window.clearTimeout(confirmationTimer);
  confirmationTimer = null;
  confirmingGameId.value = null;
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function statusLabel(game: GameSummary): string {
  if (game.status === "abandoned") return "已取消入场";
  if (game.status === "preparing") return "待选角色";
  if (game.status === "completed") return "已完成";
  return game.status === "paused" ? "已暂停" : "进行中";
}

function progressLabel(game: GameSummary): string {
  if (game.status === "preparing" || game.status === "abandoned") return `共 ${game.total_stages} 幕`;
  const phase = phaseNames[game.current_phase] || "当前进度";
  if (game.current_phase === "opening" || (game.current_phase === "private_reveal" && game.current_stage === 1)) {
    return `${phase} · 共 ${game.total_stages} 幕`;
  }
  return `${phase} · ${game.current_stage}/${game.total_stages} 幕`;
}

async function refresh(): Promise<void> {
  clearDeleteConfirmation();
  const result = await refetch({ cancelRefetch: true });
  if (result.error) appEvents.emit("toast:show", { message: queryErrorMessage(result.error) });
}

async function openRecord(game: GameSummary): Promise<void> {
  if (game.status === "abandoned") return;
  clearDeleteConfirmation();
  await invalidate();
  appEvents.emit("records:open", { gameId: game.id });
}

async function requestDelete(game: GameSummary): Promise<void> {
  if (confirmingGameId.value !== game.id) {
    clearDeleteConfirmation();
    confirmingGameId.value = game.id;
    confirmationTimer = window.setTimeout(clearDeleteConfirmation, 3200);
    return;
  }

  clearDeleteConfirmation();
  try {
    await deleteRecord(game);
    appEvents.emit("records:deleted", { gameId: game.id, title: game.title });
  } catch (deleteError) {
    appEvents.emit("toast:show", { message: queryErrorMessage(deleteError) });
  }
}

watch(
  () => auth.user?.id,
  (userId, previousUserId) => {
    if (previousUserId && previousUserId !== userId) {
      queryClient.removeQueries({ queryKey: gameRecordsQueryKey(previousUserId) });
    }
  },
);

watch(enabled, (active) => {
  if (!active) clearDeleteConfirmation();
});

onMounted(() => {
  stopInvalidationListener = appEvents.on("records:invalidate", () => {
    const userId = auth.user?.id;
    if (userId) void invalidateGameRecords(queryClient, userId);
  });
});

onBeforeUnmount(() => {
  clearDeleteConfirmation();
  stopInvalidationListener?.();
});
</script>

<template>
  <section class="case-archive-shell" aria-labelledby="caseArchiveTitle">
    <header class="case-archive-header">
      <div class="case-archive-heading">
        <p class="case-archive-eyebrow">CASE ARCHIVE</p>
        <div class="case-archive-heading-line">
          <h2 id="caseArchiveTitle">案件档案</h2>
          <p class="case-archive-subtitle">继续调查或查看已经完成的案件。</p>
        </div>
      </div>
      <button
        id="refreshRecordsBtn"
        class="case-archive-refresh"
        :class="{ 'case-archive-refresh--loading': isFetching }"
        type="button"
        aria-label="刷新档案"
        :disabled="isFetching || deletingGameId !== null"
        @click="refresh"
      ><RefreshCw :size="20" aria-hidden="true" /><span>刷新档案</span></button>
    </header>

    <div id="recordsList" class="case-archive-list" :aria-busy="isFetching">
      <div v-if="isPending" class="case-archive-message" role="status">正在读取记录...</div>
      <div v-else-if="error && !games.length" class="case-archive-message case-archive-message--error" role="alert">
        <span>{{ queryErrorMessage(error) }}</span>
        <button class="case-archive-retry" type="button" :disabled="isFetching" @click="refresh">
          <RefreshCw :size="16" aria-hidden="true" />重新读取
        </button>
      </div>
      <div v-else-if="!games.length" class="case-archive-message">
        <FolderOpen :size="32" aria-hidden="true" />
        <span>暂无游戏记录</span>
      </div>
      <article
        v-for="game in games"
        :key="game.id"
        class="case-archive-card"
        :data-game-id="game.id"
        :aria-labelledby="`caseArchiveGameTitle-${game.id}`"
      >
        <div class="case-archive-cover">
          <img :src="scriptCover(game.catalog_script_id || '')" alt="" loading="lazy" decoding="async" />
        </div>
        <div class="case-archive-details">
          <h3 :id="`caseArchiveGameTitle-${game.id}`" class="case-archive-title">{{ game.title }}</h3>
          <p class="case-archive-meta">游戏 #{{ game.id }}<span aria-hidden="true">·</span>{{ formatUpdatedAt(game.updated_at) }}</p>
          <div class="case-archive-fields">
            <span class="case-archive-tag">{{ categoryNames[game.category] || game.category }}</span>
            <span class="case-archive-tag">{{ modeNames[game.mode] || game.mode }}</span>
            <span class="case-archive-state" :class="`case-archive-state--${game.status}`">
              <Pause v-if="game.status === 'paused'" :size="15" aria-hidden="true" />
              <Check v-else-if="game.status === 'completed'" :size="16" aria-hidden="true" />
              <UserRound v-else-if="game.status === 'preparing'" :size="16" aria-hidden="true" />
              <BookOpen v-else :size="15" aria-hidden="true" />
              {{ statusLabel(game) }}
            </span>
            <span class="case-archive-progress">{{ progressLabel(game) }}</span>
          </div>
        </div>
        <div class="case-archive-actions">
          <button class="case-archive-open" type="button" :disabled="game.status === 'abandoned'" @click="openRecord(game)">
            {{ game.status === "abandoned" ? "已取消" : game.status === "completed" ? "查看" : "继续" }}
          </button>
          <button
            class="case-archive-delete"
            :class="{ 'case-archive-delete--confirming': confirmingGameId === game.id }"
            type="button"
            :disabled="deletingGameId !== null"
            @click="requestDelete(game)"
          >
            <Trash2 :size="17" aria-hidden="true" />
            <span>{{ deletingGameId === game.id ? "删除中" : confirmingGameId === game.id ? "确认删除" : "删除" }}</span>
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
