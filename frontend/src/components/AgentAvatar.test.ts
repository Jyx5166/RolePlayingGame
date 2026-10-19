// @vitest-environment happy-dom
import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentAvatar from './AgentAvatar.vue';
afterEach(()=>vi.useRealTimers());
describe('Agent presence feedback',()=>{
  it('uses the role portrait, falls back after an image error, and refreshes it when the role changes',async()=>{
    const wrapper=mount(AgentAvatar,{props:{name:'沈知微',online:true,portrait:'/portraits/shen.png',human:true}});
    expect(wrapper.get('img').attributes('src')).toBe('/portraits/shen.png');
    expect(wrapper.get('img').attributes('alt')).toBe('沈知微的角色肖像');
    expect(wrapper.attributes('aria-label')).toBe('沈知微 · 在线');
    expect(wrapper.find('.agent-avatar-initial').exists()).toBe(false);
    await wrapper.get('img').trigger('error');
    expect(wrapper.find('img').exists()).toBe(false);expect(wrapper.get('.agent-avatar-initial').text()).toBe('沈');
    await wrapper.setProps({name:'顾临川',portrait:'/portraits/gu.png',human:false});
    expect(wrapper.get('img').attributes('src')).toBe('/portraits/gu.png');
    expect(wrapper.get('img').attributes('alt')).toBe('顾临川的角色肖像');
    expect(wrapper.classes()).toContain('has-portrait');wrapper.unmount();
  });
  it('keeps presence effects visible alongside portraits and leaves the DM marker intact',async()=>{
    vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-13T12:00:00Z'));
    const wrapper=mount(AgentAvatar,{props:{name:'周既明',portrait:'/portraits/zhou.png',online:true,activity:{activity:'thinking',at:Date.now()}}});
    expect(wrapper.classes()).toContain('activity-thinking');expect(wrapper.find('img').exists()).toBe(true);
    await wrapper.setProps({activity:{activity:'idle',at:Date.now(),speechAt:Date.now()}});
    expect(wrapper.classes()).toContain('activity-speaking');expect(wrapper.find('.agent-avatar-ripple').exists()).toBe(true);
    await wrapper.setProps({activity:{activity:'searching',at:Date.now(),searchAt:Date.now()}});
    expect(wrapper.classes()).toContain('activity-searching');expect(wrapper.find('.agent-avatar-search').exists()).toBe(true);
    await vi.advanceTimersByTimeAsync(2700);expect(wrapper.classes()).toContain('activity-idle');
    await wrapper.setProps({name:'DM',portrait:undefined,activity:undefined});
    expect(wrapper.find('img').exists()).toBe(false);expect(wrapper.get('.agent-avatar-initial').text()).toBe('DM');wrapper.unmount();
  });
  it('shows actual thinking and keeps a short speech pulse before returning online',async()=>{
    vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-13T12:00:00Z'));
    const wrapper=mount(AgentAvatar,{props:{name:'周既明',online:true,activity:{activity:'thinking',at:Date.now()}}});
    expect(wrapper.attributes('aria-label')).toContain('正在思考');
    await wrapper.setProps({activity:{activity:'thinking',at:Date.now(),speechAt:Date.now()}});
    expect(wrapper.classes()).toContain('activity-speaking');
    await wrapper.setProps({activity:{activity:'idle',at:Date.now(),speechAt:Date.now()}});
    expect(wrapper.classes()).toContain('activity-speaking');
    await vi.advanceTimersByTimeAsync(2700);expect(wrapper.classes()).toContain('activity-idle');
    await wrapper.setProps({activity:{activity:'idle',at:Date.now(),speechAt:Date.now()-100,searchAt:Date.now()}});
    expect(wrapper.find('.agent-avatar-search').exists()).toBe(true);
    await wrapper.setProps({online:false});expect(wrapper.classes()).toContain('activity-offline');expect(wrapper.find('.agent-avatar-search').exists()).toBe(false);
    wrapper.unmount();
  });
});
