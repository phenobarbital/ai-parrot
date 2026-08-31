// ai-parrot (FEAT-476 TASK-2594): ChatBubble.svelte tests — markdown
// sanitization, sources disclosure, error+retry, and the "Helpful" quick
// rating popup (the observable slice of "feedback callbacks": the ported
// `onFeedback` prop / `handleFeedback()` is unreferenced dead code in the
// navigator source — verbatim per the copy-in doctrine — so there is no
// call site to assert against; see this task's Completion Note).
import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

// These flagged-surface targets ship from TASK-2595/2596 and don't exist
// in this worktree yet; ChatBubble only reaches them via a runtime-gated
// `await import(...)` that no default-content test triggers, but Vite's
// import-analysis still needs the specifier to resolve at transform time
// — stub them per this task's Codebase Contract ("Does NOT Exist").
vi.mock("./DataMap.svelte", () => ({ default: {} }));
vi.mock("./StructuredMap.svelte", () => ({ default: {} }));
vi.mock("./VoiceNotePlayer.svelte", () => ({ default: {} }));
vi.mock("$lib/components/charts/AppChart.svelte", () => ({ default: {} }));
vi.mock("$lib/components/visualizations/ECharts.svelte", () => ({ default: {} }));

import ChatBubble from "./ChatBubble.svelte";
import type { AgentMessage } from "$lib/types/agent";

function makeMessage(overrides: Partial<AgentMessage> = {}): AgentMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "Hello **world**",
    timestamp: new Date(),
    metadata: {
      session_id: "s1",
      model: "gemini",
      provider: "google",
      turn_id: "t1",
      response_time: 1,
    } as AgentMessage["metadata"],
    ...overrides,
  };
}

describe("ChatBubble", () => {
  it("renders markdown and sanitizes raw script tags", async () => {
    const { container } = render(ChatBubble, {
      message: makeMessage({
        content: "Hi <script>window.__pwned = true;</script> **bold**",
      }),
    });
    // DOMPurify must have stripped the <script> element entirely.
    expect(container.querySelector("script")).toBeNull();
    // The safe markdown content still renders.
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });

  it("shows the sources disclosure panel when sources are present", async () => {
    const { container } = render(ChatBubble, {
      message: makeMessage({
        sources: [{ title: "Doc A", url: "https://example.com/a" } as any],
      }),
    });
    // Sources are collapsed behind a disclosure toggle (SourcesPanel.svelte).
    const toggle = container.querySelector("button.bg-blue-50");
    expect(toggle).not.toBeNull();
    await fireEvent.click(toggle!);
    expect(screen.getByText("Doc A")).toBeInTheDocument();
  });

  it("does not render the sources panel when there are no sources", () => {
    const { container } = render(ChatBubble, { message: makeMessage() });
    expect(container.querySelector("button.bg-blue-50")).toBeNull();
  });

  it("shows an error bubble with a working Retry action", async () => {
    let retriedId: string | undefined;
    render(ChatBubble, {
      message: makeMessage({
        content: "**Error:** Failed to get response from agent. \n\n`boom`",
        metadata: {
          session_id: "s1",
          model: "system",
          provider: "",
          turn_id: "",
          response_time: 0,
          is_error: true,
        } as AgentMessage["metadata"],
      }),
      onRetry: (id: string) => {
        retriedId = id;
      },
    });
    const retryButton = screen.getByTitle("Retry request");
    await fireEvent.click(retryButton);
    expect(retriedId).toBe("m1");
  });

  it("opens the quick-rating popup when Helpful is clicked", async () => {
    render(ChatBubble, {
      message: makeMessage(),
      sessionId: "s1",
      chatbotId: "bot-1",
    });
    await fireEvent.click(screen.getByTitle("Helpful"));
    expect(screen.getByText("What did you like?")).toBeInTheDocument();
  });
});
