type Envelope = Record<string, unknown>;
export interface CommandContext {
  gameId: number;
  stage: number;
  phase: string;
}

export class CommandOutbox {
  private readonly pending = new Map<string, { envelope: Envelope; context: CommandContext }>();

  retain(envelope: Envelope, context: CommandContext): void {
    if (this.pending.size >= 32) throw new Error("待确认操作过多，请等待服务端确认");
    this.pending.set(String(envelope.request_id), { envelope, context: { ...context } });
  }

  acknowledge(raw: unknown): void {
    if (!raw || typeof raw !== "object") return;
    const message = raw as Envelope;
    if (message.kind === "resume") {
      const events = (message.payload as { events?: unknown[] } | undefined)?.events;
      if (Array.isArray(events)) events.forEach(event => this.acknowledge(event));
    }
    if (message.kind !== "event" && message.kind !== "error") return;
    const record = this.pending.get(String(message.request_id));
    if (record && message.game_id === record.context.gameId) {
      this.pending.delete(String(message.request_id));
    }
  }

  reconcile(context: CommandContext): { commands: Envelope[]; expiredCount: number } {
    const commands: Envelope[] = [];
    let expiredCount = 0;
    for (const [requestId, record] of this.pending) {
      if (record.context.gameId !== context.gameId) continue;
      if (record.context.stage !== context.stage || record.context.phase !== context.phase) {
        this.pending.delete(requestId);
        expiredCount += 1;
      } else {
        commands.push(record.envelope);
      }
    }
    return { commands, expiredCount };
  }

  clear(): void {
    this.pending.clear();
  }
}
