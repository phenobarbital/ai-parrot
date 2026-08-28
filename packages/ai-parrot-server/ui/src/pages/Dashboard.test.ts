import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import type { AdminStatus } from "$lib/types/generated/AdminStatus";

import Dashboard, { formatUptime } from "./Dashboard.svelte";

const okStatus: AdminStatus = {
  name: "ai-parrot",
  version: "1.2.3",
  uptime_seconds: 3600 * 4 + 60 * 12,
  agents: { database: 5, registry: 7, loaded: 4 },
  crews: 2,
  dependencies: {
    postgres: { status: "ok" },
    redis: { status: "ok" },
    vector_store: { status: "ok" },
  },
};

describe("formatUptime", () => {
  it("formats days/hours/minutes", () => {
    expect(formatUptime(3 * 86400 + 4 * 3600 + 12 * 60)).toBe("3d 4h 12m");
  });

  it("formats hours/minutes without days", () => {
    expect(formatUptime(4 * 3600 + 12 * 60)).toBe("4h 12m");
  });

  it("formats minutes/seconds without hours", () => {
    expect(formatUptime(12 * 60 + 5)).toBe("12m 5s");
  });

  it("formats seconds only", () => {
    expect(formatUptime(5)).toBe("5s");
  });

  it("falls back to 0s for invalid input", () => {
    expect(formatUptime(-1)).toBe("0s");
    expect(formatUptime(Number.NaN)).toBe("0s");
  });
});

describe("Dashboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders tiles from AdminStatus", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: okStatus });

    const { findByText } = render(Dashboard);

    expect(await findByText("1.2.3")).toBeTruthy();
    expect(await findByText("4h 12m")).toBeTruthy();
    expect(await findByText("2")).toBeTruthy();
    expect(await findByText("5")).toBeTruthy();
    expect(await findByText("7")).toBeTruthy();
    expect(await findByText("4")).toBeTruthy();
  });

  it("renders degraded dependency badge", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({
      data: {
        ...okStatus,
        dependencies: {
          postgres: { status: "unreachable", detail: "timeout" },
          redis: { status: "ok" },
          vector_store: { status: "unconfigured" },
        },
      },
    });

    const { findByTestId } = render(Dashboard);

    expect(await findByTestId("health-badge-unreachable")).toBeTruthy();
    expect(await findByTestId("health-badge-ok")).toBeTruthy();
    expect(await findByTestId("health-badge-unconfigured")).toBeTruthy();
  });

  it("auto-refreshes on interval and cleans up", async () => {
    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValue({ data: okStatus });

    const { unmount } = render(Dashboard);

    await vi.advanceTimersByTimeAsync(0);
    expect(getSpy).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(15_000);
    expect(getSpy).toHaveBeenCalledTimes(2);

    unmount();

    await vi.advanceTimersByTimeAsync(30_000);
    expect(getSpy).toHaveBeenCalledTimes(2);
  });

  it("shows retry card on fetch error", async () => {
    const getSpy = vi.spyOn(apiClient, "get").mockRejectedValue(new Error("network down"));

    const { findByTestId, getByRole } = render(Dashboard);

    const retryCard = await findByTestId("dashboard-retry-card");
    expect(retryCard).toBeTruthy();

    getSpy.mockResolvedValue({ data: okStatus });
    await fireEvent.click(getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
  });
});
