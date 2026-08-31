import '@testing-library/jest-dom/vitest';

// jsdom has no ResizeObserver; bits-ui's Slider (vendored TASK-2585,
// FEAT-475) measures its track/thumb with one on mount. Any test that
// renders a Slider — directly or via a page/form that includes one, e.g.
// AgentForm's TabsAI/TabsCapabilities panels — needs this stub, so it
// lives in the shared setup rather than duplicated per test file.
class ResizeObserverStub implements ResizeObserver {
  constructor(_callback: ResizeObserverCallback) {}
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub;

// jsdom has no Web Animations API; Svelte's `slide`/`fade`/etc. transitions
// (e.g. QuickRating.svelte, vendored FEAT-476 TASK-2594) call
// `element.animate()` when they run. Stub it as a no-op Animation so any
// test that mounts a transitioning element doesn't crash — this doesn't
// need to actually animate, just not throw.
if (typeof Element !== "undefined" && !Element.prototype.animate) {
  Element.prototype.animate = function () {
    return {
      finished: Promise.resolve(),
      cancel() {},
      finish() {},
      play() {},
      pause() {},
      addEventListener() {},
      removeEventListener() {},
    } as unknown as Animation;
  };
}
