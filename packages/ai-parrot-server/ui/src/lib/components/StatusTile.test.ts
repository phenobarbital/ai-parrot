import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import StatusTile from "./StatusTile.svelte";

describe("StatusTile", () => {
  it("renders the label and value", () => {
    const { getByText, getByTestId } = render(StatusTile, { label: "Version", value: "1.2.3" });
    expect(getByText("Version")).toBeTruthy();
    expect(getByText("1.2.3")).toBeTruthy();
    expect(getByTestId("status-tile-version")).toBeTruthy();
  });

  it("renders a skeleton when loading", () => {
    const { getByTestId, queryByText } = render(StatusTile, {
      label: "Version",
      value: "1.2.3",
      loading: true,
    });
    expect(getByTestId("status-tile-version-skeleton")).toBeTruthy();
    expect(queryByText("1.2.3")).toBeNull();
  });
});
