import { describe,it,expect } from 'vitest';
import { applyGameEvent, optimisticSpeech, interruptPendingMessages } from './game-session';
const initial=()=>({phase:{},messages:[],clues:[],whisper:{},busy:true,voteTarget:'a'});
describe('game session',()=>{
  it('keeps command busy after a role response until completion',()=>{const s=initial();applyGameEvent(s,{type:'ai_speech',role_id:'role',content:'证词'});expect(s.busy).toBe(true);applyGameEvent(s,{type:'game_command_complete'});expect(s.busy).toBe(false);});
  it('opens private channel only after consent and clears it on close',()=>{const s:any=initial();applyGameEvent(s,{type:'whisper_declined',message:'拒绝'});expect(s.whisper.active_target_role_id).toBeUndefined();applyGameEvent(s,{type:'whisper_accepted',target_role_id:'a',remaining_sessions:1});expect(s.channel).toBe('private');applyGameEvent(s,{type:'whisper_closed'});expect(s.channel).toBe('public');expect(s.whisper.active_target_role_id).toBeNull();});
  it('retains voting result across completion and resets selection for a new vote',()=>{const s:any=initial();applyGameEvent(s,{type:'stage_resolution',resolution:{stage:2,vote:{pending:true}}});expect(s.voteTarget).toBe('');applyGameEvent(s,{type:'stage_vote_result',resolution:{stage:2,vote:{pending:false}}});applyGameEvent(s,{type:'game_command_complete'});expect(s.resolution.vote.pending).toBe(false);});
});

describe('optimistic chat receipts',()=>{
  const state=()=>({...initial(),init:{role_info:{role_id:'human'}},channel:'public',whisper:{active_target_role_id:'peer'},pendingRequestId:'request-1'});
  it('shows a message before any server response and merges its correlated receipt',()=>{
    const s:any=state();optimisticSpeech(s,'player_speech','现在可见','request-1');
    expect(s.messages[0]).toMatchObject({content:'现在可见',delivery:'sending',channel:'public'});
    applyGameEvent(s,{type:'ai_speech',role_id:'peer',request_id:'request-1',content:'回复'});
    applyGameEvent(s,{type:'human_speech_echo',role_id:'human',request_id:'request-1',content:'现在可见'});
    expect(s.messages).toHaveLength(2);expect(s.messages[0].delivery).toBe('sent');expect(s.busy).toBe(true);
  });
  it('keeps rejection distinct from an accepted message followed by a failed Agent turn',()=>{
    const s:any=state();optimisticSpeech(s,'player_speech','证词','request-1');
    applyGameEvent(s,{type:'error',request_id:'request-1',message:'阶段已过期'});
    expect(s.messages[0].delivery).toBe('failed');expect(s.busy).toBe(false);
    applyGameEvent(s,{type:'human_speech_echo',request_id:'request-1',content:'证词',role_id:'human'});
    applyGameEvent(s,{type:'error',request_id:'request-1',message:'Agent 未完成'});
    expect(s.messages[0].delivery).toBe('sent');
  });
  it('retains uncertainty after disconnect without pretending delivery or resending',()=>{
    const s:any=state();optimisticSpeech(s,'whisper_speech','私聊','request-1');interruptPendingMessages(s);
    expect(s.messages[0]).toMatchObject({delivery:'unconfirmed',channel:'private',conversation_role_id:'peer'});
    applyGameEvent(s,{type:'whisper_message',sender_role_id:'peer',request_id:'request-1',conversation_role_id:'peer',content:'回复'});
    expect(s.messages).toHaveLength(2);expect(s.messages[0].delivery).toBe('unconfirmed');
    applyGameEvent(s,{type:'whisper_message',sender_role_id:'human',request_id:'request-1',conversation_role_id:'peer',content:'私聊'});
    expect(s.messages).toHaveLength(2);expect(s.messages[0].delivery).toBe('sent');
  });
  it('does not unlock a human command when another autonomous command completes',()=>{
    const s:any=state();applyGameEvent(s,{type:'game_command_complete',request_id:'server:other'});expect(s.busy).toBe(true);
    applyGameEvent(s,{type:'game_command_complete',request_id:'request-1'});expect(s.busy).toBe(false);
  });
});
