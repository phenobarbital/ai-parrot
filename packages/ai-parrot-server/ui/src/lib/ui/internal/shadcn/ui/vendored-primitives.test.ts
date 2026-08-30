/**
 * Smoke tests for the five primitive families vendored in TASK-2585
 * (FEAT-475): tabs, checkbox, switch, textarea, slider. Confirms each is
 * importable via its `index.js` barrel (the acceptance criterion) and
 * renders without crashing in jsdom — no positioning assertions per the
 * FEAT-468 jsdom caveat (bits-ui floating primitives are awkward in
 * jsdom; these five are all non-floating).
 */
import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";

import { Checkbox } from "./checkbox/index.js";
import { Slider } from "./slider/index.js";
import { Switch } from "./switch/index.js";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs/index.js";
import TabsHarness from "./TabsHarness.test.svelte";
import { Textarea } from "./textarea/index.js";

// ResizeObserver is stubbed globally in vitest-setup.ts (needed by every
// test that renders a Slider, not just this file — TASK-2587 moved it
// there from a local stub here).

// Re-export sanity: Tabs/TabsList/TabsTrigger/TabsContent are exercised
// through TabsHarness.test.svelte below (a compound component needs real
// markup around it); referencing them here documents that the barrel
// exports all four names.
void Tabs;
void TabsList;
void TabsTrigger;
void TabsContent;

describe("vendored primitive families are importable and render", () => {
  it("Checkbox", () => {
    const { container } = render(Checkbox, { checked: false });
    expect(container.querySelector('[data-slot="checkbox"]')).toBeTruthy();
  });

  it("Switch", () => {
    const { container } = render(Switch, { checked: false });
    expect(container.querySelector('[data-slot="switch"]')).toBeTruthy();
  });

  it("Textarea", () => {
    const { container } = render(Textarea, { value: "hello" });
    const el = container.querySelector('[data-slot="textarea"]') as HTMLTextAreaElement;
    expect(el).toBeTruthy();
    expect(el.value).toBe("hello");
  });

  it("Slider", () => {
    const { container } = render(Slider, { value: 50 });
    expect(container.querySelector('[data-slot="slider"]')).toBeTruthy();
  });

  it("Tabs (Root/List/Trigger/Content) via a harness", () => {
    const { getByText } = render(TabsHarness);
    expect(getByText("General")).toBeTruthy();
    expect(getByText("General tab content")).toBeTruthy();
  });
});
