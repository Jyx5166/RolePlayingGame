import { describe, expect, it } from "vitest";

import { buildCommandEnvelope, reduceRealtimeEnvelope } from "./ws-protocol";

describe("WebSocket protocol", () => {
  it('preserves request correlation for optimistic chat and live activity',()=>{
    const result=reduceRealtimeEnvelope({protocol_version:'1.0',kind:'event',event_id:null,request_id:'request-1',type:'agent_activity',payload:{actor_role_id:'role',activity:'searching'}},21);
    expect(result.lastEventId).toBe(21);expect(result.messages[0]).toMatchObject({request_id:'request-1',actor_role_id:'role',activity:'searching'});
  });
  it("builds versioned command envelopes", () => {
    expect(buildCommandEnvelope(3, {
      type: "player_speech",
      content: "检查时间线",
    }, "request-123")).toEqual({
      protocol_version: "1.0",
      kind: "command",
      type: "player_speech",
      request_id: "request-123",
      game_id: 3,
      payload: { content: "检查时间线" },
    });
  });

  it("unwraps snapshots without mixing rendering effects", () => {
    const result = reduceRealtimeEnvelope({
      protocol_version: "1.0",
      kind: "snapshot",
      event_id: 8,
      payload: {
        game: { type: "game_init", game_id: 3 },
        phase_messages: [{ type: "phase_changed" }],
      },
    }, 0);
    expect(result.lastEventId).toBe(8);
    expect(result.snapshotGame).toEqual({ type: "game_init", game_id: 3 });
    expect(result.messages).toEqual([{ type: "phase_changed" }]);
  });

  it("deduplicates events and resumes only missing messages", () => {
    const result = reduceRealtimeEnvelope({
      protocol_version: "1.0",
      kind: "resume",
      event_id: 11,
      payload: {
        events: [
          {
            protocol_version: "1.0",
            kind: "event",
            event_id: 10,
            type: "player_echo",
            payload: { type: "player_echo", content: "已存在" },
          },
          {
            protocol_version: "1.0",
            kind: "event",
            event_id: 11,
            type: "ai_message",
            payload: { type: "ai_message", content: "新增" },
          },
        ],
      },
    }, 10);
    expect(result.lastEventId).toBe(11);
    expect(result.messages).toEqual([{ type: "ai_message", content: "新增" }]);
  });

  it("rejects malformed v1 payloads", () => {
    expect(() => reduceRealtimeEnvelope({
      protocol_version: "1.0",
      kind: "event",
      event_id: 1,
      payload: "invalid",
    }, 0)).toThrow("payload 无效");
  });

  it("does not advance the persisted cursor for heartbeat messages", () => {
    const result = reduceRealtimeEnvelope({
      protocol_version: "1.0", kind: "event", type: "heartbeat",
      event_id: null, payload: { type: "heartbeat" },
    }, 21);
    expect(result.lastEventId).toBe(21);
    expect(result.snapshotGame).toBeNull();
    expect(result.messages).toEqual([{ type: "heartbeat" }]);
  });

  it("applies every resume page before a newer live event", () => {
    let cursor = 1;
    const delivered: number[] = [];
    for (let start = 2; start <= 1001; start += 200) {
      const events = Array.from({ length: Math.min(200, 1002 - start) }, (_, index) => ({
        protocol_version: "1.0", kind: "event", event_id: start + index,
        type: "audit_event", payload: { type: "audit_event", index: start + index },
      }));
      const result = reduceRealtimeEnvelope({
        protocol_version: "1.0", kind: "resume", event_id: events[events.length - 1].event_id,
        payload: { events },
      }, cursor);
      cursor = result.lastEventId;
      delivered.push(...result.messages.map(message => Number(message.index)));
    }
    expect(delivered).toEqual(Array.from({ length: 1000 }, (_, index) => index + 2));
    expect(cursor).toBe(1001);
    const live = reduceRealtimeEnvelope({ protocol_version: "1.0", kind: "event", event_id: 1002,
      type: "hint", payload: { type: "hint" } }, cursor);
    expect(live.messages).toHaveLength(1);
    expect(live.lastEventId).toBe(1002);
  });
});
