<script setup lang="ts">
import { X } from "@lucide/vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { appEvents } from "../app-events";
import { getApiClient } from "../runtime";
import { rolePortrait } from "../script-artwork";
import type { ScriptPreview } from "../scripts";
import type { GameSummary } from "../queries/game-records";
import ScriptDetailView from "./ScriptDetailView.vue";
import "../script-library.css";

const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const gameId = computed(() => Number(route.params.gameId));
const dialog = ref<HTMLDialogElement>();
const selectedRole = ref("");
const activating = ref(false);
const cancelling = ref(false);
const busy = computed(() => activating.value || cancelling.value);
const actionError = ref("");
const { data, error, isPending, refetch } = useQuery({
  queryKey: computed(() => ["game-preparation", gameId.value]),
  queryFn: ({ signal }) => getApiClient().request<{ game: GameSummary; script: ScriptPreview; tags: string[] }>(`/api/v1/games/${gameId.value}/preparation`, { signal }),
  enabled: computed(() => route.name === "game-prepare" && gameId.value > 0),
  retry: false,
});
async function selectRole(): Promise<void> {
  await nextTick();
  if (dialog.value && !dialog.value.open) dialog.value.showModal();
}
watch(data, (value) => {
  selectedRole.value = "";
  if (value?.game.status === "preparing") void selectRole();
  else if (value && value.game.status !== "abandoned") appEvents.emit("games:activated", { gameId: value.game.id });
}, { immediate: true });
async function returnToLibrary(): Promise<void> {
  dialog.value?.close();
  const from = route.query.from;
  const returnQuery = typeof from === "string" && (from === "/play" || from.startsWith("/play?"))
    ? Object.fromEntries(Object.entries(router.resolve(from).query).filter(([key]) => ["q", "source", "tag", "order"].includes(key)))
    : {};
  await router.push({ name: "script-library", query: returnQuery });
  appEvents.emit("navigation:view", { view: "library" });
}
async function activate(): Promise<void> {
  if (!selectedRole.value || busy.value) return;
  activating.value = true;
  actionError.value = "";
  try {
    await getApiClient().request(`/api/v1/games/${gameId.value}/activate`, { method: "POST", body: JSON.stringify({ player_role_id: selectedRole.value }) });
    dialog.value?.close();
    appEvents.emit("records:invalidate", {});
    appEvents.emit("games:activated", { gameId: gameId.value });
  } catch (reason) { actionError.value = reason instanceof Error ? reason.message : "进入游戏失败，请重试"; }
  finally { activating.value = false; }
}
async function cancel(): Promise<void> {
  if (busy.value) return;
  cancelling.value = true;
  actionError.value = "";
  try {
    await getApiClient().request(`/api/v1/games/${gameId.value}/cancel-preparation`, { method: "POST" });
    if (data.value) queryClient.setQueryData(["game-preparation", gameId.value], { ...data.value, game: { ...data.value.game, status: "abandoned" } });
    appEvents.emit("records:invalidate", {});
    await returnToLibrary();
  } catch (reason) { actionError.value = reason instanceof Error ? reason.message : "取消入场失败，请重试"; }
  finally { cancelling.value = false; }
}
</script>

<template>
  <section class="catalog-shell">
    <div v-if="isPending" class="catalog-status">正在进入剧本…</div>
    <div v-else-if="error" class="catalog-status"><p role="alert">{{ error.message }}</p><button class="secondary-button" @click="refetch()">重新读取</button><button class="secondary-button" @click="returnToLibrary">返回剧本库</button></div>
    <div v-else-if="data?.game.status === 'abandoned'" class="catalog-status"><p>本次入场已取消，请返回剧本库重新选择剧本。</p><button class="secondary-button" @click="returnToLibrary">返回剧本库</button></div>
    <template v-else-if="data">
      <ScriptDetailView :script="data.script" :tags="data.tags" :busy="busy" :error="actionError" :selected-role="selectedRole" preparing @back="cancel" @choose="selectRole" />
      <dialog ref="dialog" class="role-selection-dialog portrait-selection-dialog" aria-labelledby="roleSelectionTitle" @cancel.prevent="cancel">
        <header><div><p class="catalog-eyebrow">CHOOSE YOUR CHARACTER</p><h3 id="roleSelectionTitle">选择你的角色</h3><p>其余角色将由角色 Agent 扮演。</p></div><button class="portrait-dialog-close" type="button" aria-label="取消本次入场并返回剧本库" :disabled="busy" @click="cancel"><X :size="20" aria-hidden="true" /></button></header>
        <form @submit.prevent="activate">
          <div class="role-selection-list"><fieldset class="role-options portrait-options" :disabled="busy"><legend class="sr-only">可选角色</legend><label v-for="role in data.script.playable_roles" :key="role.role_id" class="portrait-option" :class="{ selected: selectedRole === role.role_id }"><input v-model="selectedRole" type="radio" name="player-role" :value="role.role_id" /><img :src="rolePortrait(role.role_id)" alt="" /><span class="portrait-option-copy"><strong>{{ role.role_name }}</strong><span>{{ role.public_identity }}</span></span></label></fieldset></div>
          <p v-if="actionError" class="form-error" role="alert">{{ actionError }}</p>
          <div class="role-selection-actions"><button class="secondary-button" type="button" :disabled="busy" @click="cancel">{{ cancelling ? '正在取消…' : '取消本次入场' }}</button><button class="primary-button" type="submit" :disabled="!selectedRole || busy">{{ activating ? '正在入场…' : '确认角色，进入游戏' }}</button></div>
        </form>
      </dialog>
    </template>
  </section>
</template>
