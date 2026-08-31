import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

import { router } from "$lib/router.svelte";
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";

// ai-parrot (FEAT-476 TASK-2597): swap the real (heavy) AgentChat for the
// shared test stub — see AgentChatStub.svelte's header comment.
vi.mock("$lib/components/agents/AgentChat.svelte", async () => ({
  default: (await import("./__mocks__/AgentChatStub.svelte")).default,
}));

import AgentDetail from "./AgentDetail.svelte";

const dbAgent: BotAgentItem = {
  name: "helpdesk",
  source: "database",
  description: "Handles support tickets",
  role: "Support Agent",
  enabled: true,
  chatbot_id: "uuid-1",
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

  it("does not mount AgentChat until the Chat tab is selected (TASK-2597)", () => {
    render(AgentDetail, { agent: dbAgent, open: true });
    expect(screen.queryByTestId("agentchat-stub")).toBeNull();
  });

  it("Chat tab mounts a compact AgentChat with the agent's chatbot_id (TASK-2597)", async () => {
    render(AgentDetail, { agent: dbAgent, open: true });

    await fireEvent.click(screen.getByRole("tab", { name: "Chat" }));

    const stub = await waitFor(() => screen.getByTestId("agentchat-stub"));
    expect(stub).toHaveAttribute("data-agent-id", "helpdesk");
    expect(stub).toHaveAttribute("data-chatbot-id", "uuid-1");
    expect(stub).toHaveAttribute("data-variant", "compact");
  });

  it("Chat tab hides the chatbot_id for a registry agent (no prompt library)", async () => {
    render(AgentDetail, { agent: minimalRegistryAgent, open: true });

    await fireEvent.click(screen.getByRole("tab", { name: "Chat" }));

    const stub = await waitFor(() => screen.getByTestId("agentchat-stub"));
    expect(stub).toHaveAttribute("data-agent-id", "cron-sync");
    expect(stub).not.toHaveAttribute("data-chatbot-id");
  });
});
