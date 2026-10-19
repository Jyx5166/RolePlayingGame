<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { getApiClient } from '../runtime';
import type { GameData } from '../game-session';
const props=defineProps<{gameId:number}>(); const emit=defineEmits<{close:[]}>();
const dialog=ref<HTMLDialogElement>();
const records=ref<GameData>(); const selected=ref(''); const logs=ref<GameData[]>([]); const kind=ref('tools'); const offset=ref(0); const more=ref(false); const error=ref(''); const busy=ref(false);
const role=computed(()=>records.value?.roles.find((r:GameData)=>r.role_id===selected.value));
let pageRequest=0;
async function loadPage(reset=false) {
  const current=++pageRequest;
  if(reset){offset.value=0;logs.value=[];error.value='';}
  busy.value=true;
  try {
    const page=await getApiClient().request<GameData>(`/api/v1/games/${props.gameId}/execution-log-pages?kind=${kind.value}&actor_role_id=${encodeURIComponent(selected.value)}&offset=${offset.value}`);
    if(current!==pageRequest)return;
    logs.value.push(...page.items);offset.value=page.next_offset;more.value=page.has_more;
  }catch(e){if(current===pageRequest)error.value=(e as Error).message;}
  finally{if(current===pageRequest)busy.value=false;}
}
watch([selected,kind],()=>{void loadPage(true);});
onMounted(async()=>{await nextTick();dialog.value?.showModal();try{records.value=await getApiClient().request<GameData>(`/api/v1/games/${props.gameId}/role-records`);records.value.roles.push({role_id:'dm',role_name:'DM 主持'});selected.value=records.value.roles[0]?.role_id || 'dm';}catch(e){error.value=(e as Error).message;}});
async function download() {const content=await getApiClient().request<GameData>(`/api/v1/games/${props.gameId}/export`);const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`game-${props.gameId}.json`;a.click();URL.revokeObjectURL(url);}
</script>
<template>
  <dialog ref="dialog" class="role-records-modal modern-audit" aria-labelledby="modernAuditTitle" @cancel="emit('close')">
    <section class="role-records-shell">
      <header class="role-records-header"><div><p class="case-label">GAME #{{ gameId }} · POSTGAME AUDIT</p><h2 id="modernAuditTitle">全部角色与 DM 记录</h2><p>查看各自的原始线索、证词、判断与实际调用。</p></div><button class="secondary-button" @click="download">导出本局记录</button><button class="icon-button" aria-label="关闭角色记录" @click="emit('close')">×</button></header>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <nav class="audit-role-tabs" aria-label="选择记录角色"><button v-for="item in records?.roles" :key="item.role_id" :class="{active:selected===item.role_id}" :aria-pressed="selected===item.role_id" @click="selected=item.role_id">{{ item.role_name }}</button></nav>
      <div class="role-audit-grid" :class="{'dm-audit':selected==='dm'}">
        <section v-if="selected!=='dm'"><h3>角色档案</h3><div v-for="section in [['clues','搜证与披露'],['automatic_notebook','自动线索'],['reasoning_notebook','推理记录'],['operations','操作记录'],['stage_results','任务结算']]" :key="section[0]"><h4>{{ section[1] }}</h4><article v-for="(item,index) in role?.[section[0]] || []" :key="index"><strong>{{ item.title || item.target_name }}</strong><p>{{ item.content || item.truth_content || item.summary }}</p><details><summary>完整记录</summary><pre>{{ JSON.stringify(item,null,2) }}</pre></details></article></div></section>
        <section class="audit-ledger"><h3>执行日志</h3><div class="notebook-tabs"><button :class="{active:kind==='tools'}" :aria-pressed="kind==='tools'" @click="kind='tools'">函数调用</button><button :class="{active:kind==='models'}" :aria-pressed="kind==='models'" @click="kind='models'">模型请求</button></div><article v-for="entry in logs" :key="entry.tool_call_id || entry.model_request_id"><span>{{ entry.started_at }}</span><h4>{{ entry.tool_name || '模型推理' }} · {{ entry.status }}</h4><p>运行 {{ entry.run_id }}<br />回合 {{ entry.turn_id }}</p><details><summary>参数、结果、来源与用量</summary><pre>{{ JSON.stringify(entry,null,2) }}</pre></details></article><p v-if="!logs.length && !busy">暂无记录</p><button v-if="more" class="secondary-button" :disabled="busy" @click="loadPage()">加载更多</button></section>
      </div>
    </section>
  </dialog>
</template>
