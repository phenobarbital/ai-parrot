import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient, { ApiError } from "$lib/api/http";
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";

import DeleteAgentDialog from "./DeleteAgentDialog.svelte";

const dbAgent: BotAgentItem = { name: "helpdesk", source: "database" };

describe("DeleteAgentDialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("disables the destructive button until the typed name matches exactly", async () => {
    const { getByTestId } = render(DeleteAgentDialog, { agent: dbAgent, open: true });
    const confirmInput = getByTestId("delete-agent-confirm-input") as HTMLInputElement;
    const confirmButton = getByTestId("delete-agent-confirm") as HTMLButtonElement;

    expect(confirmButton.disabled).toBe(true);

    await fireEvent.input(confirmInput, { target: { value: "help" } });
    expect(confirmButton.disabled).toBe(true);

    await fireEvent.input(confirmInput, { target: { value: "helpdesk" } });
    expect(confirmButton.disabled).toBe(false);
  });

  it("calls DELETE /api/v1/bots/{name} and ondeleted() on success", async () => {
    const del = vi
      .spyOn(apiClient, "delete")
      .mockResolvedValue({ data: { message: "deleted", name: "helpdesk" } });
    const ondeleted = vi.fn();

    const { getByTestId } = render(DeleteAgentDialog, {
      agent: dbAgent,
      open: true,
      ondeleted,
    });

    await fireEvent.input(getByTestId("delete-agent-confirm-input"), {
      target: { value: "helpdesk" },
    });
    await fireEvent.click(getByTestId("delete-agent-confirm"));

    await waitFor(() => expect(del).toHaveBeenCalledWith("/api/v1/bots/helpdesk"));
    await waitFor(() => expect(ondeleted).toHaveBeenCalled());
  });

  it("shows a 403 message verbatim and keeps the dialog open on error", async () => {
    vi.spyOn(apiClient, "delete").mockRejectedValue(
      new ApiError(
        "Agent 'helpdesk' is a repo YAML/code agent and cannot be deleted via this endpoint.",
        "auth",
        403,
      ),
    );

    const { getByTestId, findByTestId } = render(DeleteAgentDialog, {
      agent: dbAgent,
      open: true,
    });

    await fireEvent.input(getByTestId("delete-agent-confirm-input"), {
      target: { value: "helpdesk" },
    });
    await fireEvent.click(getByTestId("delete-agent-confirm"));

    const error = await findByTestId("delete-agent-error");
    expect(error.textContent).toContain(
      "Agent 'helpdesk' is a repo YAML/code agent and cannot be deleted via this endpoint.",
    );
    // Dialog content is still rendered — it did not close on error.
    expect(getByTestId("delete-agent-dialog")).toBeTruthy();
  });

  it("resets the typed name and error each time it opens for a (possibly different) agent", async () => {
    vi.spyOn(apiClient, "delete").mockRejectedValue(new ApiError("boom", "server", 500));

    const { getByTestId, findByTestId, rerender } = render(DeleteAgentDialog, {
      agent: dbAgent,
      open: true,
    });

    await fireEvent.input(getByTestId("delete-agent-confirm-input"), {
      target: { value: "helpdesk" },
    });
    await fireEvent.click(getByTestId("delete-agent-confirm"));
    await findByTestId("delete-agent-error");

    await rerender({ agent: dbAgent, open: false });
    await rerender({ agent: dbAgent, open: true });

    expect((getByTestId("delete-agent-confirm-input") as HTMLInputElement).value).toBe("");
    expect(() => getByTestId("delete-agent-error")).toThrow();
  });
});
