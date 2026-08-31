import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import StringListEditor from "./StringListEditor.svelte";

function itemTexts(container: HTMLElement): string[] {
  return Array.from(
    container.querySelectorAll('[data-testid="string-list-editor-items"] li span'),
  ).map((el) => el.textContent ?? "");
}

describe("StringListEditor", () => {
  it("adds an item via the Add button", async () => {
    const { getByTestId, container } = render(StringListEditor, { items: [] });
    const input = getByTestId("string-list-editor-input") as HTMLInputElement;
    const addButton = getByTestId("string-list-editor-add");

    await fireEvent.input(input, { target: { value: "search_web" } });
    await fireEvent.click(addButton);

    expect(itemTexts(container)).toEqual(["search_web"]);
    expect(input.value).toBe("");
  });

  it("adds an item via Enter", async () => {
    const { getByTestId, container } = render(StringListEditor, { items: [] });
    const input = getByTestId("string-list-editor-input") as HTMLInputElement;

    await fireEvent.input(input, { target: { value: "search_web" } });
    await fireEvent.keyDown(input, { key: "Enter" });

    expect(itemTexts(container)).toEqual(["search_web"]);
  });

  it("trims and drops blank entries", async () => {
    const { getByTestId, container } = render(StringListEditor, { items: [] });
    const input = getByTestId("string-list-editor-input") as HTMLInputElement;
    const addButton = getByTestId("string-list-editor-add");

    await fireEvent.input(input, { target: { value: "   " } });
    await fireEvent.click(addButton);
    expect(itemTexts(container)).toEqual([]);

    await fireEvent.input(input, { target: { value: "  trimmed  " } });
    await fireEvent.click(addButton);
    expect(itemTexts(container)).toEqual(["trimmed"]);
  });

  it("removes an item", async () => {
    const { getByTestId, container } = render(StringListEditor, {
      items: ["a", "b", "c"],
    });

    await fireEvent.click(getByTestId("string-list-editor-remove-1"));

    expect(itemTexts(container)).toEqual(["a", "c"]);
  });

  it("reorders items with move up/down", async () => {
    const { getByTestId, container } = render(StringListEditor, {
      items: ["a", "b", "c"],
    });

    await fireEvent.click(getByTestId("string-list-editor-down-0"));
    expect(itemTexts(container)).toEqual(["b", "a", "c"]);

    await fireEvent.click(getByTestId("string-list-editor-up-2"));
    expect(itemTexts(container)).toEqual(["b", "c", "a"]);
  });

  it("renders suggestions in a datalist", () => {
    const { getByTestId } = render(StringListEditor, {
      items: [],
      suggestions: ["search_web", "calculator"],
      id: "tools",
    });

    const datalist = getByTestId("string-list-editor-suggestions");
    expect(datalist.querySelectorAll("option")).toHaveLength(2);
  });

  it("does not render a datalist when there are no suggestions", () => {
    const { queryByTestId } = render(StringListEditor, { items: [] });
    expect(queryByTestId("string-list-editor-suggestions")).toBeNull();
  });
});
