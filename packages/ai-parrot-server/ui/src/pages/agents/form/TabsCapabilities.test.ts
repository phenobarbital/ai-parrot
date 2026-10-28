import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import { AgentFormState } from "$lib/stores/agent-form.svelte";
import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";

import TabsCapabilities from "./TabsCapabilities.svelte";

const catalog: AdminCatalog = {
  knowledge_bases: [],
  llm_providers: [],
  memory_types: ["memory"],
  operation_modes: ["conversational", "agentic", "adaptive"],
};

function state(): AgentFormState {
  const formState = new AgentFormState();
  formState.values.suggest_followups = false;
  formState.values.suggestion_timeout_s = 4;
  formState.values.suggestion_model = null;
  return formState;
}

describe("TabsCapabilities suggestion fields", () => {
  it("toggles LLM suggestions and enables the timeout input", async () => {
    const formState = state();
    const { getByTestId } = render(TabsCapabilities, { state: formState, catalog });
    const followupSwitch = getByTestId("field-suggest_followups");
    const timeoutInput = getByTestId("field-suggestion_timeout_s") as HTMLInputElement;

    expect(timeoutInput.disabled).toBe(true);
    await fireEvent.click(followupSwitch);

    expect(formState.values.suggest_followups).toBe(true);
    expect(timeoutInput.disabled).toBe(false);
  });

  it("stores a suggestion model and maps an empty input to null", async () => {
    const formState = state();
    formState.values.suggest_followups = true;
    const { getByTestId } = render(TabsCapabilities, { state: formState, catalog });
    const modelInput = getByTestId("field-suggestion_model") as HTMLInputElement;

    await fireEvent.input(modelInput, { target: { value: "google:gemini-flash" } });
    expect(formState.values.suggestion_model).toBe("google:gemini-flash");

    await fireEvent.input(modelInput, { target: { value: "" } });
    expect(formState.values.suggestion_model).toBeNull();
  });
});
