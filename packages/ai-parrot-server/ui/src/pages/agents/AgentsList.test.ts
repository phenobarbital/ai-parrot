import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import { router } from "$lib/router.svelte";
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

  it("renders Create Agent and Edit/Delete only on database rows (TASK-2588)", async () => {
    mockAgents([dbAgent, registryAgent]);

    const { findByTestId, queryByTestId } = render(AgentsList);
    await findByTestId("agent-row-helpdesk");

    expect(await findByTestId("create-agent-button")).toBeTruthy();
    expect(await findByTestId("agent-edit-helpdesk")).toBeTruthy();
    expect(await findByTestId("agent-delete-helpdesk")).toBeTruthy();
    // Registry rows keep no mutating affordance — unchanged FEAT-468 rule.
    expect(queryByTestId("agent-edit-cron-sync")).toBeNull();
    expect(queryByTestId("agent-delete-cron-sync")).toBeNull();
  });

  it("Create Agent navigates to /admin/agents/new", async () => {
    mockAgents([dbAgent]);
    const navigateSpy = vi.spyOn(router, "navigate");

    const { findByTestId } = render(AgentsList);
    await fireEvent.click(await findByTestId("create-agent-button"));

    expect(navigateSpy).toHaveBeenCalledWith("/admin/agents/new");
  });

  it("Edit navigates to /admin/agents/{name} without opening the detail dialog", async () => {
    mockAgents([dbAgent]);
    const navigateSpy = vi.spyOn(router, "navigate");

    const { findByTestId, queryByTestId } = render(AgentsList);
    await fireEvent.click(await findByTestId("agent-edit-helpdesk"));

    expect(navigateSpy).toHaveBeenCalledWith("/admin/agents/helpdesk");
    // The row's own onclick (open detail) must not also fire.
    expect(queryByTestId("agent-detail-dialog")).toBeNull();
  });

  it("Delete opens the confirmation dialog without opening the detail dialog", async () => {
    mockAgents([dbAgent]);

    const { findByTestId, queryByTestId } = render(AgentsList);
    await fireEvent.click(await findByTestId("agent-delete-helpdesk"));

    expect(await findByTestId("delete-agent-dialog")).toBeTruthy();
    expect(queryByTestId("agent-detail-dialog")).toBeNull();
  });

  it('"Show disabled" toggles include_disabled on the list request', async () => {
    const get = mockAgents([dbAgent]);

    const { findByTestId } = render(AgentsList);
    await findByTestId("agent-row-helpdesk");
    expect(get).toHaveBeenLastCalledWith("/api/v1/bots");

    await fireEvent.click(await findByTestId("show-disabled-toggle"));

    await waitFor(() => expect(get).toHaveBeenLastCalledWith("/api/v1/bots?include_disabled=true"));
  });

  it("a disabled database agent shows a disabled Badge", async () => {
    mockAgents([{ ...dbAgent, enabled: false }]);

    const { findByTestId } = render(AgentsList);

    expect(await findByTestId("agent-disabled-badge-helpdesk")).toBeTruthy();
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
