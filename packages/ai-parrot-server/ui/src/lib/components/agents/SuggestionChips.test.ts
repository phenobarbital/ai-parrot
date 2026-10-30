import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import SuggestionChips from "./SuggestionChips.svelte";
import type { AgentChatSuggestion } from "$lib/types/generated/AgentChatResponse";

const chips: AgentChatSuggestion[] = [
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
];

describe("SuggestionChips", () => {
  it("renders one button per chip", () => {
    render(SuggestionChips, { props: { suggestions: chips, onSelect: vi.fn() } });
    expect(screen.getAllByTestId("suggestion-chip")).toHaveLength(2);
  });

  it("calls onSelect with the clicked chip", async () => {
    const onSelect = vi.fn();
    render(SuggestionChips, { props: { suggestions: chips, onSelect } });
    await fireEvent.click(screen.getAllByTestId("suggestion-chip")[1]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(chips[1]);
  });

  it("renders nothing for an empty list", () => {
    render(SuggestionChips, { props: { suggestions: [], onSelect: vi.fn() } });
    expect(screen.queryByTestId("suggestion-chips")).toBeNull();
    expect(screen.queryAllByTestId("suggestion-chip")).toHaveLength(0);
  });

  it("exposes the chip kind and prompt for styling and hover", () => {
    render(SuggestionChips, { props: { suggestions: chips, onSelect: vi.fn() } });
    const [table, explain] = screen.getAllByTestId("suggestion-chip");
    expect(table.getAttribute("data-kind")).toBe("presentation");
    expect(explain.getAttribute("data-kind")).toBe("action");
    expect(table.getAttribute("title")).toBe("Show the previous answer as a table");
  });

  it("disables every chip and ignores clicks while disabled", async () => {
    const onSelect = vi.fn();
    render(SuggestionChips, { props: { suggestions: chips, disabled: true, onSelect } });
    const buttons = screen.getAllByTestId("suggestion-chip") as HTMLButtonElement[];
    expect(buttons.every((b) => b.disabled)).toBe(true);
    // HTMLElement.click() honours `disabled` like a real user click; fireEvent dispatches the event regardless.
    buttons[0].click();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
