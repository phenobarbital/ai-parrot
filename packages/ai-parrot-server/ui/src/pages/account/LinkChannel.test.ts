import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "$lib/api/http";
import { confirmChannelLink, previewChannelLink } from "$lib/api/connections";
import { router } from "$lib/router.svelte";

vi.mock("$lib/api/connections", () => ({
  confirmChannelLink: vi.fn(),
  previewChannelLink: vi.fn(),
}));

vi.mock("$lib/router.svelte", () => ({ router: { navigate: vi.fn() } }));

const PREVIEW = {
  channel: "slack",
  channel_user_id: "U123",
  team_id: "T456",
  nav_user_id: "nav-user-789",
};

async function renderPage(token = "nonce-123") {
  window.history.replaceState({}, "", `/account/link?token=${token}`);
  const { default: LinkChannel } = await import("./LinkChannel.svelte");
  return render(LinkChannel);
}

describe("Account › Link channel", () => {
  beforeEach(() => {
    vi.mocked(previewChannelLink).mockResolvedValue(PREVIEW);
    vi.mocked(confirmChannelLink).mockResolvedValue({ channel: "slack", linked: true });
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.clearAllMocks();
  });

  it("loads a preview only and never confirms automatically", async () => {
    const { findByText } = await renderPage();

    expect(await findByText("This Slack account will be able to use your connections.")).toBeTruthy();
    expect(previewChannelLink).toHaveBeenCalledWith("nonce-123");
    expect(confirmChannelLink).not.toHaveBeenCalled();
  });

  it("shows both Slack identities and the current Navigator account", async () => {
    const { findByTestId } = await renderPage();

    expect((await findByTestId("slack-team-id")).textContent).toContain("T456");
    expect((await findByTestId("slack-user-id")).textContent).toContain("U123");
    expect((await findByTestId("navigator-user-id")).textContent).toContain("nav-user-789");
  });

  it("cancels without writing and navigates away", async () => {
    const { findByRole } = await renderPage();
    await fireEvent.click(await findByRole("button", { name: "Cancel" }));

    expect(confirmChannelLink).not.toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith("/account/connections");
  });

  it("confirms only once on a double click", async () => {
    const { findByRole } = await renderPage();
    const confirm = await findByRole("button", { name: "Confirm" });
    await Promise.all([fireEvent.click(confirm), fireEvent.click(confirm)]);

    await waitFor(() => expect(confirmChannelLink).toHaveBeenCalledTimes(1));
    expect(await findByRole("status")).toHaveTextContent("linked");
  });

  it.each([
    [409, "already linked to another Navigator account"],
    [410, "link has expired"],
    [500, "couldn't load this link"],
  ])("shows the expected copy for %s", async (status, copy) => {
    vi.mocked(previewChannelLink).mockRejectedValue(new ApiError("failed", "server", status));
    const { findByRole } = await renderPage();

    expect((await findByRole("alert")).textContent).toContain(copy);
  });
});
