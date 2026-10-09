export const WS_PROTOCOL_VERSION = "1.0" as const;

type JsonRecord = Record<string, unknown>;

export interface RealtimeReduction {
  lastEventId: number;
  snapshotGame: JsonRecord | null;
  messages: JsonRecord[];
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function eventIdOf(message: JsonRecord): number {
  const value = Number(message.event_id || 0);
  return Number.isSafeInteger(value) && value > 0 ? value : 0;
}

export function createRequestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

export function buildCommandEnvelope(
  gameId: number,
  command: JsonRecord,
  requestId = createRequestId(),
): JsonRecord {
  const { type, ...payload } = command;
  if (!Number.isSafeInteger(gameId) || gameId <= 0) {
    throw new Error("game_id 必须是正整数");
  }
  if (typeof type !== "string" || !type) {
    throw new Error("实时命令缺少 type");
  }
  return {
    protocol_version: WS_PROTOCOL_VERSION,
    kind: "command",
    type,
    request_id: requestId,
    game_id: gameId,
    payload,
  };
}

export function reduceRealtimeEnvelope(
  rawMessage: unknown,
  currentEventId: number,
): RealtimeReduction {
  if (!isRecord(rawMessage)) throw new Error("实时消息必须是对象");
  if (rawMessage.protocol_version !== WS_PROTOCOL_VERSION) {
    return {
      lastEventId: currentEventId,
      snapshotGame: null,
      messages: [rawMessage],
    };
  }
  const kind = rawMessage.kind;
  const nextEventId = Math.max(currentEventId, eventIdOf(rawMessage));
  if (kind === "snapshot") {
    if (!isRecord(rawMessage.payload) || !isRecord(rawMessage.payload.game)) {
      throw new Error("实时快照缺少 game");
    }
    const phaseMessages = rawMessage.payload.phase_messages;
    if (!Array.isArray(phaseMessages) || !phaseMessages.every(isRecord)) {
      throw new Error("实时快照 phase_messages 无效");
    }
    return {
      lastEventId: nextEventId,
      snapshotGame: rawMessage.payload.game,
      messages: phaseMessages,
    };
  }
  if (kind === "resume") {
    if (!isRecord(rawMessage.payload) || !Array.isArray(rawMessage.payload.events)) {
      throw new Error("实时续传 events 无效");
    }
    let cursor = currentEventId;
    const messages: JsonRecord[] = [];
    for (const event of rawMessage.payload.events) {
      const reduction = reduceRealtimeEnvelope(event, cursor);
      cursor = reduction.lastEventId;
      messages.push(...reduction.messages);
    }
    return {
      lastEventId: Math.max(cursor, nextEventId),
      snapshotGame: null,
      messages,
    };
  }
  if (kind !== "event" && kind !== "error") {
    throw new Error("不支持的实时消息类型");
  }
  const eventId = eventIdOf(rawMessage);
  if (eventId && eventId <= currentEventId) {
    return { lastEventId: currentEventId, snapshotGame: null, messages: [] };
  }
  if (!isRecord(rawMessage.payload)) throw new Error("实时事件 payload 无效");
  const payloadType = typeof rawMessage.payload.type === "string"
    ? rawMessage.payload.type
    : rawMessage.type;
  if (typeof payloadType !== "string" || !payloadType) {
    throw new Error("实时事件缺少 type");
  }
  return {
    lastEventId: nextEventId,
    snapshotGame: null,
    messages: [{ ...rawMessage.payload, type: payloadType }],
  };
}
