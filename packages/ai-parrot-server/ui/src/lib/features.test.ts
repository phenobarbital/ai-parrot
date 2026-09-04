import { describe, it, expect } from "vitest";
import { features } from "./features";

describe("features", () => {
  it("defaults every flag to true", () => {
    expect(Object.values(features).every(Boolean)).toBe(true);
    expect(Object.isFrozen(features)).toBe(true);
  });

  it("exposes exactly the nine documented flags", () => {
    expect(Object.keys(features).sort()).toEqual(
      [
        "voice",
        "avatar",
        "maps",
        "charts",
        "canvas",
        "infographic",
        "datasets",
        "richEditor",
        "a2ui",
      ].sort(),
    );
  });
});
