import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentFormState } from "$lib/stores/agent-form.svelte";
import type { ToolInfo } from "$lib/types/generated/ToolsListResponse";

vi.mock("$lib/api/studio", () => ({
  getAgentToolkits: vi.fn().mockResolvedValue({ agent: "helpdesk", editable: true, toolkits: [], unavailable: [] }),
  getToolkitSchema: vi.fn().mockRejectedValue(new Error("not a toolkit")),
  getAgentMcpServers: vi.fn().mockResolvedValue({ agent: "helpdesk", editable: true, servers: [] }),
  putAgentMcpServers: vi.fn(),
  getToolkitOptions: vi.fn(),
  putAgentToolkit: vi.fn(),
  deleteAgentToolkit: vi.fn(),
  reloadAgent: vi.fn(),
}));

import TabsTools from "./TabsTools.svelte";

const tools: Record<string, ToolInfo> = {
  search_web: { tool_name: "Search web", module_path: "parrot_tools.search" },
};

function state(selected: string[] = []): AgentFormState {
  return { values: { tools: selected } } as unknown as AgentFormState;
}

describe("TabsTools", () => {
  afterEach(() => vi.clearAllMocks());

  it("toggling a plain tool updates state.values.tools", async () => {
    const formState = state();
    const { getByTestId } = render(TabsTools, { formState, tools });

    await waitFor(() => expect(getByTestId("tool-switch-search_web")).toBeTruthy());
    await fireEvent.click(getByTestId("tool-switch-search_web"));

    expect(formState.values.tools).toEqual(["search_web"]);
  });

  it("surfaces selected tools absent from the catalog", () => {
    const { getByTestId } = render(TabsTools, { formState: state(["retired_tool"]), tools });

    expect(getByTestId("tool-unknown-retired_tool").textContent).toContain("retired_tool");
  });

  it("shows the read-only reason returned by the toolkit endpoint", async () => {
    const { getAgentToolkits } = await import("$lib/api/studio");
    vi.mocked(getAgentToolkits).mockResolvedValueOnce({
      agent: "registry-agent",
      editable: false,
      reason: "Registry definition is read-only",
      toolkits: [],
      unavailable: [],
    });

    const { findByTestId } = render(TabsTools, { formState: state(), tools, agentName: "registry-agent" });

    expect((await findByTestId("tools-readonly-banner")).textContent).toContain("Registry definition is read-only");
  });
});
