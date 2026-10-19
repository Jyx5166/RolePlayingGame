<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { Search } from '@lucide/vue';
const props=defineProps<{name:string;online:boolean;portrait?:string;activity?:{activity:string;at:number;speechAt?:number;searchAt?:number};human?:boolean}>();
const portraitFailed=ref(false);
watch(()=>props.portrait,()=>{portraitFailed.value=false;});
const hasPortrait=computed(()=>Boolean(props.portrait && !portraitFailed.value));
const now=ref(Date.now());
let expiry:ReturnType<typeof setTimeout> | undefined;
watch(()=>[props.activity?.speechAt,props.activity?.searchAt],()=>{
  clearTimeout(expiry);now.value=Date.now();
  const until=Math.max(props.activity?.speechAt || 0,props.activity?.searchAt || 0)+2400;
  if(until>now.value)expiry=setTimeout(()=>{now.value=Date.now();},until-now.value+1);
},{immediate:true});
onBeforeUnmount(()=>clearTimeout(expiry));
const state=computed(()=>!props.online?'offline':props.activity?.searchAt && props.activity.searchAt>=(props.activity.speechAt || 0) && now.value-props.activity.searchAt<2400?'searching':
  props.activity?.speechAt && now.value-props.activity.speechAt<2400?'speaking':props.activity?.activity==='thinking'?'thinking':'idle');
const label=computed(()=>props.name+' · '+({offline:'离线',idle:'在线',thinking:'正在思考',speaking:'发言',searching:'搜证'} as Record<string,string>)[state.value]);
</script>
<template>
  <div class="agent-avatar" :class="[`activity-${state}`,{ 'is-human':human,'has-portrait':hasPortrait }]" role="img" :aria-label="label" :title="label">
    <span class="agent-avatar-ripple" aria-hidden="true" />
    <img v-if="hasPortrait" :key="portrait" class="agent-avatar-portrait" :src="portrait" :alt="`${name}的角色肖像`" @error="portraitFailed=true" />
    <b v-else class="agent-avatar-initial" aria-hidden="true">{{ name==='DM'?'DM':Array.from(name)[0] }}</b>
    <span v-if="!human" class="agent-avatar-wave" aria-hidden="true"><i v-for="bar in 5" :key="bar" /></span>
    <Search v-if="state==='searching'" class="agent-avatar-search" :size="19" aria-hidden="true" />
    <span class="agent-avatar-beacon" aria-hidden="true" />
  </div>
</template>

<style scoped>
.agent-avatar-portrait { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; object-position:center 28%; border-radius:inherit; }
.has-portrait .agent-avatar-wave { opacity:0; pointer-events:none; }
.has-portrait.activity-speaking .agent-avatar-wave { inset:auto 5px 4px; height:12px; opacity:.8; z-index:2; }
.has-portrait.activity-speaking .agent-avatar-wave i { max-height:12px; }
.agent-avatar-beacon, .agent-avatar-ripple { z-index:3; }
</style>
