<script setup lang="ts">
import { FolderOpen, RefreshCw, Trash2 } from "@lucide/vue";
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
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

async function refresh(): Promise<void> {
  clearDeleteConfirmation();
  const result = await refetch({ cancelRefetch: true });
  if (result.error) appEvents.emit("toast:show", { message: queryErrorMessage(result.error) });
}

async function openRecord(game: GameSummary): Promise<void> {
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
  <header class="page-header">
    <div>
      <p class="case-label">CASE ARCHIVE</p>
      <h2>案件档案</h2>
      <p>继续调查或查看已经完成的案件。</p>
    </div>
    <button
      id="refreshRecordsBtn"
      class="icon-button bordered records-refresh"
      :class="{ 'is-loading': isFetching }"
      type="button"
      title="刷新档案"
      aria-label="刷新档案"
      :disabled="isFetching || deletingGameId !== null"
      @click="refresh"
    ><RefreshCw :size="17" aria-hidden="true" /></button>
  </header>

  <div class="records-header" aria-hidden="true">
    <span>案件</span><span>类型</span><span>模式</span><span>进度</span><span></span>
  </div>
  <div id="recordsList" class="records-list" :aria-busy="isFetching">
    <div v-if="isPending" class="empty-state">正在读取记录...</div>
    <div v-else-if="error && !games.length" class="empty-state records-error-state">
      <span>{{ queryErrorMessage(error) }}</span>
      <button class="secondary-button" type="button" @click="refresh">
        <RefreshCw :size="15" aria-hidden="true" />重新读取
      </button>
    </div>
    <div v-else-if="!games.length" class="empty-state">暂无游戏记录</div>
    <article v-for="game in games" :key="game.id" class="record-row">
      <div class="record-title">
        <strong>{{ game.title }}</strong>
        <span>{{ formatUpdatedAt(game.updated_at) }}</span>
      </div>
      <div class="record-cell"><span>类型</span>{{ categoryNames[game.category] || game.category }}</div>
      <div class="record-cell"><span>模式</span>{{ modeNames[game.mode] || game.mode }}</div>
      <div class="record-cell"><span>进度</span>{{ game.current_stage }}/{{ game.total_stages }}</div>
      <div class="record-actions">
        <button class="secondary-button" type="button" @click="openRecord(game)">
          <FolderOpen :size="14" aria-hidden="true" />{{ game.status === "completed" ? "查看" : "继续" }}
        </button>
        <button
          class="record-delete-button"
          :class="{ confirming: confirmingGameId === game.id }"
          type="button"
          :disabled="deletingGameId !== null"
          @click="requestDelete(game)"
        >
          <Trash2 :size="14" aria-hidden="true" />
          <b>{{ deletingGameId === game.id ? "删除中" : confirmingGameId === game.id ? "确认删除" : "删除" }}</b>
        </button>
      </div>
    </article>
  </div>
</template>
