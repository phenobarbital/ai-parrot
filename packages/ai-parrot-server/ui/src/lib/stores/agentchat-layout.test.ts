// FEAT-611: AgentChat layout store — maximize (expanded) vs swap (canvas primary) modes.
import { beforeEach, describe, expect, it } from "vitest";

import * as layout from "./agentchat-layout.svelte";

beforeEach(() => {
  layout.closeCanvas();
  layout.closeHistory();
});

describe("agentchat-layout — canvas swap / maximize", () => {
  it("swap makes the canvas primary without hiding the chat", () => {
    layout.openCanvas();
    layout.toggleCanvasPrimary();
    expect(layout.getCanvasPrimary()).toBe(true);
    expect(layout.getCanvasExpanded()).toBe(false);
    layout.toggleCanvasPrimary();
    expect(layout.getCanvasPrimary()).toBe(false);
  });

  it("maximize and swap are mutually exclusive", () => {
    layout.openCanvas();
    layout.toggleCanvasPrimary();
    layout.toggleCanvasExpanded();
    expect(layout.getCanvasExpanded()).toBe(true);
    expect(layout.getCanvasPrimary()).toBe(false);
    layout.toggleCanvasPrimary();
    expect(layout.getCanvasPrimary()).toBe(true);
    expect(layout.getCanvasExpanded()).toBe(false);
  });

  it("closing the canvas resets both modes", () => {
    layout.openCanvas();
    layout.toggleCanvasPrimary();
    layout.closeCanvas();
    expect(layout.getCanvasPrimary()).toBe(false);
    layout.openCanvas();
    layout.toggleCanvasExpanded();
    layout.toggleCanvas(); // closes
    expect(layout.getCanvasExpanded()).toBe(false);
    expect(layout.getCanvasPrimary()).toBe(false);
  });
});
