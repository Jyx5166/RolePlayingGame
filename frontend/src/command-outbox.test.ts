import { describe, expect, it } from "vitest";
import { CommandOutbox } from "./command-outbox";
import { buildCommandEnvelope } from "./ws-protocol";

const context = { gameId: 3, stage: 2, phase: "investigation" };

describe("command outbox", () => {
  it("retries the original envelope and request id", () => {
    const outbox = new CommandOutbox();
    const command = buildCommandEnvelope(3, { type: "search", target_id: "desk" }, "original-id");
    outbox.retain(command, context);
    expect(outbox.reconcile(context).commands).toEqual([command]);
    expect(outbox.reconcile(context).commands[0]).toBe(command);
  });

  it("acknowledges resume events and error results but not heartbeats", () => {
    const outbox = new CommandOutbox();
    outbox.retain(buildCommandEnvelope(3, { type: "search" }, "pending"), context);
    outbox.acknowledge({ kind: "event", game_id: 3, request_id: null, type: "heartbeat" });
    expect(outbox.reconcile(context).commands).toHaveLength(1);
    outbox.acknowledge({ kind: "resume", payload: { events: [{ kind: "error", game_id: 3, request_id: "pending" }] } });
    expect(outbox.reconcile(context).commands).toHaveLength(0);
  });

  it("never retries a command into another stage or phase", () => {
    const outbox = new CommandOutbox();
    outbox.retain(buildCommandEnvelope(3, { type: "search" }, "old"), context);
    expect(outbox.reconcile({ ...context, stage: 3 })).toEqual({ commands: [], expiredCount: 1 });
    outbox.retain(buildCommandEnvelope(3, { type: "search" }, "old-phase"), context);
    expect(outbox.reconcile({ ...context, phase: "dm_hosting" })).toEqual({ commands: [], expiredCount: 1 });
  });

  it("isolates games and clears pending operations on explicit exit", () => {
    const outbox = new CommandOutbox();
    outbox.retain(buildCommandEnvelope(3, { type: "search" }, "owned"), context);
    outbox.acknowledge({ kind: "event", game_id: 4, request_id: "owned" });
    expect(outbox.reconcile({ ...context, gameId: 4 }).commands).toHaveLength(0);
    expect(outbox.reconcile(context).commands).toHaveLength(1);
    outbox.clear();
    expect(outbox.reconcile(context).commands).toHaveLength(0);
  });
});
