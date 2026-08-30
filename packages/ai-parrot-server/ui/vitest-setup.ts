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
