import { describe, expect, it } from "vitest";
import { browser } from "./environment";

describe("shims/environment", () => {
  it("browser is always true (no server-rendering path in this SPA)", () => {
    expect(browser).toBe(true);
  });
});
