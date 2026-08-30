import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import { router } from "$lib/router.svelte";
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";

import AgentDetail from "./AgentDetail.svelte";

const dbAgent: BotAgentItem = {
  name: "helpdesk",
  source: "database",
  description: "Handles support tickets",
  role: "Support Agent",
  enabled: true,
};

const minimalRegistryAgent: BotAgentItem = {
  name: "cron-sync",
  source: "registry",
};

describe("AgentDetail", () => {
  it("renders labeled fields and the raw JSON for a full agent", () => {
    const { getByTestId, getByText } = render(AgentDetail, { agent: dbAgent, open: true });

    expect(getByText("helpdesk")).toBeTruthy();
    expect(getByText("Handles support tickets")).toBeTruthy();
    const raw = getByTestId("agent-detail-raw-json");
    expect(raw.textContent).toContain('"role": "Support Agent"');
  });

  it("does not crash on the minimal registry shape", () => {
    const { getByTestId, getByText } = render(AgentDetail, {
      agent: minimalRegistryAgent,
      open: true,
    });

    expect(getByText("cron-sync")).toBeTruthy();
    expect(getByText("No additional fields.")).toBeTruthy();
    expect(getByTestId("agent-detail-raw-json")).toBeTruthy();
  });

  it("renders nothing when there is no agent", () => {
    const { queryByTestId } = render(AgentDetail, { agent: null, open: true });
    expect(queryByTestId("agent-detail-raw-json")).toBeNull();
  });

  it("shows an Edit button for a database agent (TASK-2588)", () => {
    const { getByTestId } = render(AgentDetail, { agent: dbAgent, open: true });
    expect(getByTestId("agent-detail-edit")).toBeTruthy();
  });

  it("shows no Edit button for a registry agent", () => {
    const { queryByTestId } = render(AgentDetail, {
      agent: minimalRegistryAgent,
      open: true,
    });
    expect(queryByTestId("agent-detail-edit")).toBeNull();
  });

  it("Edit navigates to /admin/agents/{name} and closes the dialog", async () => {
    const navigateSpy = vi.spyOn(router, "navigate");
    const { getByTestId } = render(AgentDetail, { agent: dbAgent, open: true });

    await fireEvent.click(getByTestId("agent-detail-edit"));

    expect(navigateSpy).toHaveBeenCalledWith("/admin/agents/helpdesk");
  });
});
