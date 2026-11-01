/** Single owner of the user's connections list + SSE reader (FEAT-777 M5). */
import { listConnections, openConnectionEvents } from "$lib/api/connections";
import type { ConnectionEvent } from "$lib/types/generated/ConnectionEvent";
import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";

const BACKOFF_MIN_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

export class ConnectionsStore {
  items = $state<IntegrationDescriptor[]>([]);
  loading = $state(false);
  live = $state(false);
  error = $state<string | null>(null);

  #abort: AbortController | null = null;
  #listeners = new Set<(e: ConnectionEvent) => void>();

  async refresh(): Promise<void> {
    this.loading = true;
    try {
      this.items = await listConnections();
      this.error = null;
    } catch (err) {
      this.error = err instanceof Error ? err.message : "Failed to load connections";
    } finally {
      this.loading = false;
    }
  }

  /** Idempotent: opens the SSE reader once; refresh() on open and on each event. */
  start(): void {
    if (this.#abort) return;
    this.#abort = new AbortController();
    void this.#run(this.#abort.signal);
  }

  stop(): void {
    this.#abort?.abort();
    this.#abort = null;
    this.live = false;
  }

  onEvent(cb: (e: ConnectionEvent) => void): () => void {
    this.#listeners.add(cb);
    return () => this.#listeners.delete(cb);
  }

  async #run(signal: AbortSignal): Promise<void> {
    let delay = BACKOFF_MIN_MS;
    while (!signal.aborted) {
      this.live = true;
      void this.refresh();
      try {
        await openConnectionEvents((event) => {
          void this.refresh();
          for (const listener of this.#listeners) {
            try {
              listener(event);
            } catch {
              // A consumer must not terminate the shared stream.
            }
          }
        }, signal);
        delay = BACKOFF_MIN_MS;
      } catch (err) {
        if (signal.aborted || (err instanceof Error && err.name === "AbortError")) break;
      }

      if (signal.aborted) break;
      this.live = false;
      await this.#sleep(delay, signal);
      delay = Math.min(delay * 2, BACKOFF_MAX_MS);
    }
    if (signal.aborted) this.live = false;
  }

  async #sleep(milliseconds: number, signal: AbortSignal): Promise<void> {
    await new Promise<void>((resolve) => {
      if (signal.aborted) {
        resolve();
        return;
      }
      const timer = setTimeout(() => {
        signal.removeEventListener("abort", onAbort);
        resolve();
      }, milliseconds);
      const onAbort = () => {
        clearTimeout(timer);
        signal.removeEventListener("abort", onAbort);
        resolve();
      };
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }
}

export const connectionsStore = new ConnectionsStore();
