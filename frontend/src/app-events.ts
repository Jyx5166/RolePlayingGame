export interface FrontendEventMap {
  "auth:authenticated": { user: { id: number; username: string } };
  "auth:logout": { preserveReturnPath: boolean; broadcast: boolean };
  "navigation:view": { view: "create" | "records" | "library" | "profile" };
  "games:prepare": { gameId: number };
  "games:activated": { gameId: number };
  "sidebar:set": { collapsed: boolean; focusTarget: boolean };
  "records:open": { gameId: number };
  "records:deleted": { gameId: number; title: string };
  "records:invalidate": Record<string, never>;
  "toast:show": { message: string };
}

type FrontendEventName = keyof FrontendEventMap;
type EventHandler<K extends FrontendEventName> = (payload: FrontendEventMap[K]) => void;

class FrontendEventBus {
  private handlers = new Map<FrontendEventName, Set<(payload: never) => void>>();

  emit<K extends FrontendEventName>(name: K, payload: FrontendEventMap[K]): void {
    for (const handler of this.handlers.get(name) || []) {
      handler(payload as never);
    }
  }

  on<K extends FrontendEventName>(name: K, handler: EventHandler<K>): () => void {
    const handlers = this.handlers.get(name) || new Set<(payload: never) => void>();
    handlers.add(handler as (payload: never) => void);
    this.handlers.set(name, handlers);
    return () => handlers.delete(handler as (payload: never) => void);
  }
}

export const appEvents = new FrontendEventBus();
