import { describe, expect, it } from "vitest";
import { axisDomain, splitByAxis } from "./dual-axis";

describe("splitByAxis", () => {
  it("puts only exact 'right' entries on the right", () => {
    expect(splitByAxis(["a", "b", "c"], ["left", "right", null])).toEqual({ left: ["a", "c"], right: ["b"] });
  });
  it("treats a missing/short seriesAxes as all-left", () => {
    expect(splitByAxis(["a", "b"])).toEqual({ left: ["a", "b"], right: [] });
    expect(splitByAxis(["a", "b"], ["right"])).toEqual({ left: ["b"], right: ["a"] });
  });
});

describe("axisDomain", () => {
  const rows = [
    { a: 10, b: 1000, c: -5 },
    { a: 20, b: 3000, c: 2 },
  ];
  it("unstacked positive: [0, max]", () => {
    expect(axisDomain(rows, ["a"], false)).toEqual([0, 20]);
  });
  it("unstacked with negatives: floor is the real minimum", () => {
    expect(axisDomain(rows, ["c"], false)).toEqual([-5, 2]);
  });
  it("stacked: row sums with a 0 floor", () => {
    expect(axisDomain(rows, ["a", "c"], true)).toEqual([0, 22]);
  });
  it("only the given keys count", () => {
    expect(axisDomain(rows, ["a"], false)).toEqual([0, 20]);
    expect(axisDomain(rows, ["b"], false)).toEqual([0, 3000]);
  });
  it("coerces missing/non-numeric to 0", () => {
    expect(axisDomain([{ a: "x" }, {}], ["a"], false)).toEqual([0, 0]);
  });
});
