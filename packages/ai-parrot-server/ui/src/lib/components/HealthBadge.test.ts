import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import HealthBadge from "./HealthBadge.svelte";

describe("HealthBadge", () => {
  it("renders the ok status", () => {
    const { getByTestId } = render(HealthBadge, { status: "ok" });
    const badge = getByTestId("health-badge-ok");
    expect(badge.textContent?.trim()).toBe("OK");
    expect(badge.className).toContain("text-success");
  });

  it("renders the unreachable status as destructive", () => {
    const { getByTestId } = render(HealthBadge, { status: "unreachable", detail: "timeout" });
    const badge = getByTestId("health-badge-unreachable");
    expect(badge.textContent?.trim()).toBe("Unreachable");
    expect(badge.title).toBe("timeout");
  });

  it("renders the unconfigured status as muted", () => {
    const { getByTestId } = render(HealthBadge, { status: "unconfigured" });
    const badge = getByTestId("health-badge-unconfigured");
    expect(badge.textContent?.trim()).toBe("Unconfigured");
    expect(badge.className).toContain("text-muted-foreground");
  });

  it("combines detail and latency into the title", () => {
    const { getByTestId } = render(HealthBadge, {
      status: "ok",
      detail: "reachable",
      latencyMs: 42,
    });
    expect(getByTestId("health-badge-ok").title).toBe("reachable · 42ms");
  });
});
