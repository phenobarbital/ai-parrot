// FEAT-598 (TASK-3794): 30 s clamp, manual inert, pause while hidden, immediate run on resume (AC10).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RefreshScheduler } from './scheduler';

function setHidden(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { configurable: true, value: hidden });
}

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
});
afterEach(() => {
  vi.useRealTimers();
  setHidden(false);
});

describe('RefreshScheduler', () => {
  it('clamps interval_seconds below 30 to 30 s', () => {
    const s = new RefreshScheduler({ policy: 'interval', interval_seconds: 5 } as never, async () => {});
    expect(s.intervalMs).toBe(30_000);
  });

  it('manual policy never auto-runs', async () => {
    const run = vi.fn(async () => {});
    const s = new RefreshScheduler({ policy: 'manual' } as never, run);
    s.start();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(run).not.toHaveBeenCalled();
    s.stop();
  });

  it('on_mount runs exactly once and never schedules a periodic timer', async () => {
    const run = vi.fn(async () => {});
    const s = new RefreshScheduler({ policy: 'on_mount' } as never, run);
    s.start();
    await Promise.resolve();
    expect(run).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(run).toHaveBeenCalledTimes(1);
    s.stop();
  });

  it('interval runs immediately then every clamped interval', async () => {
    const run = vi.fn(async () => {});
    const s = new RefreshScheduler({ policy: 'interval', interval_seconds: 30 } as never, run);
    s.start();
    await Promise.resolve();
    expect(run).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(run).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(run).toHaveBeenCalledTimes(3);
    s.stop();
  });

  it('pauses while hidden and runs immediately on resume', async () => {
    const run = vi.fn(async () => {});
    const s = new RefreshScheduler({ policy: 'interval', interval_seconds: 30 } as never, run);
    s.start();
    await Promise.resolve();
    expect(run).toHaveBeenCalledTimes(1);

    setHidden(true);
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
    run.mockClear();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(run).not.toHaveBeenCalled();

    setHidden(false);
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
    expect(run).toHaveBeenCalledTimes(1);

    run.mockClear();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(run).toHaveBeenCalledTimes(1);
    s.stop();
  });

  it('stop() clears the timer and removes the visibility listener', async () => {
    const run = vi.fn(async () => {});
    const s = new RefreshScheduler({ policy: 'interval', interval_seconds: 30 } as never, run);
    s.start();
    await Promise.resolve();
    run.mockClear();
    s.stop();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(run).not.toHaveBeenCalled();
    // A visibility change after stop() must not resurrect the schedule.
    setHidden(true);
    document.dispatchEvent(new Event('visibilitychange'));
    setHidden(false);
    document.dispatchEvent(new Event('visibilitychange'));
    await Promise.resolve();
    expect(run).not.toHaveBeenCalled();
  });
});
