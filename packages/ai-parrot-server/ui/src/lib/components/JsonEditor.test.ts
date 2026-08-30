import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import JsonEditor from "./JsonEditor.svelte";

describe("JsonEditor", () => {
  it("seeds the textarea with the pretty-printed initial value", () => {
    const { getByTestId } = render(JsonEditor, {
      value: { a: 1 },
      mode: "object",
    });
    const textarea = getByTestId("json-editor-textarea") as HTMLTextAreaElement;
    expect(textarea.value).toBe(JSON.stringify({ a: 1 }, null, 2));
  });

  it("shows an inline error and reports invalid for malformed JSON", async () => {
    const { getByTestId, queryByTestId } = render(JsonEditor, {
      value: {},
      mode: "object",
    });
    const textarea = getByTestId("json-editor-textarea") as HTMLTextAreaElement;

    await fireEvent.input(textarea, { target: { value: "{ not valid json" } });

    expect(queryByTestId("json-editor-error")).not.toBeNull();
    expect(textarea.getAttribute("aria-invalid")).toBe("true");
  });

  it("emits the parsed value only when valid", async () => {
    let lastValid: boolean | undefined;
    const { getByTestId } = render(JsonEditor, {
      value: { a: 1 },
      mode: "object",
      onvalid: (v: boolean) => {
        lastValid = v;
      },
    });
    const textarea = getByTestId("json-editor-textarea") as HTMLTextAreaElement;

    await fireEvent.input(textarea, { target: { value: '{"b": 2}' } });

    expect(lastValid).toBe(true);
  });

  it("Format button pretty-prints valid JSON", async () => {
    const { getByTestId } = render(JsonEditor, { value: {}, mode: "object" });
    const textarea = getByTestId("json-editor-textarea") as HTMLTextAreaElement;
    const formatButton = getByTestId("json-editor-format");

    await fireEvent.input(textarea, { target: { value: '{"a":1,"b":2}' } });
    await fireEvent.click(formatButton);

    expect(textarea.value).toBe(JSON.stringify({ a: 1, b: 2 }, null, 2));
  });

  it("object mode rejects a JSON array", async () => {
    const { getByTestId, queryByTestId } = render(JsonEditor, {
      value: {},
      mode: "object",
    });
    const textarea = getByTestId("json-editor-textarea") as HTMLTextAreaElement;

    await fireEvent.input(textarea, { target: { value: "[1, 2, 3]" } });

    expect(queryByTestId("json-editor-error")?.textContent).toContain("object");
  });

  it("array mode rejects a JSON object", async () => {
    const { getByTestId, queryByTestId } = render(JsonEditor, {
      value: [],
      mode: "array",
    });
    const textarea = getByTestId("json-editor-textarea") as HTMLTextAreaElement;

    await fireEvent.input(textarea, { target: { value: '{"a": 1}' } });

    expect(queryByTestId("json-editor-error")?.textContent).toContain("array");
  });

  it("any mode accepts both objects and arrays", async () => {
    const { getByTestId, queryByTestId } = render(JsonEditor, {
      value: {},
      mode: "any",
    });
    const textarea = getByTestId("json-editor-textarea") as HTMLTextAreaElement;

    await fireEvent.input(textarea, { target: { value: "[1, 2, 3]" } });
    expect(queryByTestId("json-editor-error")).toBeNull();

    await fireEvent.input(textarea, { target: { value: '{"a": 1}' } });
    expect(queryByTestId("json-editor-error")).toBeNull();
  });
});
