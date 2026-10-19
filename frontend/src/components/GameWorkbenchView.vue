<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue';
import { useGameSession, type GameData } from '../game-session';
import { appEvents } from '../app-events';
import RoleAuditView from './RoleAuditView.vue';
import AgentAvatar from './AgentAvatar.vue';
import { rolePortrait } from '../script-artwork';
import { ChevronDown, UserRound } from '@lucide/vue';
const props = defineProps<{gameId:number}>();
const {s,command,pause,saveNotes,takeOver} = useGameSession(props.gameId);
const currentPhase = computed(() => s.phase.phase || s.detail?.current_phase);
const currentStage = computed(() => s.phase.stage || s.detail?.current_stage);
const opening = computed(() => currentPhase.value==='opening');
const hasOpening = computed(() => s.phase.has_opening ?? s.detail?.has_opening ?? (opening.value || Boolean(s.openingScene)));
const beforeFirstStage = computed(() => s.phase.before_first_stage ?? s.detail?.before_first_stage ?? (opening.value || (hasOpening.value && currentStage.value===1 && currentPhase.value==='private_reveal')));
const phaseTitle = computed(() => opening.value ? s.phase.stage_title || s.openingScene?.title || '故事开幕' : beforeFirstStage.value ? '角色剧本' : s.phase.stage_title);
const phaseLabel = computed(() => s.phase.phase_label || (opening.value ? '故事开幕' : currentPhase.value==='private_reveal' ? '角色剧本' : currentPhase.value==='briefing' ? '本幕开场' : ''));
const sequence = computed(() => hasOpening.value && currentStage.value===1
  ? [['opening','开幕'],['private_reveal','角色剧本'],['briefing','第一幕'],['investigation','自由调查'],['dm_hosting','DM 主持'],['replay','复盘']]
  : [['briefing','开场'],['private_reveal','角色剧本'],['investigation','自由调查'],['dm_hosting','DM 主持'],['replay','复盘']]);
const continueLabel = computed(() => {
  if(s.phase.continue_label)return s.phase.continue_label;
  if(opening.value)return '接收角色剧本';
  if(currentPhase.value==='private_reveal')return beforeFirstStage.value ? '开始第一幕' : '开始调查';
  if(currentPhase.value==='briefing')return hasOpening.value && currentStage.value===1 ? '开始调查' : '接收角色剧本';
  return '进入下一阶段';
});
const tab = ref('clues'); const audit = ref(false);
const roleInfoOpen = ref(false);
const auditButton = ref<HTMLButtonElement>();
const shareDialog = ref<HTMLDialogElement>();
const shareDraft = ref<GameData>();
const shareText = ref('');
const shareDestination = ref<{scope:string;targetRoleId:string|null}>({scope:'public',targetRoleId:null});
const shareTriggerId = ref('');
const roleName = (id:string) => s.init?.public_roles?.find((r:GameData)=>r.role_id===id)?.role_name || id || 'DM';
const targets = computed(() => s.init?.search_status?.targets || (s.init?.active_mechanics?.find((m:GameData)=>m.name==='search')?.actions?.[0]?.targets || []).filter((t:GameData)=>t.unlock_stage<=s.phase.stage));
const visibleMessages = computed(() => s.messages.filter((m:GameData)=>s.channel==='private' ? (m.type==='whisper_message' || m.channel==='private') && (m.conversation_role_id || m.target_role_id)===s.whisper.active_target_role_id : m.type!=='whisper_message' && m.channel!=='private'));
const privateOpen = computed(() => Boolean(s.whisper?.active_target_role_id));
const messagesPanel=ref<HTMLElement>();
const phaseScroll=ref<HTMLElement>();
watch(()=>`${currentStage.value}:${currentPhase.value}`,async()=>{await nextTick();if(phaseScroll.value)phaseScroll.value.scrollTop=0;},{flush:'post'});
watch(()=>[visibleMessages.value.length,s.phase.phase],async()=>{await nextTick();const panel=messagesPanel.value;if(panel)panel.scrollTop=panel.scrollHeight;},{flush:'post'});
async function leave() { try { await pause(); appEvents.emit('navigation:view',{view:'records'}); } catch(e) {s.error=(e as Error).message;} }
function speak() {if(s.speech.trim() && command(s.channel==='private'?'whisper_speech':'player_speech',{content:s.speech.trim()}))s.speech='';}
function messageRole(message:GameData):string {
  if(message.type==='human_speech_echo')return message.role_id || message.sender_role_id || s.init?.role_info?.role_id || 'dm';
  if(message.type?.startsWith('dm_') || ['hint','speech_warning'].includes(message.type))return 'dm';
  // A record owner or conversation target may be the listener, never the speaker.
  return message.sender_role_id || message.actor_role_id || message.role_id || 'dm';
}
function messageName(message:GameData):string {
  const id=messageRole(message);
  if(id==='dm')return 'DM';
  return s.init?.public_roles?.find((role:GameData)=>role.role_id===id)?.role_name
    || message.sender_role_name || message.actor_role_name || message.role_name || id;
}
const ownMessage=(message:GameData)=>message.type==='human_speech_echo' || messageRole(message)===s.init?.role_info.role_id;
const deliveryLabel=(message:GameData)=>({sending:'发送中',failed:'发送失败',unconfirmed:'发送状态未确认，请核对聊天记录'} as Record<string,string>)[message.delivery];
const canShareDraft = computed(()=>s.connected && !s.busy && s.phase.phase==='investigation' && (shareDestination.value.scope!=='private' || shareDestination.value.targetRoleId===s.whisper.active_target_role_id));
async function share(clue:GameData,mode:string) {
  if(mode==='distorted') {
    shareTriggerId.value=`share-clue-${props.gameId}-${clue.clue_id}`;
    shareDraft.value=clue;shareText.value='';
    shareDestination.value={scope:s.channel,targetRoleId:s.channel==='private'?s.whisper.active_target_role_id:null};
    await nextTick();shareDialog.value?.showModal();return;
  }
  command('share_clue',{clue_id:clue.clue_id,mode,content:'',scope:s.channel,target_role_id:s.channel==='private'?s.whisper.active_target_role_id:null});
}
function closeShare() {shareDialog.value?.close();}
async function restoreShareFocus() {await nextTick();document.getElementById(shareTriggerId.value)?.focus();}
function publishShare() {
  if(!shareDraft.value || !shareText.value.trim() || !canShareDraft.value)return;
  command('share_clue',{clue_id:shareDraft.value.clue_id,mode:'distorted',content:shareText.value.trim(),scope:shareDestination.value.scope,target_role_id:shareDestination.value.targetRoleId});
  closeShare();
}
const taskStatus = (status:string) => (({completed:'已完成',failed:'未完成',manual_review:'待复盘'} as Record<string,string>)[status] || status);
const timelineLabel = (key:string) => key.startsWith('stage_') ? `第 ${key.slice(6)} 幕` : key;
async function closeAudit() { audit.value=false; await nextTick(); auditButton.value?.focus(); }
</script>

<template>
  <section v-if="s.detail?.lifecycle_version>=4" class="modern-workbench">
    <header class="game-toolbar"><button class="icon-button bordered" aria-label="暂停并返回游戏记录" @click="leave">←</button><div class="game-title-block"><p class="case-label">GAME #{{ gameId }} · {{ phaseTitle }}</p><h2>{{ s.detail.title }}</h2></div><span class="connection-state">{{ s.connected?'已连接':'计时冻结' }}</span><div v-if="s.remaining!==null && currentPhase==='investigation'" class="round-clock"><span>调查剩余</span><strong>{{ Math.floor(s.remaining/60) }}:{{ String(s.remaining%60).padStart(2,'0') }}</strong></div><div class="stage-badge"><span v-if="beforeFirstStage">{{ opening?'故事开幕':'角色准备' }}</span><span v-else>第 {{ currentStage }} / {{ s.detail.total_stages }} 幕</span></div></header>
    <p v-if="s.error" class="form-error" role="alert">{{ s.error }} <button v-if="s.conflict" class="secondary-button" @click="takeOver">接管本场游戏</button></p>
    <nav class="modern-sequence" aria-label="游戏阶段"><span v-for="step in sequence" :key="step[0]" :class="{active:currentPhase===step[0]}">{{ step[1] }}</span></nav>
    <section v-if="currentPhase!=='investigation'" class="phase-stage modern-stage">
      <div ref="phaseScroll" class="modern-phase-scroll"><div class="modern-phase-content">
        <header class="modern-phase-heading"><p class="case-label">{{ phaseLabel }}</p><h2>{{ phaseTitle }}</h2></header>
        <section v-if="currentPhase==='private_reveal' && s.assignment" class="private-role-card">
          <h3>{{ s.assignment.role_name }}</h3><p class="role-identity">{{ s.assignment.public_identity }}</p>
          <article v-for="block in s.assignment.blocks" :key="block.block_id" class="dossier-block"><p>{{ block.content }}</p></article>
          <div class="personal-mission"><span>我的任务</span><p>{{ s.assignment.personal_task }}</p></div>
        </section>
        <p v-else-if="!s.replay" class="modern-narration phase-narration" :aria-label="opening ? '剧本开幕' : undefined">{{ (opening ? s.openingScene?.content : '') || (currentPhase==='private_reveal' ? '正在读取角色剧本…' : s.narration) || (opening ? '正在读取开幕…' : 'DM 正在准备本幕内容…') }}</p>
        <section v-if="s.resolution && s.phase.phase==='dm_hosting'" class="stage-resolution">
          <h3>{{ s.resolution.title || '本幕结算' }}</h3><p v-if="s.resolution.summary">{{ s.resolution.summary }}</p>
          <form v-if="s.resolution.vote?.pending" class="modern-vote" @submit.prevent="command('stage_vote',{target_role_id:s.voteTarget})">
            <fieldset class="vote-options" :disabled="s.busy || !s.connected">
              <legend>{{ s.resolution.vote.prompt || '选择指认对象' }}</legend>
              <div class="role-options"><label v-for="role in s.resolution.vote.eligible_roles" :key="role.role_id" class="role-option"><input v-model="s.voteTarget" type="radio" :name="`game-${gameId}-stage-vote`" :value="role.role_id" /><span><strong>{{ role.role_name }}</strong><span>{{ role.public_identity }}</span></span></label></div>
            </fieldset>
            <div class="modern-vote-actions"><span>{{ s.voteTarget ? '已选择 '+roleName(s.voteTarget) : '选择一位角色后提交本幕指认' }}</span><button class="primary-button" type="submit" :disabled="!s.voteTarget || s.busy || !s.connected">{{ s.busy?'正在提交…':'提交指认' }}</button></div>
          </form>
          <p v-else class="vote-outcome">{{ s.resolution.vote?.outcome_text }}</p>
          <details class="modern-result-details"><summary>查看本幕各角色任务结果</summary><div class="modern-result-grid"><article v-for="result in s.resolution.role_results" :key="result.role_id"><header><strong>{{ result.role_name }}</strong><span>{{ s.resolution.metric?.label || '本幕积分' }} {{ result.total }}（{{ result.delta>=0?'+':'' }}{{ result.delta }}）</span></header><ul><li v-for="(task,index) in result.task_results || []" :key="index"><span>{{ task.description || task.label }}</span><b :class="task.status">{{ taskStatus(task.status) }}</b></li></ul><p v-if="!result.task_results?.length">本幕暂无可公开的任务结果。</p></article></div></details>
        </section>
        <section v-if="s.replay" class="replay-card">
          <h3>{{ s.replay.verdict || s.replay.final_decision?.outcome_text || '案件复盘' }}</h3><p class="modern-narration">{{ s.replay.full_story }}</p>
          <details class="modern-result-details"><summary>案件时间线与角色回顾</summary><div class="replay-sections"><section><h4>案件时间线</h4><article v-for="(content,key) in s.replay.timeline" :key="key"><strong>{{ timelineLabel(String(key)) }}</strong><p>{{ content }}</p></article></section><section><h4>角色回顾</h4><article v-for="(content,roleId) in s.replay.role_arcs" :key="roleId"><strong>{{ roleName(String(roleId)) }}</strong><p>{{ content }}</p></article></section></div></details>
          <button ref="auditButton" class="primary-button" @click="audit=true">全部角色与 DM 记录</button>
        </section>
      </div></div>
      <footer v-if="!s.replay" class="modern-stage-actions"><div class="modern-stage-actions-inner"><button class="primary-button phase-continue" :disabled="s.busy || !s.connected || !s.init || !s.phase.phase || s.resolution?.vote?.pending" @click="command('advance_phase')">{{ s.busy?'处理中…':continueLabel }}</button><span v-if="s.resolution?.vote?.pending">完成本幕指认后可继续。</span></div></footer>
    </section>
    <div v-else class="game-layout modern-investigation">
      <aside class="intel-panel investigation-intel">
        <section class="investigation-overview investigation-glass" aria-label="本幕任务与搜证">
          <h3>本幕任务</h3>
          <ul class="investigation-task-list"><li v-for="task in s.phase.public_tasks" :key="task">{{ task }}</li></ul>
          <h3>现场搜证</h3>
          <div class="search-list">
            <button v-for="target in targets" :key="target.id" class="secondary-button wide" :disabled="s.busy || !s.connected || s.searchAp===0" @click="command('search',{target_id:target.id})">{{ target.name || target.target_name || target.id }}</button>
            <p v-if="!targets.length">当前暂无可搜查地点</p>
          </div>
        </section>
        <section class="investigation-notebook investigation-glass" aria-label="调查笔记">
          <div class="notebook-tabs" role="group" aria-label="调查笔记分类">
            <button v-for="option in [['clues','私有线索'],['auto','自动归档'],['manual','推理手记']]" :key="option[0]" :class="{active:tab===option[0]}" :aria-pressed="tab===option[0]" @click="tab=option[0]">{{ option[1] }}</button>
          </div>
          <div class="investigation-notebook-body" :class="{'is-editor':tab==='manual'}">
            <div v-if="tab==='clues'" class="owned-clues">
              <article v-for="clue in s.clues" :key="clue.clue_id"><strong>{{ clue.target_name }}</strong><p>{{ clue.truth_content || clue.content }}</p><div class="notebook-clue-actions"><button class="text-button" :disabled="s.busy" @click="share(clue,'truthful')">分享原文</button><button :id="`share-clue-${gameId}-${clue.clue_id}`" class="text-button" :disabled="s.busy" @click="share(clue,'distorted')">改写后分享</button></div></article>
              <p v-if="!s.clues.length" class="notebook-empty">尚未取得私有线索</p>
            </div>
            <div v-if="tab==='auto'" class="notebook-auto-entries">
              <article v-for="note in s.notebook.automatic" :key="note.id"><strong>{{ note.title }}</strong><p>{{ note.content }}</p></article>
              <p v-if="!s.notebook.automatic.length" class="notebook-empty">本局获得的信息会自动归档在这里。</p>
            </div>
            <div v-if="tab==='manual'" class="notebook-editor">
              <textarea v-model="s.notebook.manual_notes" aria-label="推理手记" maxlength="10000" placeholder="记录时间线与待验证推断…" @input="s.notesDirty=true" @change="saveNotes" />
              <div class="notebook-editor-footer"><span>{{ s.notesDirty?'有未保存的修改':'修改会自动保存' }}</span><button class="secondary-button notebook-save" @click="saveNotes">保存手记</button></div>
            </div>
          </div>
        </section>
        <section class="investigation-role investigation-glass" :class="{'is-open':roleInfoOpen}">
          <button class="investigation-role-toggle" type="button" :aria-expanded="roleInfoOpen" :aria-controls="`game-${gameId}-role-info`" @click="roleInfoOpen=!roleInfoOpen"><UserRound :size="17" aria-hidden="true" /><span>我的角色信息</span><ChevronDown :size="16" class="role-toggle-chevron" aria-hidden="true" /></button>
          <div v-if="roleInfoOpen" :id="`game-${gameId}-role-info`" class="investigation-role-body"><p v-for="block in s.info" :key="block.block_id">{{ block.content }}</p><p v-if="!s.info.length" class="notebook-empty">本幕暂无角色补充信息。</p></div>
        </section>
      </aside>
      <section class="dialogue-panel">
        <header class="dialogue-header"><div><span>INTERROGATION LOG</span><strong>{{ s.channel==='private'?'与 '+roleName(s.whisper.active_target_role_id)+' 的私聊':'公开询问记录' }}</strong></div><span>{{ s.busy?'Agent 正在行动…':'等待行动' }}</span></header>
        <div ref="messagesPanel" class="messages" role="log" aria-label="聊天记录" aria-live="polite">
          <article v-for="(message,index) in visibleMessages" :key="message.client_id || index" class="message message-chat" :class="ownMessage(message)?'user':'agent'">
            <AgentAvatar :name="messageName(message)" :portrait="rolePortrait(messageRole(message))" :online="s.connected" :human="ownMessage(message)" />
            <div class="message-body"><span class="message-sender">{{ messageName(message) }}</span><p class="message-bubble">{{ message.content || message.shared_content || message.summary }}</p>
              <span v-if="deliveryLabel(message)" class="message-delivery" role="status"><i v-if="message.delivery==='sending'" class="sending-spinner" aria-hidden="true" />{{ deliveryLabel(message) }}</span>
            </div>
          </article>
          <p v-if="!visibleMessages.length" class="empty-state">从一个问题开始，核对各自掌握的信息。</p>
        </div>
        <div class="composer-shell"><div class="channel-control"><button :class="{active:s.channel==='public'}" @click="s.channel='public'">公开询问</button><button :disabled="!privateOpen" :class="{active:s.channel==='private'}" @click="s.channel='private'">秘密询问</button></div><form class="composer" @submit.prevent="speak"><input v-model="s.speech" :aria-label="s.channel==='private'?'私聊消息':'公开询问消息'" maxlength="4000" placeholder="输入证词或问题…" :disabled="s.busy || !s.connected" /><button class="primary-button" :disabled="s.busy || !s.speech.trim() || !s.connected">发送</button></form></div>
      </section>
      <aside class="dm-panel">
        <div class="dm-status"><AgentAvatar name="DM" :online="s.connected" :activity="s.agentActivity?.dm" /><div><strong>主持 Agent</strong><p>{{ s.connected?'在线':'离线' }} · {{ s.phase.phase_label }}</p></div></div>
        <h3>参与角色</h3><div class="cast-list"><article v-for="role in s.init?.public_roles" :key="role.role_id">
          <header class="cast-member"><AgentAvatar :name="role.role_name" :portrait="rolePortrait(role.role_id)" :online="s.connected" :activity="s.agentActivity?.[role.role_id]" :human="role.role_id===s.init?.role_info.role_id" /><div><strong>{{ role.role_name }}</strong><span class="cast-presence">{{ role.role_id===s.init?.role_info.role_id?'我':s.connected?'角色 Agent · 在线':'角色 Agent · 离线' }}</span></div></header>
          <p>{{ role.public_identity }}</p><button v-if="role.role_id!==s.init?.role_info.role_id && s.phase.enabled_actions?.includes('whisper')" class="text-button" :disabled="s.busy || !s.connected" @click="command('whisper_invite',{target_role_id:role.role_id}); s.target=role.role_id">发起私聊</button>
        </article></div>
        <p v-if="privateOpen">私聊对象：{{ roleName(s.whisper.active_target_role_id) }} <button class="text-button" :disabled="s.busy" @click="command('whisper_close');s.channel='public'">结束私聊</button></p><div class="phase-rules"><span>调查结束条件</span><p>{{ s.phase.end_condition_text }}</p></div><p v-if="s.endVote">{{ s.endVote.approved?'结束投票通过':'结束投票未通过，可继续调查' }}</p><button class="secondary-button wide" :disabled="s.busy || !s.connected || !s.phase.can_manual_end" @click="command('request_phase_end')">发起结束调查投票</button>
      </aside>
    </div>
    <dialog ref="shareDialog" class="clue-share-dialog" :aria-labelledby="`game-${gameId}-share-title`" @cancel.prevent="closeShare" @close="restoreShareFocus">
      <form @submit.prevent="publishShare"><header><p class="case-label">{{ shareDestination.scope==='private'?'私聊分享':'公开分享' }}</p><h3 :id="`game-${gameId}-share-title`">改写线索说法</h3><p>分享至：{{ shareDestination.scope==='private'?roleName(shareDestination.targetRoleId || ''):'公开频道' }}</p></header><blockquote>{{ shareDraft?.truth_content || shareDraft?.content }}</blockquote><label>新的线索说法<textarea v-model="shareText" maxlength="4000" required placeholder="写下你希望分享的说法…" /></label><p>原始线索会保留在你的私人档案中。</p><p v-if="shareDestination.scope==='private' && shareDestination.targetRoleId!==s.whisper.active_target_role_id" class="form-error">私聊已结束，请关闭后重新选择分享对象。</p><footer><button class="secondary-button" type="button" @click="closeShare">取消</button><button class="primary-button" :disabled="!shareText.trim() || !canShareDraft">确认分享</button></footer></form>
    </dialog>
    <RoleAuditView v-if="audit" :game-id="gameId" @close="closeAudit" />
  </section>
</template>
