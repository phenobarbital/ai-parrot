import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listConnections: vi.fn(),
  openConnectionEvents: vi.fn(),
}));
vi.mock("$lib/api/connections", () => mocks);

describe("ConnectionsStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.listConnections.mockReset().mockResolvedValue([]);
    mocks.openConnectionEvents.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.resetModules();
  });

  it("refreshes on open and on every event", async () => {
    const event = { kind: "connection.completed" };
    mocks.openConnectionEvents.mockImplementationOnce(async (onEvent: (value: unknown) => void) => {
      onEvent(event);
    });
    const { ConnectionsStore } = await import("$lib/stores/connections.svelte");
    const store = new ConnectionsStore();
    const listener = vi.fn();
    store.onEvent(listener);

    store.start();
    // Flush microtasks only: the 1 s reconnect backoff must not elapse (it would add a third refresh).
    await vi.advanceTimersByTimeAsync(0);

    expect(mocks.listConnections).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenCalledWith(event);
    store.stop();
  });

  it("start() is idempotent", async () => {
    mocks.openConnectionEvents.mockImplementation(() => new Promise<void>(() => {}));
    const { ConnectionsStore } = await import("$lib/stores/connections.svelte");
    const store = new ConnectionsStore();

    store.start();
    store.start();
    await Promise.resolve();

    expect(mocks.openConnectionEvents).toHaveBeenCalledOnce();
    store.stop();
  });

  it("backs off 1s → 30s between reconnects", async () => {
    mocks.openConnectionEvents.mockRejectedValue(new Error("offline"));
    const { ConnectionsStore } = await import("$lib/stores/connections.svelte");
    const store = new ConnectionsStore();

    store.start();
    await Promise.resolve();
    expect(mocks.openConnectionEvents).toHaveBeenCalledOnce();

    for (const delay of [1_000, 2_000, 4_000, 8_000, 16_000, 30_000]) {
      await vi.advanceTimersByTimeAsync(delay);
      expect(mocks.openConnectionEvents).toHaveBeenCalledTimes(
        [1_000, 2_000, 4_000, 8_000, 16_000, 30_000].indexOf(delay) + 2,
      );
    }
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mocks.openConnectionEvents).toHaveBeenCalledTimes(8);
    store.stop();
  });

  it("stop() aborts the signal and stops reconnecting", async () => {
    let signal!: AbortSignal;
    mocks.openConnectionEvents.mockImplementation((_onEvent: unknown, receivedSignal: AbortSignal) => {
      signal = receivedSignal;
      return new Promise<void>(() => {});
    });
    const { ConnectionsStore } = await import("$lib/stores/connections.svelte");
    const store = new ConnectionsStore();

    store.start();
    await Promise.resolve();
    store.stop();
    await vi.advanceTimersByTimeAsync(60_000);

    expect(signal.aborted).toBe(true);
    expect(store.live).toBe(false);
    expect(mocks.openConnectionEvents).toHaveBeenCalledOnce();
  });
});
