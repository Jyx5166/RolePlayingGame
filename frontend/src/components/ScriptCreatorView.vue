<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import { ArrowRight, BookOpen, CircleCheck, FilePlus2, FileText, Plus, Sparkles, Users, X } from "@lucide/vue";
import { useRoute } from 'vue-router';
import { appEvents } from "../app-events";
import { getApiClient } from "../runtime";
import type { CatalogScript, ScriptPreview } from "../scripts";
import type { AuthoringJob, AuthoringPreview, AuthoringStep } from "../authoring";
import { rolePortrait, scriptCover } from "../script-artwork";
import "../script-creator.css";

const fileInput = ref<HTMLInputElement>();
const fileName = ref("");
const title = ref("");
const tagsText = ref("");
const tagDraft = ref("");
const fileSize = ref<number | null>(null);
const dragging = ref(false);
const script = ref<Record<string, unknown> | null>(null);
const preview = ref<AuthoringPreview | null>(null);
const steps = ref<AuthoringStep[]>([]);
const publishable = ref<boolean>();
const draftText = ref("");
const draftTextError = ref("");
const returnedDraft = ref(false);
const sourceJobId = ref<string | null>(null);
const error = ref("");
const busy = ref(false);
const cancelling = ref(false);
let cancelled = false;
const mode=ref<'import'|'ai'>('import'); const topic=ref(''); const jobId=ref(''); const jobState=ref('');
const route=useRoute(); let destroyed=false;
const currentCatalogId=ref<string | null>(route.query.edit ? String(route.query.edit) : null);
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let finishWait: (() => void) | undefined;
let operation = 0;
const savedJob=ref(sessionStorage.getItem('authoring:last') || '');
const editable = computed(() => Boolean(script.value) || mode.value==='ai');
const validation = computed(() => preview.value?.authoring_validation);
const semanticReview = computed(() => preview.value?.semantic_review);
const reviewRunning = computed(() => busy.value && ['queued','generating','validating'].includes(jobState.value)
  && (semanticReview.value?.status==='running' || steps.value.some(step=>step.step_id.startsWith('review:') && step.status==='running')));
const semanticReviewLabel = computed(() => reviewRunning.value ? '审稿中' : semanticReview.value?.status==='passed' ? '通过'
  : semanticReview.value?.status==='failed' ? '未通过' : ['running','incomplete'].includes(semanticReview.value?.status || '') ? '审稿未完成' : '未进行模型审稿');
const canPublish = computed(() => !cancelling.value && !cancelled && jobState.value==='preview' && Boolean(preview.value && jobId.value)
  && validation.value?.passed!==false && semanticReview.value?.status!=='failed' && publishable.value===true);
const displayPreview = computed(() => {
  const value = preview.value;
  return value && typeof value.title==='string' && typeof value.script_id==='string'
    && typeof value.role_count==='number' && typeof value.total_stages==='number'
    && Array.isArray(value.playable_roles) ? value as ScriptPreview : null;
});
const completedSteps = computed(() => steps.value.filter(step=>step.status==='completed').length);
const statusText = computed(() => busy.value ? jobState.value==='generating' ? '正在创作草稿' : jobState.value==='validating' ? '正在校验' : '处理中…'
  : jobState.value==='failed' ? '需要修订' : jobState.value==='interrupted' ? '创作已中断' : preview.value ? canPublish.value ? '校验通过' : '暂不可发布'
  : script.value || mode.value==='ai' ? '等待校验' : '等待导入');
const stepStatus = { pending:'待开始', running:'进行中', completed:'已完成', failed:'未通过', interrupted:'已中断' };
const checkStatus = { passed:'通过', failed:'未通过', warning:'提醒' };
function record(value: unknown): Record<string, unknown> {
  return value && typeof value==='object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function text(value: unknown): string { return typeof value==='string' ? value : ''; }
function stageEntries(value: unknown): [string, Record<string, unknown>][] {
  return Object.entries(record(value)).sort(([a],[b])=>Number(a.replace('stage_',''))-Number(b.replace('stage_',''))).map(([key,value])=>[key,record(value)]);
}
function stageLabel(key: string): string { return /^stage_\d+$/.test(key) ? `第 ${key.slice(6)} 幕` : '分幕内容'; }
const opening = computed(() => record(script.value?.opening));
const roles = computed(() => Array.isArray(script.value?.roles) ? script.value.roles.map(record) : []);
const stages = computed(() => stageEntries(script.value?.stage_flow));
function blocks(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.map(record) : []; }
function publicTasks(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string=>typeof item==='string') : []; }
function roleName(id: string): string { return text(roles.value.find(role=>role.role_id===id)?.role_name) || '角色'; }
onBeforeUnmount(()=>{destroyed=true;clearTimeout(pollTimer);finishWait?.();});
onMounted(async()=>{
  if(!route.query.edit){if(savedJob.value)await restoreDraft();return;}
  const currentOperation=++operation;busy.value=true;
  try {
    let saved:AuthoringJob | undefined;
    if(savedJob.value){try{saved=await getApiClient().request<AuthoringJob>(`/api/v1/authoring-jobs/${savedJob.value}`);}catch{ /* A missing old task must not block editing this script. */ }}
    if(destroyed)return;
    if(saved?.catalog_id===String(route.query.edit) && saved.status!=='published'){
      jobId.value=savedJob.value;await pollJob(jobId.value,true,saved);return;
    }
    const data=await getApiClient().request<{script:Record<string,unknown>;source_job_id?:string|null}>(`/api/v1/scripts/${encodeURIComponent(String(route.query.edit))}/edit`);
    if(!destroyed){
      adoptDraft(data.script,'编辑已发布剧本 · 新版本');
      sourceJobId.value=data.source_job_id || null;returnedDraft.value=Boolean(sourceJobId.value);
    }
  } catch(reason){if(currentOperation===operation)error.value=(reason as Error).message;}
  finally{if(currentOperation===operation)busy.value=false;}
});
const tags = () => [...new Set(tagsText.value.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean))];
function clearReview(): void { preview.value=null;publishable.value=undefined;steps.value=[];jobId.value='';jobState.value='';cancelled=false;cancelling.value=false; }
function invalidatePreview(reviseDraft=true): void {
  clearReview();
  if(reviseDraft && returnedDraft.value && script.value)mode.value='import';
  if(script.value && !draftTextError.value)draftText.value=JSON.stringify(normalizedScript(),null,2);
}
function adoptDraft(value: Record<string, unknown>, name?: string): void {
  script.value=value;
  const meta=record(value.script_meta);
  title.value=text(meta.title);
  tagsText.value=publicTasks(meta.tags).join('，');
  tagDraft.value='';draftText.value=JSON.stringify(value,null,2);draftTextError.value='';
  if(name){fileName.value=name;fileSize.value=null;mode.value='import';}
}
function editDraft(event: Event): void {
  draftText.value=(event.target as HTMLTextAreaElement).value;clearReview();
  try {
    const parsed=JSON.parse(draftText.value);
    if(!parsed || typeof parsed!=='object' || Array.isArray(parsed))throw new Error('剧本必须是 JSON 对象');
    const content=draftText.value;adoptDraft(parsed);draftText.value=content;mode.value='import';
  } catch(reason){draftTextError.value=reason instanceof SyntaxError ? '草稿格式尚未完整，请检查后再校验。' : (reason as Error).message;}
}
function changeMode(value: 'import' | 'ai'): void {
  if(mode.value===value)return;
  mode.value=value;clearReview();
  if(value==='ai'){
    returnedDraft.value=false;sourceJobId.value=null;draftTextError.value='';
    if(script.value)draftText.value=JSON.stringify(normalizedScript(),null,2);
  }
}
function addTag(): boolean {
  if (!editable.value || busy.value) return false;
  const added = tagDraft.value.split(/[,，]/).map(tag=>tag.trim()).filter(Boolean);
  const next = [...new Set([...tags(), ...added])];
  if (next.length>12 || next.some(tag=>tag.length>24)) { error.value='最多 12 个标签，每个最多 24 字。'; return false; }
  tagsText.value = next.join('，');
  tagDraft.value = '';
  invalidatePreview();
  return true;
}
function removeTag(value: string): void { tagsText.value=tags().filter(tag=>tag!==value).join('，'); invalidatePreview(); }
async function readFile(file?: File): Promise<void> {
  if (!file || busy.value) return;
  clearReview();returnedDraft.value=false;sourceJobId.value=null;draftText.value='';draftTextError.value='';
  tagDraft.value = '';
  script.value = null;
  title.value = '';
  tagsText.value = '';
  error.value = "";
  fileName.value = file.name;
  fileSize.value = file.size;
  if (file.size > 5 * 1024 * 1024) { error.value = "剧本文件不能超过 5 MB"; return; }
  try {
    const parsed = JSON.parse(await file.text());
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("剧本必须是 JSON 对象");
    adoptDraft(parsed);
  } catch (reason) { error.value = reason instanceof SyntaxError ? "JSON 格式无效" : (reason as Error).message; }
}
function dropFile(event: DragEvent): void { dragging.value=false; void readFile(event.dataTransfer?.files[0]); }
function normalizedScript(): Record<string, unknown> {
  const draft = JSON.parse(JSON.stringify(script.value));
  draft.script_meta = { ...draft.script_meta, title: title.value.trim(), tags: tags() };
  return draft;
}
async function validate(): Promise<void> {
  if ((mode.value==='import'&&!script.value) || busy.value) return;
  if(mode.value==='import' && draftTextError.value){error.value='请先修正草稿格式，再进行校验。';return;}
  if (mode.value==='ai' && !topic.value.trim()) { error.value='请先填写创作主题。'; return; }
  if (tagDraft.value.trim() && !addTag()) return;
  const currentOperation=++operation;
  busy.value = true; error.value = "";clearReview();jobState.value='queued';
  try {
    const job=await getApiClient().request<AuthoringJob>('/api/v1/authoring-jobs',{method:'POST',body:JSON.stringify({
      mode:mode.value,request_id:crypto.randomUUID(),title:title.value,tags:tags(),topic:topic.value,
      script:mode.value==='import'?normalizedScript():null,catalog_id:currentCatalogId.value,
      source_job_id:mode.value==='import'?sourceJobId.value:null})});
    if(destroyed)return;
    if(mode.value==='ai')sourceJobId.value=job.job_id;
    jobId.value=job.job_id; receiveJob(job);
    savedJob.value=job.job_id;sessionStorage.setItem('authoring:last',job.job_id);
    await pollJob(job.job_id);
  } catch (reason) { if(currentOperation===operation)error.value = (reason as Error).message; }
  finally { if(currentOperation===operation)busy.value = false; }
}
async function publish(): Promise<void> {
  if (!script.value || !canPublish.value || busy.value) return;
  busy.value = true; error.value = "";
  try {
    await getApiClient().request<CatalogScript>(`/api/v1/authoring-jobs/${jobId.value}/publish`, { method: "POST" });
    sessionStorage.removeItem('authoring:last');savedJob.value='';
    appEvents.emit("toast:show", { message: "剧本已发布，可从新建游戏进入" });
    appEvents.emit("navigation:view", { view: "library" });
  } catch (reason) { error.value = (reason as Error).message; }
  finally { busy.value = false; }
}
function receiveJob(job: AuthoringJob, restoring=false): void {
  jobState.value=job.status;
  if(restoring) {
    if(job.mode)mode.value=job.mode;
    if(typeof job.input?.title==='string')title.value=job.input.title;
    if(Array.isArray(job.input?.tags))tagsText.value=job.input.tags.join('，');
    if(typeof job.input?.topic==='string')topic.value=job.input.topic;
  }
  if(job.catalog_id!==undefined)currentCatalogId.value=job.catalog_id;
  if(job.steps)steps.value=job.steps;
  publishable.value=job.can_publish;
  if(job.preview)preview.value=job.preview;
  if(job.mode==='ai' || job.input?.source_job_id || job.preview?.semantic_required===true)
    sourceJobId.value=job.job_id || jobId.value || job.input?.source_job_id || null;
  else if(job.preview?.semantic_required===false || job.input)sourceJobId.value=null;
  if(job.draft && ['preview','failed','interrupted'].includes(job.status)) {
    returnedDraft.value=true;
    adoptDraft(job.draft,restoring ? '已恢复的草稿' : ['failed','interrupted'].includes(job.status) ? '保留的创作草稿' : undefined);
  }
}
async function pollJob(id: string, restoring=false, initialJob?:AuthoringJob): Promise<void> {
  while(!destroyed && !cancelled){
    const job=initialJob || await getApiClient().request<AuthoringJob>(`/api/v1/authoring-jobs/${id}`);initialJob=undefined;
    if(destroyed || cancelled || jobId.value!==id)return;
    if(!cancelling.value || ['failed','interrupted'].includes(job.status))receiveJob(job,restoring);
    if(job.status==='published') {
      sessionStorage.removeItem('authoring:last');savedJob.value='';
      throw new Error('这个任务已经发布，请从剧本库查看');
    }
    if(['failed','interrupted'].includes(job.status))throw new Error(job.error || (job.status==='failed' ? '创作未通过，请查看报告并修订草稿。' : '创作已中断，已完成的草稿会保留。'));
    if(job.status==='preview' && !cancelling.value)return;
    await new Promise<void>(resolve=>{finishWait=resolve;pollTimer=setTimeout(()=>{finishWait=undefined;resolve();},1000);});
  }
}
async function restoreDraft():Promise<void>{
  if(busy.value || !savedJob.value)return;
  const currentOperation=++operation;
  busy.value=true;error.value='';clearReview();jobId.value=savedJob.value;
  try{await pollJob(jobId.value,true);}catch(reason){if(currentOperation===operation)error.value=(reason as Error).message;}finally{if(currentOperation===operation)busy.value=false;}
}
async function cancelTask():Promise<void>{
  if(!jobId.value || cancelling.value)return;
  const cancelId=jobId.value;const cancelOperation=operation;
  cancelling.value=true;
  try {
    const job=await getApiClient().request<AuthoringJob>(`/api/v1/authoring-jobs/${cancelId}/cancel`,{method:'POST'});
    if(destroyed || jobId.value!==cancelId || operation!==cancelOperation)return;
    receiveJob({...job,status:'interrupted'});cancelled=true;operation++;busy.value=false;
    clearTimeout(pollTimer);finishWait?.();
    error.value=job.error || '创作已取消，已完成的草稿会保留。';
  } catch(reason){if(jobId.value===cancelId && operation===cancelOperation)error.value=(reason as Error).message;}
  finally{if(jobId.value===cancelId)cancelling.value=false;}
}
</script>

<template>
  <section class="script-creator-shell">
    <header class="script-creator-header"><h2>{{ currentCatalogId?'编辑剧本 · 发布新版本':'新建剧本' }}</h2><p>导入或创作故事，校验后发布到你的剧本库。</p></header>
    <div class="script-creator-modebar">
      <div class="script-creator-tabs" role="group" aria-label="剧本创作方式"><button :class="{active:mode==='import'}" :aria-pressed="mode==='import'" :disabled="busy" @click="changeMode('import')">导入剧本</button><button :class="{active:mode==='ai'}" :aria-pressed="mode==='ai'" :disabled="busy" @click="changeMode('ai')">AI 创作草稿</button></div>
      <button v-if="savedJob && !busy" class="script-creator-restore" type="button" @click="restoreDraft">恢复上次创作任务</button>
    </div>
    <div class="script-creator-layout">
      <form class="script-creator-form" @submit.prevent="validate">
        <section v-if="mode==='import'" class="script-creator-panel script-creator-import-panel">
          <header class="script-creator-section-heading"><span>01</span><div><h3>导入剧本</h3><p>支持 JSON 格式的剧本文件，校验通过后可预览并发布。</p></div></header>
          <label class="script-creator-dropzone" :class="{'is-dragging':dragging,'is-disabled':busy}" @dragover.prevent="dragging=!busy" @dragleave.prevent="dragging=false" @drop.prevent="dropFile">
            <input ref="fileInput" class="script-creator-file-input" type="file" accept=".json,application/json" aria-label="选择 JSON 剧本文件" :disabled="busy" @change="readFile(($event.target as HTMLInputElement).files?.[0])" />
            <FilePlus2 :size="42" aria-hidden="true" /><strong>拖入剧本文件，或点击选择</strong><span>UTF-8 JSON · 最大 5 MB</span>
          </label>
          <div v-if="fileName" class="script-creator-file-row"><FileText :size="23" aria-hidden="true" /><div><strong>{{ fileName }}</strong><span>{{ fileSize!==null ? `${Math.max(1,Math.ceil(fileSize/1024))} KB · ` : '' }}{{ canPublish?'校验通过':preview?'请查看校验报告':script?'已读取，待校验':'文件未能读取' }}</span></div><CircleCheck v-if="canPublish" class="script-creator-file-check" :size="23" aria-label="文件校验通过" /><button v-else type="button" :disabled="busy" @click="fileInput?.click()">更换文件</button></div>
        </section>
        <section v-else class="script-creator-panel">
          <header class="script-creator-section-heading"><span>01</span><div><h3>创作主题</h3><p>描述故事与角色关系，生成草稿后校验并预览。</p></div></header>
          <div class="script-creator-ai-fields"><label for="scriptCreatorTopic">故事设定</label><textarea id="scriptCreatorTopic" v-model="topic" aria-label="创作主题" maxlength="2000" required placeholder="描述故事背景、角色关系与推理主题…" :disabled="busy" @input="invalidatePreview(false)" /><p>按故事设计、独立开幕、角色本和分幕逐步创作，再进行结构校验与语义审校。</p></div>
        </section>
        <section class="script-creator-panel script-creator-metadata-panel">
          <header class="script-creator-section-heading"><span>02</span><div><h3>基本信息</h3><p>{{ editable?'完善剧本的基本信息，以便在剧本库中展示。':'导入剧本后，可编辑名称和类型标签。' }}</p></div></header>
          <div class="script-creator-field"><label for="scriptCreatorTitle">剧本名称</label><input id="scriptCreatorTitle" v-model="title" maxlength="120" required placeholder="填写剧本名称" :disabled="busy || !editable" @input="invalidatePreview()" /></div>
          <div class="script-creator-field script-creator-tag-field"><label for="scriptCreatorTag">标签</label><div class="script-creator-tag-editor"><span v-for="tag in tags()" :key="tag" class="script-creator-tag-chip">{{ tag }}<button type="button" :aria-label="`移除标签：${tag}`" :disabled="busy || !editable" @click="removeTag(tag)"><X :size="13" aria-hidden="true" /></button></span><div class="script-creator-tag-add"><input id="scriptCreatorTag" v-model="tagDraft" maxlength="24" aria-label="添加类型标签" placeholder="添加标签" :disabled="busy || !editable || tags().length>=12" @input="invalidatePreview()" @keydown.enter.prevent="addTag" /><button type="button" aria-label="添加标签" :disabled="busy || !editable || !tagDraft.trim() || tags().length>=12" @click="addTag"><Plus :size="19" aria-hidden="true" /></button></div><small>最多 12 个标签，每个最多 24 字。</small></div></div>
          <p v-if="returnedDraft && mode==='import'" class="script-creator-revalidation-note">{{ sourceJobId?'沿用故事设计，修订后重新校验并审稿。':'修订草稿后可重新校验结构与线索；这次校验不进行模型审稿。' }}</p>
          <button class="script-creator-gold-button" type="submit" :disabled="busy || !editable || Boolean(draftTextError)">{{ busy?'处理中…':mode==='ai'?'开始分步创作':'校验并预览' }}<ArrowRight :size="22" aria-hidden="true" /></button>
        </section>
        <section v-if="steps.length" class="script-creator-panel script-creator-progress" aria-labelledby="scriptCreatorProgressTitle">
          <header><h3 id="scriptCreatorProgressTitle">创作进度</h3><span>已完成 {{ completedSteps }} / {{ steps.length }} 步</span></header>
          <ol><li v-for="step in steps" :key="step.step_id" :class="`is-${step.status}`"><div><strong>{{ step.label }}</strong><span>{{ stepStatus[step.status] }}</span></div><p v-if="step.error">{{ step.error }}</p></li></ol>
        </section>
        <p v-if="error" class="script-creator-error" role="alert">{{ error }}</p>
        <div v-if="busy" class="script-creator-job-status"><p role="status"><Sparkles :size="17" aria-hidden="true" />{{ statusText }}</p><button v-if="jobId" type="button" :disabled="cancelling" @click="cancelTask">{{ cancelling?'正在取消…':'取消本次创作' }}</button></div>
        <details v-if="script && (mode==='import' || returnedDraft)" class="script-creator-panel script-creator-draft-editor"><summary>编辑完整草稿文件</summary><p>可修订正文、角色、分幕和线索。修改后需要重新校验；请保留完整 JSON 格式。</p><label for="scriptCreatorDraft">剧本草稿（JSON）</label><textarea id="scriptCreatorDraft" :value="draftText" :disabled="busy" spellcheck="false" @input="editDraft" /><p v-if="draftTextError" class="script-creator-error" role="alert">{{ draftTextError }}</p></details>
      </form>
      <aside class="script-creator-panel script-creator-preview" aria-labelledby="scriptCreatorPreviewTitle">
        <header class="script-creator-preview-header"><h3 id="scriptCreatorPreviewTitle">剧本预览</h3><span class="script-creator-preview-status" :class="{'is-validated':canPublish && !busy}" aria-live="polite"><CircleCheck v-if="canPublish && !busy" :size="20" aria-hidden="true" />{{ statusText }}</span></header>
        <template v-if="displayPreview">
          <img class="script-creator-cover" :src="scriptCover(displayPreview.script_id)" :alt="`${displayPreview.title}封面`" />
          <h2 class="script-creator-preview-title">{{ displayPreview.title }}</h2>
          <div class="script-creator-preview-facts"><div class="script-creator-preview-tags"><span v-for="tag in tags()" :key="tag">{{ tag }}</span></div><div class="script-creator-preview-meta"><span><Users :size="20" aria-hidden="true" /><b>{{ displayPreview.role_count }}</b> 位角色</span><span><BookOpen :size="20" aria-hidden="true" /><b>{{ displayPreview.total_stages }}</b> 幕故事</span></div></div>
          <section class="script-creator-preview-story"><h4>故事背景</h4><p>{{ displayPreview.story_background }}</p></section>
          <section class="script-creator-preview-roles"><h4>可选角色</h4><div class="script-creator-cast"><figure v-for="role in displayPreview.playable_roles" :key="role.role_id"><img :src="rolePortrait(role.role_id)" :alt="`${role.role_name}角色头像`" /><figcaption><strong>{{ role.role_name }}</strong><span>{{ role.public_identity }}</span></figcaption></figure></div></section>
          <p class="script-creator-agent-count">本剧本另有 {{ displayPreview.ai_agent_count }} 位角色由 AI 演绎。</p>
        </template>
        <div v-else-if="!returnedDraft" class="script-creator-preview-placeholder"><div class="script-creator-placeholder-art"><BookOpen :size="54" aria-hidden="true" /><span>故事即将展开</span></div><h4>校验后查看剧本预览</h4><p>剧本封面、故事背景和可选角色将在校验成功后显示。</p><ol><li>导入文件或填写创作主题</li><li>完善基本信息并校验</li><li>确认预览后发布</li></ol></div>
        <section v-if="returnedDraft && script" class="script-creator-manuscript" aria-label="完整剧本预览">
          <section class="script-creator-opening"><h4>公共开幕</h4><h5 v-if="opening.title">{{ opening.title }}</h5><p>{{ text(opening.content) || '此草稿未提供独立开幕。' }}</p></section>
          <section class="script-creator-role-books"><h4>角色本</h4><p class="script-creator-reading-note">以下包含私人信息与后续剧情，仅供作者审阅。</p><details v-for="(role,index) in roles" :key="text(role.role_id) || index"><summary>{{ text(role.role_name) || `角色 ${index+1}` }}</summary><p>{{ role.public_identity }}</p><p v-if="role.personality"><b>人物性格</b>{{ role.personality }}</p><p v-if="role.hidden_goal"><b>私人目标</b>{{ role.hidden_goal }}</p><details v-for="[key,knowledge] in stageEntries(role.stage_knowledge)" :key="key"><summary>{{ stageLabel(key) }} · 角色内容</summary><p v-for="(block,blockIndex) in blocks(knowledge.blocks)" :key="text(block.block_id) || blockIndex">{{ block.content }}</p></details></details><p v-if="!roles.length">尚未生成角色本。</p></section>
          <section class="script-creator-stage-books"><h4>分幕内容</h4><details v-for="[key,stage] in stages" :key="key"><summary>{{ text(stage.title) || stageLabel(key) }}</summary><h5>本幕开场</h5><p>{{ stage.public_briefing }}</p><h5 v-if="publicTasks(stage.public_tasks).length">公共任务</h5><ul><li v-for="task in publicTasks(stage.public_tasks)" :key="task">{{ task }}</li></ul><h5 v-if="Object.keys(record(stage.personal_tasks)).length">个人任务</h5><p v-for="(task,roleId) in record(stage.personal_tasks)" :key="roleId"><b>{{ roleName(roleId) }}</b>{{ task }}</p><h5 v-if="stage.dm_hosting">主持提示</h5><p>{{ stage.dm_hosting }}</p></details><p v-if="!stages.length">尚未生成分幕内容。</p></section>
        </section>
        <section v-if="validation || semanticReview" class="script-creator-review" aria-label="校验报告">
          <h4>校验报告</h4>
          <section v-if="validation"><h5>结构与线索校验<span :class="validation.passed?'is-passed':'is-failed'">{{ validation.passed?'通过':'未通过' }}</span></h5><ul class="script-creator-checks"><li v-for="(check,index) in validation.checks" :key="`${check.code}-${index}`" :class="`is-${check.status}`"><strong>{{ check.label }}<span>{{ checkStatus[check.status] }}</span></strong><p>{{ check.message }}</p></li></ul><ul v-if="validation.errors?.length" class="script-creator-report-errors"><li v-for="message in validation.errors" :key="message">{{ message }}</li></ul><ul v-if="validation.warnings?.length" class="script-creator-report-warnings"><li v-for="message in validation.warnings" :key="message">{{ message }}</li></ul></section>
          <section v-if="semanticReview"><h5>语义审校<span :class="`is-${reviewRunning?'running':semanticReview.status==='running'?'incomplete':semanticReview.status}`">{{ semanticReviewLabel }}</span></h5><p>{{ reviewRunning && semanticReview.status==='not_run'?'正在核对公共内容、角色成稿与证据链，完成后展示完整报告。':semanticReview.summary }}</p><ul v-if="semanticReview.issues?.length" class="script-creator-semantic-issues"><li v-for="(issue,index) in semanticReview.issues" :key="`${issue.code}-${index}`" :class="`is-${issue.severity}`"><span>{{ issue.severity==='error'?'需修订':'提醒' }}</span>{{ issue.message }}</li></ul></section>
        </section>
        <p v-if="preview && !canPublish && !busy" class="script-creator-publish-note">当前草稿暂不可发布，请查看未通过的步骤与报告，修订后重新校验。</p>
        <button class="script-creator-gold-button script-creator-publish" type="button" :disabled="busy || !canPublish" @click="publish">发布到剧本库<ArrowRight :size="22" aria-hidden="true" /></button>
      </aside>
    </div>
  </section>
</template>
