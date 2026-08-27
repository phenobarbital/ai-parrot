import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";

import AgentsList from "./AgentsList.svelte";

const dbAgent: BotAgentItem = {
  name: "helpdesk",
  source: "database",
  description: "Handles support tickets",
  role: "Support Agent",
  enabled: true,
};

const registryAgent: BotAgentItem = {
  name: "cron-sync",
  source: "registry",
  module_path: "plugins.cron_sync",
  file_path: "/opt/plugins/cron_sync.py",
  singleton: true,
  at_startup: true,
  priority: 10,
  tags: ["scheduled"],
};

function mockAgents(agents: BotAgentItem[]) {
  return vi.spyOn(apiClient, "get").mockResolvedValue({ data: { agents, total: agents.length } });
}

describe("AgentsList", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders database and registry agent rows", async () => {
    mockAgents([dbAgent, registryAgent]);

    const { findByTestId } = render(AgentsList);

    expect(await findByTestId("agent-row-helpdesk")).toBeTruthy();
    expect(await findByTestId("agent-row-cron-sync")).toBeTruthy();
  });

  it("renders — for missing fields on minimal registry agents", async () => {
    mockAgents([registryAgent]);

    const { findByTestId } = render(AgentsList);

    const row = await findByTestId("agent-row-cron-sync");
    // description/role/enabled are absent on the minimal registry shape.
    expect(row.textContent).toContain("—");
  });

  it("filters by search text", async () => {
    mockAgents([dbAgent, registryAgent]);

    const { findByTestId, getByLabelText, queryByTestId } = render(AgentsList);
    await findByTestId("agent-row-helpdesk");

    await fireEvent.input(getByLabelText("Search agents"), { target: { value: "cron" } });
    await waitFor(() => expect(queryByTestId("agent-row-helpdesk")).toBeNull());
    expect(queryByTestId("agent-row-cron-sync")).toBeTruthy();
  });

  it("filters by source", async () => {
    mockAgents([dbAgent, registryAgent]);

    const { findByTestId, getByRole, queryByTestId } = render(AgentsList);
    await findByTestId("agent-row-helpdesk");

    await fireEvent.click(getByRole("button", { name: "Database" }));
    await waitFor(() => expect(queryByTestId("agent-row-cron-sync")).toBeNull());
    expect(queryByTestId("agent-row-helpdesk")).toBeTruthy();

    await fireEvent.click(getByRole("button", { name: "All" }));
    await waitFor(() => expect(queryByTestId("agent-row-cron-sync")).toBeTruthy());
  });

  it("opens read-only detail on row click and closes cleanly", async () => {
    mockAgents([dbAgent]);

    const { findByTestId, getByTestId, queryByTestId } = render(AgentsList);
    const row = await findByTestId("agent-row-helpdesk");

    await fireEvent.click(row);
    expect(await findByTestId("agent-detail-dialog")).toBeTruthy();
    expect(getByTestId("agent-detail-raw-json").textContent).toContain("helpdesk");
  });

  it("has no mutating controls", async () => {
    mockAgents([dbAgent, registryAgent]);

    const { findByTestId, queryByRole } = render(AgentsList);
    await findByTestId("agent-row-helpdesk");

    expect(queryByRole("button", { name: /create/i })).toBeNull();
    expect(queryByRole("button", { name: /^edit$/i })).toBeNull();
    expect(queryByRole("button", { name: /delete/i })).toBeNull();
  });

  it("shows retry card on fetch error", async () => {
    const getSpy = vi.spyOn(apiClient, "get").mockRejectedValue(new Error("network down"));

    const { findByTestId, getByRole } = render(AgentsList);
    expect(await findByTestId("agents-retry-card")).toBeTruthy();

    getSpy.mockResolvedValue({ data: { agents: [dbAgent], total: 1 } });
    await fireEvent.click(getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
  });

  it("shows an empty state when there are no agents", async () => {
    mockAgents([]);

    const { findByTestId } = render(AgentsList);
    expect(await findByTestId("agents-empty-state")).toBeTruthy();
  });
});
