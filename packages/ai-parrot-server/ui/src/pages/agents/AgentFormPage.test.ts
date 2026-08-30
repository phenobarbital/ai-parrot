import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import { router } from "$lib/router.svelte";

import AgentFormPage from "./AgentFormPage.svelte";

const catalogResponse = {
  llm_providers: ["google"],
  operation_modes: ["conversational", "agentic", "adaptive"],
  memory_types: ["memory", "file", "redis"],
  knowledge_bases: [],
  bot_class_default: "BasicBot",
};

const toolsResponse = { tools: {} };

const agentResponse = {
  chatbot_id: "11111111-1111-1111-1111-111111111111",
  name: "helpdesk",
  source: "database",
  goal: "Resolve tickets quickly.",
  backstory: "I help with support.",
  rationale: "I stay calm and professional.",
};

function mockGetByUrl(handlers: Record<string, unknown>) {
  return vi.spyOn(apiClient, "get").mockImplementation((url: string) => {
    for (const [prefix, data] of Object.entries(handlers)) {
      if (url.startsWith(prefix)) return Promise.resolve({ data });
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

describe("AgentFormPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    router.params = {};
  });

  it("shows a loading skeleton while fetching", () => {
    router.params = {};
    // Never resolves within this synchronous assertion window.
    vi.spyOn(apiClient, "get").mockReturnValue(new Promise(() => {}));

    const { getByTestId } = render(AgentFormPage);

    expect(getByTestId("agent-form-loading")).toBeTruthy();
  });

  it("create mode (no router.params.name): renders AgentForm without fetching an agent", async () => {
    router.params = {};
    const get = mockGetByUrl({
      "/api/v1/admin/catalog": catalogResponse,
      "/api/v1/agent_tools": toolsResponse,
    });

    const { findByTestId } = render(AgentFormPage);

    expect(await findByTestId("agent-form")).toBeTruthy();
    expect(get.mock.calls.some(([url]) => url.startsWith("/api/v1/bots/"))).toBe(false);
  });

  it("edit mode (router.params.name set): fetches the agent, catalog, and tools", async () => {
    router.params = { name: "helpdesk" };
    const get = mockGetByUrl({
      "/api/v1/admin/catalog": catalogResponse,
      "/api/v1/agent_tools": toolsResponse,
      "/api/v1/bots/helpdesk": agentResponse,
    });

    const { findByTestId } = render(AgentFormPage);

    expect(await findByTestId("agent-form")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/api/v1/bots/helpdesk");
  });

  it("shows a retry card on error, and Retry re-fetches", async () => {
    router.params = {};
    const get = vi
      .spyOn(apiClient, "get")
      .mockRejectedValueOnce(new Error("network down"))
      .mockRejectedValueOnce(new Error("network down"));

    const { findByTestId } = render(AgentFormPage);

    expect(await findByTestId("agent-form-retry-card")).toBeTruthy();

    get.mockImplementation((url: string) => {
      if (url.startsWith("/api/v1/admin/catalog")) return Promise.resolve({ data: catalogResponse });
      if (url.startsWith("/api/v1/agent_tools")) return Promise.resolve({ data: toolsResponse });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    await fireEvent.click(await findByTestId("agent-form-retry-card"));
    const retryButton = (await findByTestId("agent-form-retry-card")).querySelector("button");
    await fireEvent.click(retryButton!);

    expect(await findByTestId("agent-form")).toBeTruthy();
  });
});
