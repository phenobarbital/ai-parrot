// ai-parrot (FEAT-476 TASK-2594): ChatInput.svelte tests — onSend
// signature, Stop → onStopStream, and the mic button's visibility gate
// (AgentChat passes `enableVoiceInput={features.voice && ...}`, so
// `enableVoiceInput` is the flag-shaped prop this component-level test
// exercises directly).
import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatInput from "./ChatInput.svelte";

// jsdom doesn't implement the MediaRecorder / getUserMedia surface that
// `isVoiceRecordingSupported()` checks — stub it so `enableVoiceInput`
// alone (not environment support) is what's under test.
beforeEach(() => {
  vi.stubGlobal("MediaRecorder", class {} as unknown as typeof MediaRecorder);
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn() },
  });
});

describe("ChatInput", () => {
  it("offers an A2UI output mode and sends output_mode 'a2ui' (FEAT-611)", async () => {
    const onSend = vi.fn();
    const { container } = render(ChatInput, { onSend, isLoading: false });

    const option = container.querySelector('option[value="a2ui"]') as HTMLOptionElement | null;
    expect(option).not.toBeNull();
    expect(option?.textContent).toContain("A2UI");

    const select = option!.closest("select") as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "a2ui" } });
    await fireEvent.input(screen.getByRole("textbox"), { target: { value: "dashboard" } });
    await fireEvent.click(screen.getByTitle("Send message (Shift+Enter)"));

    expect(onSend).toHaveBeenCalledWith("dashboard", undefined, "a2ui", undefined, undefined);
  });

  it("calls onSend with (text, method, outputMode, llm, kwargs) on submit", async () => {
    const onSend = vi.fn();
    render(ChatInput, { onSend, isLoading: false });

    const textarea = screen.getByRole("textbox");
    await fireEvent.input(textarea, { target: { value: "hello agent" } });
    await fireEvent.click(screen.getByTitle("Send message (Shift+Enter)"));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith(
      "hello agent",
      undefined,
      undefined,
      undefined,
      undefined,
    );
  });

  it("Stop button calls onStopStream while streaming", async () => {
    const onStopStream = vi.fn();
    render(ChatInput, {
      onSend: vi.fn(),
      isLoading: true,
      isStreaming: true,
      onStopStream,
    });

    await fireEvent.click(screen.getByTitle("Stop streaming"));
    expect(onStopStream).toHaveBeenCalledTimes(1);
  });

  it("hides the mic button when enableVoiceInput is false", () => {
    render(ChatInput, {
      onSend: vi.fn(),
      isLoading: false,
      enableVoiceInput: false,
    });
    expect(screen.queryByLabelText("Record a voice note")).toBeNull();
  });

  it("shows the mic button when enableVoiceInput is true", () => {
    render(ChatInput, {
      onSend: vi.fn(),
      isLoading: false,
      enableVoiceInput: true,
    });
    expect(screen.getByLabelText("Record a voice note")).toBeInTheDocument();
  });
});
