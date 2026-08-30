/**
 * No-op stub for navigator's `services/websocket-service.ts`.
 *
 * `ai-parrot-server` has no `/ws/userinfo` route (only `/ws/voice`,
 * lazily registered — `manager.py:1812-1834`), and this spec's Non-Goals
 * explicitly rule out implementing one (FEAT-476 spec §1, §2 "Overview" /
 * §6 "Does NOT Exist"). This module keeps navigator's `wsService` surface
 * (`WSMessage`, `subscribe`, `unsubscribe`, `onMessage`, `send`,
 * `disconnect`) so every vendored call site keeps compiling verbatim, but
 * never constructs a `WebSocket` and `ws_channel_id` is never sent by the
 * ported chat components.
 *
 * ai-parrot: navigator's `connect()`/reconnect machinery, `authStore`
 * token wiring and `handleMessage` dispatch are dropped — there is
 * nothing to connect to.
 */

export interface WSMessage {
  type: string;
  [key: string]: any;
}

type MessageHandler = (message: WSMessage) => void;

class WebSocketService {
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private loggedOnce = false;

  private logOnce(): void {
    if (this.loggedOnce) return;
    this.loggedOnce = true;
    // eslint-disable-next-line no-console
    console.debug("[wsService] stub — no WebSocket connection is opened");
  }

  subscribe(_channel: string): void {
    this.logOnce();
  }

  unsubscribe(_channel: string): void {
    this.logOnce();
  }

  onMessage(type: string, handler: MessageHandler): () => void {
    this.logOnce();
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)!.add(handler);

    return () => {
      const handlers = this.handlers.get(type);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.handlers.delete(type);
        }
      }
    };
  }

  send(_data: any): void {
    this.logOnce();
  }

  disconnect(): void {
    this.logOnce();
  }
}

export const wsService = new WebSocketService();
