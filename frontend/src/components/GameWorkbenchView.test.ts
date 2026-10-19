// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { describe, expect, it, vi } from 'vitest';
import GameWorkbenchView from './GameWorkbenchView.vue';
import { rolePortrait } from '../script-artwork';

const session = vi.hoisted(() => ({state:{} as Record<string,any>, command:vi.fn()}));
vi.mock('../game-session',async()=>{const {reactive}=await import('vue');return {useGameSession:()=>({s:reactive(session.state),command:session.command,pause:vi.fn(),saveNotes:vi.fn(),takeOver:vi.fn()})};});

function setup(phase:string) {
  session.command.mockReset();
  session.state={detail:{lifecycle_version:4,title:'界面验收',current_stage:1,total_stages:3},phase:{phase,stage:1,public_tasks:[]},
    connected:true,busy:false,remaining:null,messages:[],whisper:{},channel:'public',speech:'',voteTarget:'',notebook:{automatic:[],manual_notes:''},clues:[],info:[],
    init:{public_roles:[{role_id:'r1',role_name:'沈知微'},{role_id:'r2',role_name:'顾临川'}],role_info:{role_id:'r1'}}};
}

describe('GameWorkbenchView stage presentation',()=>{
  it('keeps each role portrait consistent across the cast, public messages, and private replies',async()=>{
    setup('investigation');
    session.state.init={public_roles:[{role_id:'shen_zhiwei',role_name:'沈知微'},{role_id:'gu_linchuan',role_name:'顾临川'}],role_info:{role_id:'shen_zhiwei'}};
    session.state.messages=[{type:'human_speech_echo',content:'人工发言回显'},
      {type:'ai_speech',role_id:'gu_linchuan',owner_role_id:'shen_zhiwei',content:'另一角色的回复'}];
    const wrapper=mount(GameWorkbenchView,{props:{gameId:3}});
    const cast=wrapper.findAll('.cast-member img');
    expect(cast.map(image=>image.attributes('src'))).toEqual([rolePortrait('shen_zhiwei'),rolePortrait('gu_linchuan')]);
    expect(cast[0]!.attributes('src')).not.toBe(cast[1]!.attributes('src'));
    expect(wrapper.get('.message.user img').attributes('src')).toBe(cast[0]!.attributes('src'));
    expect(wrapper.get('.message.user .message-sender').text()).toBe('沈知微');
    expect(wrapper.get('.message.agent img').attributes('src')).toBe(cast[1]!.attributes('src'));
    expect(wrapper.find('.dm-status img').exists()).toBe(false);
    const state=reactive(session.state);state.channel='private';state.whisper={active_target_role_id:'gu_linchuan'};
    state.messages=[{type:'whisper_message',sender_role_id:'gu_linchuan',role_id:'shen_zhiwei',owner_role_id:'shen_zhiwei',conversation_role_id:'gu_linchuan',content:'私聊回复'}];
    await flushPromises();
    expect(wrapper.get('.message.agent img').attributes('src')).toBe(rolePortrait('gu_linchuan'));
    expect(wrapper.get('.message-sender').text()).toBe('顾临川');wrapper.unmount();
  });
  it('never assigns listener ownership or DM guidance to a role portrait',()=>{
    setup('investigation');session.state.messages=[{type:'hint',role_id:'r1',content:'主持人提示'},
      {type:'clue_disclosed',owner_role_id:'r1',content:'来源尚未明确'}];
    const wrapper=mount(GameWorkbenchView,{props:{gameId:3}});
    expect(wrapper.findAll('.messages img')).toHaveLength(0);
    expect(wrapper.findAll('.message-sender').map(name=>name.text())).toEqual(['DM','DM']);wrapper.unmount();
  });
  it('renders own public and private messages on the user side with delivery feedback',async()=>{
    setup('investigation');session.state.messages=[{type:'human_speech_echo',role_id:'r1',content:'我的问题',delivery:'sending'},
      {type:'ai_speech',role_id:'r2',content:'角色回复'}];
    const wrapper=mount(GameWorkbenchView,{props:{gameId:3}});
    expect(wrapper.get('.message.user').text()).toContain('我的问题');expect(wrapper.find('.message.user .sending-spinner').exists()).toBe(true);
    expect(wrapper.get('.message.agent').text()).toContain('角色回复');expect(wrapper.findAll('.dm-panel .agent-avatar')).toHaveLength(3);
    const state=reactive(session.state);state.channel='private';state.whisper={active_target_role_id:'r2'};state.messages=[{type:'whisper_message',sender_role_id:'r1',conversation_role_id:'r2',content:'私聊问题'}];await flushPromises();
    expect(wrapper.get('.message.user').text()).toContain('私聊问题');wrapper.unmount();
  });
  it('keeps the draft if the transport does not accept the command',async()=>{
    setup('investigation');session.state.speech='暂未发出';session.command.mockReturnValue(false);
    const wrapper=mount(GameWorkbenchView,{props:{gameId:3}});await wrapper.get('.composer').trigger('submit');expect(session.state.speech).toBe('暂未发出');
    session.command.mockReturnValue(true);await wrapper.get('.composer').trigger('submit');expect(session.state.speech).toBe('');wrapper.unmount();
  });
  it('requires a selected member of one radio group before sending the stage vote',async()=>{
    setup('dm_hosting');
    session.state.resolution={title:'本幕结算',metric:{label:'证词风险'},role_results:[],vote:{pending:true,prompt:'选择指认对象',eligible_roles:[{role_id:'r1',role_name:'沈知微'},{role_id:'r2',role_name:'顾临川'}]}};
    const wrapper=mount(GameWorkbenchView,{props:{gameId:4}});
    const radios=wrapper.findAll('input[type=radio]');
    expect(new Set(radios.map(radio=>radio.attributes('name'))).size).toBe(1);
    expect(radios[0]!.attributes('name')).toBeTruthy();
    expect((wrapper.get('button[type=submit]').element as HTMLButtonElement).disabled).toBe(true);
    await radios[1]!.setValue(true);
    await wrapper.get('form').trigger('submit');
    expect(session.command).toHaveBeenCalledWith('stage_vote',{target_role_id:'r2'});
    wrapper.unmount();
  });

  it('presents task results and replay facts as readable content',async()=>{
    setup('dm_hosting');
    session.state.resolution={title:'本幕结算',metric:{label:'证词风险'},vote:{pending:false,outcome_text:'本幕结果已记录'},role_results:[{role_id:'r1',role_name:'沈知微',total:3,delta:1,task_results:[{label:'核对时间线',status:'completed'}]}]};
    let wrapper=mount(GameWorkbenchView,{props:{gameId:4}});
    expect(wrapper.text()).toContain('核对时间线'); expect(wrapper.text()).toContain('已完成');
    expect(wrapper.find('pre').exists()).toBe(false); wrapper.unmount();
    setup('replay');session.state.replay={verdict:'最终指认已完成',full_story:'案件完整真相',timeline:{stage_1:'确认死亡时间'},role_arcs:{r1:'面对未解的关系'}};
    wrapper=mount(GameWorkbenchView,{props:{gameId:5},global:{stubs:{RoleAuditView:true}}});await flushPromises();
    expect(wrapper.text()).toContain('案件完整真相'); expect(wrapper.text()).toContain('确认死亡时间'); expect(wrapper.text()).toContain('面对未解的关系');
    expect(wrapper.find('pre').exists()).toBe(false);wrapper.unmount();
  });

  it('restores keyboard focus to the replay action after closing the audit dialog',async()=>{
    setup('replay');session.state.replay={full_story:'案件完整真相',timeline:{},role_arcs:{}};
    const wrapper=mount(GameWorkbenchView,{props:{gameId:5},attachTo:document.body,global:{stubs:{RoleAuditView:true}}});
    const action=wrapper.findAll('button').find(button=>button.text()==='全部角色与 DM 记录')!;
    await action.trigger('click');
    wrapper.findComponent({name:'RoleAuditView'}).vm.$emit('close');await flushPromises();
    expect(document.activeElement).toBe(action.element);wrapper.unmount();
  });

  it('keeps a rewritten private clue bound to the original recipient',async()=>{
    vi.spyOn(HTMLDialogElement.prototype,'showModal').mockImplementation(function(this:HTMLDialogElement){this.open=true;});
    vi.spyOn(HTMLDialogElement.prototype,'close').mockImplementation(function(this:HTMLDialogElement){this.open=false;});
    setup('investigation');session.state.clues=[{clue_id:'c1',target_name:'药柜',truth_content:'原始线索'}];session.state.channel='private';session.state.whisper={active_target_role_id:'r2'};
    const wrapper=mount(GameWorkbenchView,{props:{gameId:3}});
    await wrapper.findAll('button').find(button=>button.text()==='改写后分享')!.trigger('click');await flushPromises();
    await wrapper.get('.clue-share-dialog textarea').setValue('要分享的说法');
    const state=reactive(session.state);state.channel='public';state.whisper.active_target_role_id=null;await flushPromises();
    await wrapper.get('.clue-share-dialog form').trigger('submit');expect(session.command).not.toHaveBeenCalled();
    state.whisper.active_target_role_id='r2';await flushPromises();
    await wrapper.get('.clue-share-dialog form').trigger('submit');
    expect(session.command).toHaveBeenCalledWith('share_clue',{clue_id:'c1',mode:'distorted',content:'要分享的说法',scope:'private',target_role_id:'r2'});
    expect(state.clues[0].truth_content).toBe('原始线索');wrapper.unmount();vi.restoreAllMocks();
  });
});
