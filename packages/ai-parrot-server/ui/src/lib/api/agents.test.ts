import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient, { ApiError } from "$lib/api/http";

import {
  createAgent,
  deleteAgent,
  getAgent,
  getCatalog,
  listAgents,
  listTools,
  updateAgent,
} from "./agents";

describe("agents API wrappers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("listAgents() hits GET /api/v1/bots with no query param by default", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { agents: [], total: 0 } });

    await listAgents();

    expect(get).toHaveBeenCalledWith("/api/v1/bots");
  });

  it("listAgents({includeDisabled: true}) appends ?include_disabled=true", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { agents: [], total: 0 } });

    await listAgents({ includeDisabled: true });

    expect(get).toHaveBeenCalledWith("/api/v1/bots?include_disabled=true");
  });

  it("listAgents({includeDisabled: false}) omits the query param", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { agents: [], total: 0 } });

    await listAgents({ includeDisabled: false });

    expect(get).toHaveBeenCalledWith("/api/v1/bots");
  });

  it("getAgent() hits GET /api/v1/bots/{name}, URL-encoded", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { name: "my bot", source: "database" } });

    await getAgent("my bot");

    expect(get).toHaveBeenCalledWith("/api/v1/bots/my%20bot");
  });

  it("createAgent() PUTs the full body to /api/v1/bots", async () => {
    const put = vi
      .spyOn(apiClient, "put")
      .mockResolvedValue({ data: { message: "ok", name: "helpdesk" } });
    const body = { storage: "database" as const, name: "Helpdesk", goal: "g" };

    await createAgent(body);

    expect(put).toHaveBeenCalledWith("/api/v1/bots", body);
  });

  it("updateAgent() POSTs only the diff to /api/v1/bots/{name}", async () => {
    const post = vi
      .spyOn(apiClient, "post")
      .mockResolvedValue({ data: { message: "ok", name: "helpdesk" } });
    const patch = { enabled: false };

    await updateAgent("helpdesk", patch);

    expect(post).toHaveBeenCalledWith("/api/v1/bots/helpdesk", patch);
  });

  it("deleteAgent() DELETEs /api/v1/bots/{name}", async () => {
    const del = vi
      .spyOn(apiClient, "delete")
      .mockResolvedValue({ data: { message: "deleted", name: "helpdesk" } });

    await deleteAgent("helpdesk");

    expect(del).toHaveBeenCalledWith("/api/v1/bots/helpdesk");
  });

  it("deleteAgent() propagates a 403 ApiError for a registry agent, unmodified", async () => {
    const error = new ApiError("Forbidden", "auth", 403);
    vi.spyOn(apiClient, "delete").mockRejectedValue(error);

    await expect(deleteAgent("registry-bot")).rejects.toBe(error);
  });

  it("listTools() hits GET /api/v1/agent_tools", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { tools: {} } });

    await listTools();

    expect(get).toHaveBeenCalledWith("/api/v1/agent_tools");
  });

  it("getCatalog() hits GET /api/v1/admin/catalog", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: {
        llm_providers: [],
        operation_modes: [],
        memory_types: [],
        knowledge_bases: [],
      },
    });

    await getCatalog();

    expect(get).toHaveBeenCalledWith("/api/v1/admin/catalog");
  });
});
