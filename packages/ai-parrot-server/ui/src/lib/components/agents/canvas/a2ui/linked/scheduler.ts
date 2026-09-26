/** RefreshScheduler — on_mount | manual | interval (FEAT-598, AC10). */
import type { RefreshPolicy } from './types';

export const MIN_INTERVAL_SECONDS = 30;

export class RefreshScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly onVisibility = (): void => this.handleVisibility();

  constructor(private readonly policy: RefreshPolicy, private readonly run: () => Promise<void>) {}

  /** Clamp to >= 30 s (spec M1/M11). */
  get intervalMs(): number {
    return Math.max(MIN_INTERVAL_SECONDS, this.policy.interval_seconds ?? MIN_INTERVAL_SECONDS) * 1000;
  }

  start(): void {
    const mode = this.policy.policy ?? 'on_mount';
    if (mode === 'manual') return;
    if (mode === 'on_mount') {
      void this.run();
      return;
    }
    // interval: pause while hidden, immediate run + periodic timer while visible.
    document.addEventListener('visibilitychange', this.onVisibility);
    if (!document.hidden) {
      void this.run();
      this.timer = setInterval(() => void this.run(), this.intervalMs);
    }
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    document.removeEventListener('visibilitychange', this.onVisibility);
  }

  private handleVisibility(): void {
    if (document.hidden) {
      if (this.timer !== null) clearInterval(this.timer);
      this.timer = null;
    } else {
      void this.run();
      this.timer = setInterval(() => void this.run(), this.intervalMs);
    }
  }
}
