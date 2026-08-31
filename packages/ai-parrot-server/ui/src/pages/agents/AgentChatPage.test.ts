import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient, { ApiError } from "$lib/api/http";
import { router } from "$lib/router.svelte";

// ai-parrot (FEAT-476 TASK-2597): swap the real (heavy) AgentChat for the
// shared test stub — see AgentChatStub.svelte's header comment.
vi.mock("$lib/components/agents/AgentChat.svelte", async () => ({
  default: (await import("./__mocks__/AgentChatStub.svelte")).default,
}));

import AgentChatPage from "./AgentChatPage.svelte";

const dbAgentResponse = {
  name: "helpdesk",
  source: "database",
  chatbot_id: "uuid-1",
  enabled: true,
};

const registryAgentResponse = {
  name: "cron-sync",
  source: "registry",
};

describe("AgentChatPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    router.params = {};
  });

  it("shows a loading skeleton while fetching", () => {
    router.params = { name: "helpdesk" };
    vi.spyOn(apiClient, "get").mockReturnValue(new Promise(() => {}));

    const { getByTestId } = render(AgentChatPage);

    expect(getByTestId("agent-chat-loading")).toBeTruthy();
  });

  it("passes chatbot_id for a database agent", async () => {
    router.params = { name: "helpdesk" };
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: dbAgentResponse });

    const { findByTestId, getByText } = render(AgentChatPage);

    const stub = await findByTestId("agentchat-stub");
    expect(stub).toHaveAttribute("data-agent-id", "helpdesk");
    expect(stub).toHaveAttribute("data-chatbot-id", "uuid-1");
    expect(stub).toHaveAttribute("data-variant", "default");
    expect(getByText("helpdesk")).toBeTruthy();
  });

  it("hides chatbotId for a registry agent (no prompt library)", async () => {
    router.params = { name: "cron-sync" };
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: registryAgentResponse });

    const { findByTestId } = render(AgentChatPage);

    const stub = await findByTestId("agentchat-stub");
    expect(stub).toHaveAttribute("data-agent-id", "cron-sync");
    expect(stub).not.toHaveAttribute("data-chatbot-id");
  });

  it("shows a not-found state for an unknown agent name (404)", async () => {
    router.params = { name: "does-not-exist" };
    vi.spyOn(apiClient, "get").mockRejectedValue(
      new ApiError("Not found", "server", 404),
    );

    const { findByTestId, queryByTestId } = render(AgentChatPage);

    expect(await findByTestId("agent-chat-not-found")).toBeTruthy();
    expect(queryByTestId("agentchat-stub")).toBeNull();
  });

  it("Back to Agents navigates to /admin/agents from the not-found state", async () => {
    router.params = { name: "does-not-exist" };
    vi.spyOn(apiClient, "get").mockRejectedValue(
      new ApiError("Not found", "server", 404),
    );
    const navigateSpy = vi.spyOn(router, "navigate");

    const { findByTestId } = render(AgentChatPage);
    await fireEvent.click(await findByTestId("agent-chat-not-found"));

    // The card itself isn't the button — click the button inside it.
    const button = (await findByTestId("agent-chat-not-found")).querySelector("button")!;
    await fireEvent.click(button);

    expect(navigateSpy).toHaveBeenCalledWith("/admin/agents");
  });

  it("shows a retry card on a non-404 error", async () => {
    router.params = { name: "helpdesk" };
    const getSpy = vi.spyOn(apiClient, "get").mockRejectedValue(
      new ApiError("Server error", "server", 500),
    );

    const { findByTestId, getByRole } = render(AgentChatPage);
    expect(await findByTestId("agent-chat-retry-card")).toBeTruthy();

    getSpy.mockResolvedValue({ data: dbAgentResponse });
    await fireEvent.click(getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
  });
});
