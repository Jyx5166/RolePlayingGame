import { reactive, onBeforeUnmount } from 'vue';
import { getApiClient } from './runtime';
import { buildCommandEnvelope, reduceRealtimeEnvelope } from './ws-protocol';

export type GameData = Record<string, any>;
export function optimisticSpeech(s:GameData, type:string, content:string, requestId:string) {
  const privateMessage=type==='whisper_speech';
  s.messages.push({type:privateMessage?'whisper_message':'human_speech_echo',role_id:s.init?.role_info?.role_id,
    sender_role_id:s.init?.role_info?.role_id,content,channel:privateMessage?'private':'public',
    conversation_role_id:privateMessage?s.whisper.active_target_role_id:undefined,request_id:requestId,
    client_id:requestId,delivery:'sending'});
}
export function interruptPendingMessages(s:GameData) {
  for(const message of s.messages)if(message.delivery==='sending')message.delivery='unconfirmed';
  s.agentActivity={};s.pendingRequestId=null;
}
export function applyGameEvent(s: GameData, event: GameData): void {
  if(event.type==='clue_disclosed' && event.scope==='private')event={...event,channel:'private',conversation_role_id:event.target_role_id};
  switch (event.type) {
    case 'phase_changed':
      if(s.phase.phase!==event.phase.phase || s.phase.stage!==event.phase.stage)s.narration='';
      s.phase = event.phase; break;
    case 'dm_narration_start': s.narration = ''; break;
    case 'dm_narration_chunk': s.narration += event.content; break;
    case 'private_script': s.assignment = event.assignment; break;
    case 'investigation_open': s.info = event.stage_info; s.clues = event.clues || []; s.whisper = event.whisper_status; s.init.search_status=event.search_status; s.searchAp=event.search_status?.remaining_ap ?? null; if(!s.whisper?.active_target_role_id)s.channel='public';break;
    case 'stage_resolution': s.resolution = event.resolution; s.voteTarget = ''; break;
    case 'stage_vote_result': s.resolution = event.resolution || s.resolution; break;
    case 'search_result': if (event.clue && !s.clues.some((c: GameData) => c.clue_id === event.clue.clue_id)) s.clues.push(event.clue);s.searchAp=event.remaining_ap;break;
    case 'whisper_accepted': s.whisper={enabled:true,active_target_role_id:event.target_role_id,remaining_sessions:event.remaining_sessions};s.channel='private';break;
    case 'whisper_closed': s.whisper={...s.whisper,active_target_role_id:null};s.channel='public';break;
    case 'whisper_declined': s.error=event.message || '对方拒绝了私聊';break;
    case 'investigation_progress': s.phase.end_condition = event.condition; break;
    case 'investigation_end_vote': s.endVote = event.vote; break;
    case 'replay': s.replay = event; s.phase.phase = 'replay'; break;
    case 'agent_activity':
      s.agentActivity ||= {};
      s.agentActivity[event.actor_role_id]={...s.agentActivity[event.actor_role_id],activity:event.activity,at:Date.now(),
        ...(event.activity==='searching'?{searchAt:Date.now()}:{})};break;
    case 'actor_turn_stopped': s.error=event.message || '角色本回合未能完成';break;
    case 'error':
      s.error = event.message || '操作未执行';
      for(const message of s.messages)if(event.request_id && message.request_id===event.request_id && message.delivery && message.delivery!=='sent')message.delivery='failed';
      if(event.request_id===s.pendingRequestId){s.busy=false;s.pendingRequestId=null;}break;
    case 'game_command_complete':
      if(!s.pendingRequestId || event.request_id===s.pendingRequestId){s.busy=false;s.pendingRequestId=null;}
      for(const message of s.messages)if(message.request_id===event.request_id && message.delivery==='sending')message.delivery='unconfirmed';break;
  }
  if (['human_speech_echo','ai_speech','ai_proactive_speech','dm_task_published','dm_host_action','whisper_message','clue_disclosed','agent_search_result','hint','speech_warning'].includes(event.type)) {
    const pending=event.request_id && s.messages.find((m:GameData)=>m.client_id===event.request_id &&
      (event.type==='human_speech_echo' || event.sender_role_id===s.init?.role_info?.role_id));
    if(pending)Object.assign(pending,event,{delivery:'sent'});
    else s.messages.push(event);
    const actor=event.actor_role_id || event.sender_role_id || event.role_id || (event.type.startsWith('dm_')?'dm':null);
    if(actor && actor!==s.init?.role_info?.role_id) {
      s.agentActivity ||= {};
      const searching=event.type==='agent_search_result' && !event.content;
      s.agentActivity[actor]={...s.agentActivity[actor],activity:'idle',at:Date.now(),[searching?'searchAt':'speechAt']:Date.now()};
    }
  }
}

export function useGameSession(gameId: number) {
  const s = reactive<GameData>({ detail:null, init:null, phase:{}, narration:'', openingScene:null, assignment:null, info:[], clues:[], messages:[],
    whisper:{}, resolution:null, replay:null, busy:false, connected:false, conflict:false, error:'', notebook:{automatic:[],manual_notes:''}, searchAp:null,
    channel:'public', target:'', speech:'', voteTarget:'', endVote:null, remaining:null,agentActivity:{},pendingRequestId:null });
  let socket: WebSocket | null = null, stopped = false, cursor = 0, reconnect = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let deadline: number | null = null;
  const clock = setInterval(() => { s.remaining = deadline === null ? null : Math.max(0,Math.ceil((deadline-Date.now())/1000)); },1000);
  let controller = sessionStorage.getItem('game_controller_id');
  if (!controller) { controller = crypto.randomUUID(); sessionStorage.setItem('game_controller_id',controller); }
  async function refreshNotebook() {
    try {
      const manual=s.notebook.manual_notes, dirty=s.notesDirty;
      s.notebook = await getApiClient().request<GameData>(`/api/v1/games/${gameId}/notebook`);
      s.clues=s.notebook.clues || s.clues;
      if (dirty) s.notebook.manual_notes=manual;
    } catch (e) { s.error = (e as Error).message; }
  }
  function snapshot(game: GameData) {
    const pending=s.messages.filter((m:GameData)=>m.client_id && m.delivery!=='sent');
    s.init = game; s.phase = game.phase; s.clues = game.clues || []; s.whisper = game.whisper_status || {};
    s.searchAp=game.search_status?.remaining_ap ?? null;
    s.info = game.stage_info || []; s.messages = [];
    for (const record of game.history_events || []) applyGameEvent(s, {type:record.type,...record.payload});
    for(const message of pending)if(!s.messages.some((m:GameData)=>m.request_id===message.request_id &&
      (m.type==='human_speech_echo' || m.sender_role_id===game.role_info?.role_id)))s.messages.push({...message,delivery:'unconfirmed'});
    s.agentActivity={};s.busy=false;s.pendingRequestId=null;
  }
  async function connect() {
    if (stopped) return;
    try {
      const ticket = await getApiClient().request<{ticket:string}>(`/api/v1/games/${gameId}/ws-ticket?controller_id=${encodeURIComponent(controller!)}`,{method:'POST'});
      if (stopped) return;
      const current = new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/v1/games/${gameId}?ticket=${encodeURIComponent(ticket.ticket)}&after_event_id=${cursor}`);
      socket = current;
      current.onopen = () => { s.connected = true; reconnect = 0; s.conflict = false; };
      current.onmessage = (raw) => {
        if (socket!==current) return;
        try {
          const reduction = reduceRealtimeEnvelope(JSON.parse(raw.data),cursor);
          cursor = reduction.lastEventId;
          if (reduction.snapshotGame) snapshot(reduction.snapshotGame);
          for (const event of reduction.messages) {
            applyGameEvent(s,event);
            if (event.type==='phase_changed') deadline = typeof s.phase.remaining_seconds==='number' ? Date.now()+s.phase.remaining_seconds*1000 : null;
            if (event.type==='game_command_complete') void refreshNotebook();
          }
          if (reduction.snapshotGame) void refreshNotebook();
        } catch (e) { s.error = (e as Error).message; }
      };
      current.onclose = (event) => {
        if (socket!==current) return;
        socket = null; s.connected = false; s.busy = false; deadline = null;
        interruptPendingMessages(s);
        if (stopped) return;
        s.error = event.reason || '连接已断开，游戏计时冻结';
        if (event.code===4409) { s.conflict=true; return; }
        if ([4401,4404].includes(event.code)) return;
        if (reconnect<5) timer = setTimeout(() => { void connect(); }, Math.min(10,2**reconnect++)*1000);
      };
    } catch (e) { s.error=(e as Error).message; }
  }
  function command(type: string, payload: GameData={}) {
    if (!s.init || !socket || socket.readyState!==WebSocket.OPEN || s.busy) return false;
    const envelope=buildCommandEnvelope(gameId,{type,...payload});
    const requestId=String(envelope.request_id);
    if(['player_speech','whisper_speech'].includes(type))optimisticSpeech(s,type,payload.content,requestId);
    s.busy=true;s.pendingRequestId=requestId;s.error='';
    try{socket.send(JSON.stringify(envelope));return true;}
    catch(e){applyGameEvent(s,{type:'error',request_id:requestId,message:(e as Error).message});return false;}
  }
  function disconnect() { stopped=true; clearTimeout(timer); socket?.close(); socket=null; deadline=null; }
  async function pause() { disconnect(); if(await saveNotes()===false)throw new Error('手记未能保存，请检查连接后重试'); await getApiClient().request(`/api/v1/games/${gameId}/pause`,{method:'POST'}); }
  async function saveNotes() {
    if (!s.detail || !s.init || s.detail.status==='preparing') return;
    try{await getApiClient().request(`/api/v1/games/${gameId}/notebook/manual`,{method:'PUT',body:JSON.stringify({content:s.notebook.manual_notes || ''})});s.notesDirty=false;return true;}
    catch(e){s.error=(e as Error).message;return false;}
  }
  async function takeOver() {
    await getApiClient().request(`/api/v1/games/${gameId}/takeover`,{method:'POST'});
    stopped=false; await connect();
  }
  async function load() {
    try {
      s.detail = await getApiClient().request<GameData>(`/api/v1/games/${gameId}`);
      if (s.detail.lifecycle_version>=4) {
        if (s.detail.current_phase==='opening') {
          // Read the independent prologue before the first realtime snapshot arrives.
          void getApiClient().request<GameData>(`/api/v1/games/${gameId}/preparation`)
            .then(preparation => { s.openingScene=preparation.opening; })
            .catch(e => { s.error=(e as Error).message; });
        }
        await connect();
      }
    }
    catch(e) { s.error=(e as Error).message; }
  }
  onBeforeUnmount(() => { disconnect(); clearInterval(clock); });
  void load();
  return {s,command,pause,saveNotes,takeOver,refreshNotebook};
}
