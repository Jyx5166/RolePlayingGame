// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GameWorkbenchView from './components/GameWorkbenchView.vue';

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('./runtime', () => ({ getApiClient: () => api }));

const openingTitle = '雾港往事';
const openingContent = '临潮公馆曾是雾港商界的会客厅。沈知微受邀回到旧宅，与故友顾临川重逢。';
const briefing = '第一幕：午夜的警铃响起，所有人开始核对各自的行踪。';
const assignment = { role_name: '沈知微', public_identity: '受邀归来的旧友', blocks: [{ block_id: 'private', content: '只有你知道的往事。' }], personal_task: '核对当晚的行踪' };
let socket: WaitingSocket;
let eventId = 0;
let wrapper: ReturnType<typeof mount> | undefined;
class WaitingSocket {
  static OPEN = 1;
  readyState = 1;
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onclose?: (event: { reason: string; code: number }) => void;
  send = vi.fn();
  close = vi.fn();
  constructor() { socket = this; }
}

function phaseSummary(stage: number, phase: string, hasOpening = true) {
  const beforeFirstStage = hasOpening && stage === 1 && ['opening', 'private_reveal'].includes(phase);
  return {
    phase, stage, has_opening: hasOpening, before_first_stage: beforeFirstStage, public_tasks: [],
    stage_title: phase === 'opening' ? openingTitle : beforeFirstStage ? '角色剧本' : `第 ${stage} 幕 · 暴雨封馆`,
    continue_label: phase === 'opening' ? '接收角色剧本' : beforeFirstStage ? '开始第一幕' : phase === 'briefing' ? hasOpening && stage === 1 ? '开始调查' : '接收角色剧本' : '开始调查',
  };
}

function setup({ stage = 1, phase = 'opening', hasOpening = true, preparationFails = false } = {}) {
  eventId = 0;
  vi.stubGlobal('WebSocket', WaitingSocket);
  api.request.mockReset();
  const summary = phaseSummary(stage, phase, hasOpening);
  api.request.mockImplementation(async (path: string) => {
    if (path.endsWith('/preparation')) {
      if (preparationFails) throw new Error('开幕读取失败');
      return { opening: hasOpening ? { title: openingTitle, content: openingContent } : null };
    }
    if (path.includes('/ws-ticket')) return { ticket: 'test-ticket' };
    if (path.endsWith('/notebook')) return { automatic: [], clues: [], manual_notes: '' };
    return { id: 38, lifecycle_version: 4, title: '钟楼夜宴', current_stage: stage, current_phase: phase, total_stages: 3,
      has_opening: summary.has_opening, before_first_stage: summary.before_first_stage };
  });
  wrapper = mount(GameWorkbenchView, { props: { gameId: 38 } });
  return wrapper;
}

function sendSnapshot(stage: number, phase: string, messages: Record<string, unknown>[] = [], hasOpening = true) {
  socket.onmessage?.({ data: JSON.stringify({
    protocol_version: '1.0', kind: 'snapshot', event_id: 0,
    payload: {
      game: { phase: phaseSummary(stage, phase, hasOpening), role_info: { role_id: 'player' }, public_roles: [] },
      phase_messages: messages,
    },
  }) });
}

function narration(content: string) {
  return [{ type: 'dm_narration_start' }, { type: 'dm_narration_chunk', content }, { type: 'dm_narration_end', can_continue: true }];
}

function sendEvent(payload: Record<string, unknown>) {
  socket.onmessage?.({ data: JSON.stringify({ protocol_version: '1.0', kind: 'event', event_id: ++eventId, payload }) });
}

function completeCommand() {
  const requestId = JSON.parse(socket.send.mock.calls.at(-1)![0]).request_id;
  sendEvent({ type: 'game_command_complete', request_id: requestId });
}

afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); });

describe('independent opening before the first act', () => {
  it('reads the prologue immediately while waiting for the first snapshot and prevents early commands', async () => {
    const view = setup();
    await flushPromises();
    socket.onopen?.();
    await flushPromises();
    expect(view.get('[aria-label="剧本开幕"]').text()).toBe(openingContent);
    expect(view.get('.modern-phase-heading h2').text()).toBe(openingTitle);
    expect(view.get('.stage-badge').text()).toBe('故事开幕');
    expect(view.get('.stage-badge').text()).not.toContain('1');
    expect(view.get('.modern-sequence').text()).toBe('开幕角色剧本第一幕自由调查DM 主持复盘');
    expect(view.get('.modern-sequence .active').text()).toBe('开幕');
    expect(view.text()).not.toContain(briefing);
    expect(view.get('.phase-continue').attributes('disabled')).toBeDefined();
    await view.get('.phase-continue').trigger('click');
    expect(socket.send).not.toHaveBeenCalled();

    const scroll = view.get('.modern-phase-scroll').element as HTMLElement;
    scroll.scrollTop = 200;
    sendSnapshot(1, 'opening', narration(openingContent));
    await flushPromises();
    expect(view.get('[aria-label="剧本开幕"]').text()).toBe(openingContent);
    expect(view.get('.phase-continue').attributes('disabled')).toBeUndefined();
    expect(scroll.scrollTop).toBe(200);
    sendEvent({ type: 'phase_changed', phase: { ...phaseSummary(1, 'opening'), continue_label: '阅读角色剧本' } });
    await flushPromises();
    expect(view.get('.phase-continue').text()).toBe('阅读角色剧本');
    expect(scroll.scrollTop).toBe(200);
  });

  it('moves from the opening to the private script, then the first act and investigation', async () => {
    const view = setup();
    await flushPromises();
    socket.onopen?.();
    sendSnapshot(1, 'opening', narration(openingContent));
    await flushPromises();
    await view.get('.phase-continue').trigger('click');
    expect(JSON.parse(socket.send.mock.calls[0]![0]).type).toBe('advance_phase');

    const scroll = view.get('.modern-phase-scroll').element as HTMLElement;
    scroll.scrollTop = 250;
    sendEvent({ type: 'phase_changed', phase: phaseSummary(1, 'private_reveal') });
    sendEvent({ type: 'private_script', assignment });
    completeCommand();
    await flushPromises();
    expect(scroll.scrollTop).toBe(0);
    expect(view.get('.modern-phase-heading h2').text()).toBe('角色剧本');
    expect(view.get('.stage-badge').text()).toBe('角色准备');
    expect(view.get('.private-role-card').text()).toContain('只有你知道的往事。');
    expect(view.text()).not.toContain(openingContent);
    expect(view.get('.phase-continue').text()).toBe('开始第一幕');
    expect(view.get('.modern-sequence .active').text()).toBe('角色剧本');
    await view.get('.phase-continue').trigger('click');

    scroll.scrollTop = 300;
    sendEvent({ type: 'phase_changed', phase: phaseSummary(1, 'briefing') });
    await flushPromises();
    expect(view.text()).not.toContain(openingContent);
    for (const message of narration(briefing)) sendEvent(message);
    completeCommand();
    await flushPromises();
    expect(scroll.scrollTop).toBe(0);
    expect(view.get('.stage-badge').text()).toBe('第 1 / 3 幕');
    expect(view.get('.modern-phase-heading .case-label').text()).toBe('本幕开场');
    expect(view.get('.phase-narration').text()).toBe(briefing);
    expect(view.get('.modern-sequence .active').text()).toBe('第一幕');
    expect(view.get('.phase-continue').text()).toBe('开始调查');
    expect(view.find('[aria-label="剧本开幕"]').exists()).toBe(false);
    await view.get('.phase-continue').trigger('click');

    sendEvent({ type: 'phase_changed', phase: phaseSummary(1, 'investigation') });
    sendEvent({ type: 'investigation_open', stage_info: [], clues: [], whisper_status: {}, search_status: {} });
    completeCommand();
    await flushPromises();
    expect(socket.send).toHaveBeenCalledTimes(3);
    expect(view.find('.modern-investigation').exists()).toBe(true);
    expect(view.get('.modern-sequence .active').text()).toBe('自由调查');
  });

  it.each(['opening', 'private_reveal', 'briefing', 'investigation'])('restores %s without substituting the first-act briefing for the opening', async phase => {
    const view = setup({ phase });
    await flushPromises();
    if (phase === 'private_reveal') expect(view.get('.stage-badge').text()).toBe('角色准备');
    socket.onopen?.();
    sendSnapshot(1, phase, phase === 'private_reveal' ? [{ type: 'private_script', assignment }] : phase === 'opening' ? narration(openingContent) : narration(briefing));
    await flushPromises();
    expect(view.get('.modern-sequence .active').text()).toBe(({ opening: '开幕', private_reveal: '角色剧本', briefing: '第一幕', investigation: '自由调查' } as Record<string, string>)[phase]);
    if (phase === 'opening') expect(view.get('[aria-label="剧本开幕"]').text()).toBe(openingContent);
    else {
      expect(view.text()).not.toContain(openingContent);
      expect(api.request.mock.calls.some(([path]) => path.endsWith('/preparation'))).toBe(false);
    }
  });

  it.each([{ stage: 1, hasOpening: false }, { stage: 2, hasOpening: true }])('preserves briefing → private script → investigation for stage $stage with has_opening=$hasOpening', async ({ stage, hasOpening }) => {
    const view = setup({ stage, phase: 'briefing', hasOpening });
    await flushPromises();
    socket.onopen?.();
    sendSnapshot(stage, 'briefing', narration(briefing), hasOpening);
    await flushPromises();
    expect(view.get('.modern-sequence').text()).toBe('开场角色剧本自由调查DM 主持复盘');
    expect(view.get('.modern-sequence .active').text()).toBe('开场');
    expect(view.get('.phase-continue').text()).toBe('接收角色剧本');
    expect(view.text()).not.toContain(openingContent);
    expect(api.request.mock.calls.some(([path]) => path.endsWith('/preparation'))).toBe(false);
    sendSnapshot(stage, 'private_reveal', [{ type: 'private_script', assignment }], hasOpening);
    await flushPromises();
    expect(view.get('.phase-continue').text()).toBe('开始调查');
    expect(view.get('.stage-badge').text()).toBe(`第 ${stage} / 3 幕`);
  });

  it('keeps connecting when preparation fails and restores the opening from the snapshot', async () => {
    const view = setup({ preparationFails: true });
    await flushPromises();
    expect(view.get('[role="alert"]').text()).toContain('开幕读取失败');
    socket.onopen?.();
    sendSnapshot(1, 'opening', narration(openingContent));
    await flushPromises();
    expect(view.get('[aria-label="剧本开幕"]').text()).toBe(openingContent);
    expect(api.request.mock.calls.some(([path]) => path.includes('/ws-ticket'))).toBe(true);
  });
});
