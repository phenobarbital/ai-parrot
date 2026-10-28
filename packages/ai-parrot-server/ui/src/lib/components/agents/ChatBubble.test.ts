// ai-parrot (FEAT-476 TASK-2594): ChatBubble.svelte tests — markdown
// sanitization, sources disclosure, error+retry, and the "Helpful" quick
// rating popup (the observable slice of "feedback callbacks": the ported
// `onFeedback` prop / `handleFeedback()` is unreferenced dead code in the
// navigator source — verbatim per the copy-in doctrine — so there is no
// call site to assert against; see this task's Completion Note).
import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { features } = vi.hoisted(() => ({
  features: {
    voice: true,
    avatar: true,
    maps: true,
    charts: true,
    canvas: true,
    infographic: true,
    datasets: true,
    richEditor: true,
    a2ui: true,
  },
}));
vi.mock("$lib/features", () => ({ features }));

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
import type { A2UIEnvelope } from "$lib/components/agents/canvas/a2ui/a2ui-types";

const inlineEnvelope: A2UIEnvelope = {
  version: "v1.0",
  createSurface: {
    surfaceId: "inline-kpi",
    components: [
      {
        id: "root",
        component: "KPICard",
        label: "Worked hours",
        value: "42h",
      },
    ],
    metadata: {
      extensions: {
        parrot_presentation: {
          kind: "widget",
          inline: true,
          origin: "chat_turn",
          component: "KPICard",
        },
      },
    },
  },
};

const dashboardEnvelope: A2UIEnvelope = {
  ...inlineEnvelope,
  createSurface: {
    ...inlineEnvelope.createSurface,
    surfaceId: "dashboard-kpi",
    metadata: undefined,
  },
};

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
  beforeEach(() => {
    features.a2ui = true;
    features.charts = true;
  });

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

  it("mounts an inline A2UI surface when the feature is enabled", async () => {
    render(ChatBubble, {
      message: makeMessage({
        output_mode: "a2ui",
        a2ui_envelope: inlineEnvelope,
      }),
    });

    expect(await screen.findByText("Worked hours")).toBeInTheDocument();
    expect(screen.getByText("42h")).toBeInTheDocument();
  });

  it("leaves the bubble unchanged when the A2UI feature is disabled", () => {
    features.a2ui = false;
    const { container } = render(ChatBubble, {
      message: makeMessage({
        output_mode: "a2ui",
        a2ui_envelope: inlineEnvelope,
      }),
    });

    expect(container.querySelector("strong")?.textContent).toBe("world");
    expect(container.textContent).not.toContain("Worked hours");
  });

  it("does not mount a marker-less A2UI dashboard envelope", () => {
    const { container } = render(ChatBubble, {
      message: makeMessage({
        output_mode: "a2ui",
        a2ui_envelope: dashboardEnvelope,
      }),
    });

    expect(container.querySelector("strong")?.textContent).toBe("world");
    expect(container.textContent).not.toContain("Worked hours");
  });

  it("keeps structured-chart rendering unchanged", () => {
    features.charts = false;
    render(ChatBubble, {
      message: makeMessage({
        output_mode: "structured_chart",
        output: { type: "bar", title: "Existing chart", x: "month", y: ["value"] },
      }),
    });

    expect(screen.getByText("Existing chart")).toBeInTheDocument();
    expect(screen.getByText("Loading chart…")).toBeInTheDocument();
  });
});

describe("ChatBubble — suggestion chips", () => {
  const suggestions = [
    {
      label: "View as table",
      prompt: "Show the previous answer as a table",
      output_mode: "structured_table",
      kind: "presentation",
      source: "provider",
      action: null,
    },
    {
      label: "Explain this",
      prompt: "Explain this answer",
      output_mode: null,
      kind: "action",
      source: "provider",
      action: "explain",
    },
  ] as any;

  it("renders chips under an assistant message and reports the click with its message", async () => {
    const onSuggestion = vi.fn();
    const message = makeMessage({ suggestions });
    render(ChatBubble, { message, onSuggestion });

    const chips = screen.getAllByTestId("suggestion-chip");
    expect(chips).toHaveLength(2);
    await fireEvent.click(chips[0]);
    expect(onSuggestion).toHaveBeenCalledTimes(1);
    expect(onSuggestion).toHaveBeenCalledWith(message, suggestions[0]);
  });

  it("renders no chips while the answer is still streaming", () => {
    render(ChatBubble, {
      message: makeMessage({ suggestions }),
      onSuggestion: vi.fn(),
      isStreaming: true,
    });
    expect(screen.queryByTestId("suggestion-chips")).toBeNull();
  });

  it("renders no chips on a user message", () => {
    render(ChatBubble, {
      message: makeMessage({ role: "user", suggestions }),
      onSuggestion: vi.fn(),
    });
    expect(screen.queryByTestId("suggestion-chips")).toBeNull();
  });

  it("renders no chips without a handler or without suggestions", () => {
    render(ChatBubble, { message: makeMessage({ suggestions }) });
    expect(screen.queryByTestId("suggestion-chips")).toBeNull();
  });

  it("renders no chips for an empty list", () => {
    render(ChatBubble, { message: makeMessage({ suggestions: [] }), onSuggestion: vi.fn() });
    expect(screen.queryByTestId("suggestion-chips")).toBeNull();
  });
});
