<script setup lang="ts">
import { ArrowRight, BookOpen, Check, ChevronDown, ChevronRight, Search, Users } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { appEvents } from "../app-events";
import { getApiClient } from "../runtime";
import { rolePortrait, scriptCover } from "../script-artwork";
import type { CatalogScript } from "../scripts";
import { useAuthStore } from "../stores/auth";
import ScriptDetailView from "./ScriptDetailView.vue";
import "../script-library.css";
import "../case-browser.css";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const routeValue = (key: string) => typeof route.query[key] === "string" ? route.query[key] as string : "";
const keyword = ref(routeValue("q"));
const query = computed(() => routeValue("q").trim());
const source = computed(() => routeValue("source"));
const tag = computed(() => routeValue("tag"));
const order = computed(() => routeValue("order"));
const selectedId = computed(() => routeValue("script"));
const previewId = ref(selectedId.value);
const previewHeading = ref<HTMLElement | null>(null);
const scriptList = ref<HTMLElement | null>(null);
const entering = ref<string | null>(null);
const actionError = ref("");
const moreFilter = ref<HTMLElement | null>(null);
const moreTrigger = ref<HTMLButtonElement | null>(null);
const moreList = ref<HTMLElement | null>(null);
const moreOpen = ref(false);
const moreAlignEnd = ref(false);
const activeGenre = ref(0);
const moreId = useId();
let debounce: ReturnType<typeof setTimeout> | undefined;
const pendingEntries = new Map<string, string>();

function updateQuery(values: Record<string, string>, replace = true): void {
  const next = { ...route.query };
  for (const [key, value] of Object.entries(values)) {
    if (value) next[key] = value;
    else delete next[key];
  }
  void router[replace ? "replace" : "push"]({ name: "script-library", query: next });
}
watch(keyword, (value) => {
  clearTimeout(debounce);
  debounce = setTimeout(() => updateQuery({ q: value.trim() }), 250);
});
watch(query, (value) => {
  if (keyword.value.trim() !== value) keyword.value = value;
});
watch(selectedId, (value) => {
  actionError.value = "";
  if (value) previewId.value = value;
});
onMounted(() => document.addEventListener("pointerdown", closeMoreOutside));
onBeforeUnmount(() => {
  clearTimeout(debounce);
  document.removeEventListener("pointerdown", closeMoreOutside);
});

const { data, error, isPending, isFetching, refetch } = useQuery({
  queryKey: computed(() => ["script-catalog", auth.user?.id, query.value]),
  queryFn: ({ signal }) => getApiClient().request<CatalogScript[]>(`/api/v1/scripts?q=${encodeURIComponent(query.value)}`, { signal }),
  enabled: computed(() => Boolean(auth.user)),
});
// Resolve a direct detail link even when its saved search does not include the selected script.
const detailCatalog = useQuery({
  queryKey: computed(() => ["script-catalog", auth.user?.id, ""]),
  queryFn: ({ signal }) => getApiClient().request<CatalogScript[]>("/api/v1/scripts?q=", { signal }),
  enabled: computed(() => Boolean(auth.user && selectedId.value && query.value && data.value && !data.value.some((item) => item.catalog_id === selectedId.value))),
});
const selectedScript = computed(() => [...(data.value || []), ...(detailCatalog.data.value || [])].find((item) => item.catalog_id === selectedId.value));
const availableTags = computed(() => [...new Set((data.value || []).flatMap((item) => item.tags))]);
const primaryTags = computed(() => ["悬疑", "推理", "密室"].filter((genre) => availableTags.value.includes(genre)));
const extraTags = computed(() => availableTags.value.filter((genre) => !primaryTags.value.includes(genre)));
const moreOptions = computed(() => [{ value: "", label: "全部类型" }, ...extraTags.value.map((genre) => ({ value: genre, label: genre }))]);
watch([tag, extraTags, selectedId], () => closeMore(false));
const visibleScripts = computed(() => {
  const scripts = (data.value || []).filter((item) => (!source.value || item.source === source.value) && (!tag.value || item.tags.includes(tag.value)));
  return order.value === "title" ? [...scripts].sort((a, b) => a.title.localeCompare(b.title, "zh-CN")) : scripts;
});
const previewScript = computed(() => {
  if (isPending.value || error.value) return undefined;
  return visibleScripts.value.find((item) => item.catalog_id === previewId.value) || visibleScripts.value[0];
});
watch([visibleScripts, isPending, error], ([scripts, pending, reason]) => {
  if (pending || reason || data.value === undefined) return;
  if (!scripts.some((item) => item.catalog_id === previewId.value)) previewId.value = scripts[0]?.catalog_id || "";
});

function search(): void {
  clearTimeout(debounce);
  updateQuery({ q: keyword.value.trim() });
}
function closeMore(restoreFocus = true): void {
  if (!moreOpen.value) return;
  moreOpen.value = false;
  if (restoreFocus) moreTrigger.value?.focus({ preventScroll: true });
}
function closeMoreOutside(event: PointerEvent): void {
  if (event.target instanceof Node && !moreFilter.value?.contains(event.target)) closeMore(false);
}
function leaveMore(event: FocusEvent): void {
  if (event.relatedTarget === moreTrigger.value || !(event.relatedTarget instanceof Node) || !moreFilter.value?.contains(event.relatedTarget)) closeMore(false);
}
async function openMore(direction = 1): Promise<void> {
  moreAlignEnd.value = false;
  const selected = moreOptions.value.findIndex((option) => option.value === tag.value);
  activeGenre.value = selected >= 0 ? selected : direction < 0 ? moreOptions.value.length - 1 : 0;
  moreOpen.value = true;
  await nextTick();
  moreAlignEnd.value = (moreList.value?.getBoundingClientRect().right || 0) > window.innerWidth - 12;
  moreList.value?.focus({ preventScroll: true });
  document.getElementById(`${moreId}-option-${activeGenre.value}`)?.scrollIntoView?.({ block: "nearest" });
}
function chooseGenre(value: string): void {
  updateQuery({ tag: value });
  closeMore();
}
function moreTriggerKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && moreOpen.value) { event.preventDefault(); closeMore(); return; }
  if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
  event.preventDefault();
  void openMore(event.key === "ArrowUp" ? -1 : 1);
}
function moreListKey(event: KeyboardEvent): void {
  if (event.key === "Escape") { event.preventDefault(); closeMore(); return; }
  if (["Enter", " "].includes(event.key)) {
    event.preventDefault();
    chooseGenre(moreOptions.value[activeGenre.value]!.value);
    return;
  }
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const count = moreOptions.value.length;
  activeGenre.value = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : (activeGenre.value + (event.key === "ArrowDown" ? 1 : -1) + count) % count;
  document.getElementById(`${moreId}-option-${activeGenre.value}`)?.scrollIntoView({ block: "nearest" });
}
function scrollInCompactView(element: HTMLElement | null): void {
  if (!element || !window.matchMedia("(max-width: 760px)").matches) return;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}
async function selectPreview(catalogId: string): Promise<void> {
  previewId.value = catalogId;
  await nextTick();
  scrollInCompactView(previewHeading.value);
}
function backToList(): void { scrollInCompactView(scriptList.value); }
function openDetails(script: CatalogScript): void {
  clearTimeout(debounce);
  updateQuery({ script: script.catalog_id, q: keyword.value.trim() }, false);
}
function backToLibrary(): void { updateQuery({ script: "" }, false); }
async function edit(script: CatalogScript): Promise<void> {
  await router.push({ name: "script-create", query: { edit: script.catalog_id } });
  appEvents.emit("navigation:view", { view: "create" });
}
async function enter(script: CatalogScript): Promise<void> {
  if (entering.value) return;
  const returnPath = route.fullPath;
  entering.value = script.catalog_id;
  actionError.value = "";
  try {
    const key = `${script.catalog_id}:${script.version}`;
    if (!pendingEntries.has(key)) pendingEntries.set(key, crypto.randomUUID());
    const game = await getApiClient().request<{ id: number }>("/api/v1/game-preparations", {
      method: "POST", body: JSON.stringify({ catalog_id: script.catalog_id, version: script.version, request_id: pendingEntries.get(key) }),
    });
    appEvents.emit("records:invalidate", {});
    await router.push({ name: "game-prepare", params: { gameId: game.id }, query: { from: returnPath } });
    appEvents.emit("games:prepare", { gameId: game.id });
  } catch (reason) {
    actionError.value = reason instanceof Error ? reason.message : "进入剧本失败";
  } finally { entering.value = null; }
}
</script>

<template>
  <section class="catalog-shell" :class="{ 'case-browser-shell': !selectedId }">
    <template v-if="selectedId">
      <ScriptDetailView v-if="selectedScript" :script="selectedScript" :tags="selectedScript.tags" :source="selectedScript.source" :busy="entering !== null" :error="actionError" @back="backToLibrary" @choose="enter(selectedScript)" @edit="edit(selectedScript)" />
      <div v-else-if="isPending || isFetching || detailCatalog.isFetching.value" class="catalog-status" aria-live="polite">正在读取剧本详情…</div>
      <div v-else class="catalog-status"><p role="alert">{{ error?.message || detailCatalog.error.value?.message || '该剧本不存在或暂时无法查看。' }}</p><button class="secondary-button" @click="backToLibrary">返回剧本库</button></div>
    </template>
    <template v-else>
      <header class="case-browser-header">
        <h2>剧本库</h2>
        <div class="case-browser-source-tabs" role="group" aria-label="剧本来源">
          <button :class="{ active: !source }" :aria-pressed="!source" @click="updateQuery({ source: '' })">全部剧本</button>
          <button :class="{ active: source === 'builtin' }" :aria-pressed="source === 'builtin'" @click="updateQuery({ source: 'builtin' })">内置剧本</button>
          <button :class="{ active: source === 'imported' }" :aria-pressed="source === 'imported'" @click="updateQuery({ source: 'imported' })">我的剧本</button>
        </div>
        <form class="case-browser-search" role="search" @submit.prevent="search">
          <button type="submit" aria-label="搜索剧本"><Search :size="21" aria-hidden="true" /></button><label class="sr-only" for="scriptSearchInput">按剧本名称或标签搜索</label>
          <input id="scriptSearchInput" v-model="keyword" type="search" maxlength="120" placeholder="搜索剧本名称或标签" autocomplete="off" />
        </form>
      </header>
      <div class="case-browser-filterbar">
        <div class="case-browser-genres" role="group" aria-label="剧本类型">
          <button class="case-browser-genre" :class="{ active: !tag }" :aria-pressed="!tag" @click="updateQuery({ tag: '' })">全部类型</button>
          <button v-for="genre in primaryTags" :key="genre" class="case-browser-genre" :class="{ active: tag === genre }" :aria-pressed="tag === genre" @click="updateQuery({ tag: tag === genre ? '' : genre })">{{ genre }}</button>
          <div v-if="extraTags.length" ref="moreFilter" class="case-browser-more" @focusout="leaveMore">
            <button :id="moreId" ref="moreTrigger" type="button" class="case-browser-genre case-browser-more-trigger" :class="{ active: extraTags.includes(tag) }" :aria-label="extraTags.includes(tag) ? `更多剧本类型，当前：${tag}` : '更多剧本类型'" aria-haspopup="listbox" :aria-expanded="moreOpen" :aria-controls="`${moreId}-options`" @click="moreOpen ? closeMore() : openMore()" @keydown="moreTriggerKey"><span>{{ extraTags.includes(tag) ? tag : '更多' }}</span><ChevronDown :size="15" aria-hidden="true" /></button>
            <ul v-if="moreOpen" :id="`${moreId}-options`" ref="moreList" class="case-browser-more-options" :class="{ 'align-end': moreAlignEnd }" role="listbox" aria-label="更多剧本类型" :aria-activedescendant="`${moreId}-option-${activeGenre}`" tabindex="-1" @keydown="moreListKey">
              <li v-for="(option,index) in moreOptions" :id="`${moreId}-option-${index}`" :key="option.value" role="option" :aria-selected="tag === option.value" :class="{ active: activeGenre === index, selected: tag === option.value }" @pointermove="activeGenre=index" @pointerdown.prevent @click="chooseGenre(option.value)"><span>{{ option.label }}</span><Check v-if="tag === option.value" :size="15" aria-hidden="true" /></li>
            </ul>
          </div>
        </div>
        <div class="case-browser-result-tools">
          <label class="case-browser-sort"><span class="sr-only">剧本排序</span><select :value="order" @change="updateQuery({ order: ($event.target as HTMLSelectElement).value })"><option value="">默认排序</option><option value="title">名称顺序</option></select><ChevronDown :size="16" aria-hidden="true" /></label>
          <span class="case-browser-count">共 {{ visibleScripts.length }} 部剧本</span>
          <span v-if="isFetching" class="sr-only" aria-live="polite">正在更新剧本…</span>
        </div>
      </div>
      <div class="case-browser-body" :aria-busy="isFetching">
        <p v-if="isPending" class="catalog-status" aria-live="polite">正在读取剧本…</p>
        <div v-else-if="error" class="catalog-status"><p role="alert">{{ error.message }}</p><button class="secondary-button" @click="refetch()">重新读取</button></div>
        <div v-else-if="!visibleScripts.length" class="catalog-status">{{ query || source || tag ? '没有匹配的剧本，试试其他名称或类型。' : '剧本库暂无可用剧本。' }}</div>
        <template v-else>
          <div ref="scriptList" class="case-browser-list" aria-label="可选剧本" tabindex="-1">
            <article v-for="script in visibleScripts" :key="script.catalog_id" class="case-browser-row" :class="{ selected: previewScript?.catalog_id === script.catalog_id }">
              <button class="case-browser-row-button" type="button" :aria-label="`预览剧本：${script.title}`" :aria-pressed="previewScript?.catalog_id === script.catalog_id" @click="selectPreview(script.catalog_id)">
                <img class="case-browser-thumbnail" :src="scriptCover(script.script_id || script.catalog_id)" alt="" loading="lazy" />
                <div class="case-browser-row-copy"><h3 :title="script.title">{{ script.title }}</h3><div class="case-browser-tags"><span v-for="genre in script.tags.slice(0, 3)" :key="genre" :title="genre">{{ genre }}</span></div></div>
                <div class="case-browser-row-meta"><span><b>{{ script.role_count }}</b> 位角色</span><span><b>{{ script.total_stages }}</b> 幕故事</span></div>
                <ChevronRight class="case-browser-row-arrow" :size="20" aria-hidden="true" />
              </button>
              <button v-if="script.source === 'imported'" class="case-browser-edit" @click="edit(script)">编辑并发布新版本 <ArrowRight :size="13" aria-hidden="true" /></button>
            </article>
          </div>
          <aside v-if="previewScript" class="case-browser-preview" aria-labelledby="scriptPreviewHeading">
            <div class="case-browser-preview-bar"><h3 id="scriptPreviewHeading" ref="previewHeading" class="case-browser-preview-label" tabindex="-1">剧本预览</h3><button class="case-browser-back-to-list" type="button" @click="backToList">返回剧本列表</button></div>
            <img class="case-browser-preview-cover" :src="scriptCover(previewScript.script_id || previewScript.catalog_id)" :alt="`${previewScript.title}封面`" />
            <h2 class="case-browser-preview-title">{{ previewScript.title }}</h2>
            <div class="case-browser-tags"><span v-for="genre in previewScript.tags" :key="genre">{{ genre }}</span></div>
            <p class="case-browser-synopsis">{{ previewScript.story_background }}</p>
            <div class="case-browser-preview-meta"><span><Users :size="23" aria-hidden="true" /><b>{{ previewScript.role_count }}</b> 位角色</span><span><BookOpen :size="23" aria-hidden="true" /><b>{{ previewScript.total_stages }}</b> 幕故事</span></div>
            <section class="case-browser-roles" aria-label="可选角色"><h3>可选角色</h3><div class="case-browser-cast"><figure v-for="role in previewScript.playable_roles" :key="role.role_id"><img :src="rolePortrait(role.role_id)" :alt="role.role_name" loading="lazy" /><figcaption>{{ role.role_name }}</figcaption></figure></div></section>
            <button class="case-browser-details" type="button" @click="openDetails(previewScript)">查看剧本详情 <ArrowRight :size="23" aria-hidden="true" /></button>
          </aside>
        </template>
      </div>
    </template>
  </section>
</template>
