/**
 * Canvas Component Registry — maps CanvasTabType to Svelte component.
 *
 * Initially registers placeholders. Actual implementations are added in later tasks.
 */
import type { Component } from "svelte";
import type { CanvasTabType } from "./canvas-tab-manager.svelte.js";
import BlockCanvas from "./BlockCanvas.svelte";
import InfographicCanvas from "./InfographicCanvas.svelte";
import AudioCanvas from "./AudioCanvas.svelte";
import SpreadsheetCanvas from "./SpreadsheetCanvas.svelte";
import InteractiveArtifactCanvas from "./InteractiveArtifactCanvas.svelte";

const registry = new Map<
  CanvasTabType,
  Component<{ data: unknown; previewMode?: boolean; agentId?: string }>
>();

// Register built-in canvas components
// FEAT-034: both 'markdown' and 'chart' now use BlockCanvas
registry.set(
  "markdown",
  BlockCanvas as unknown as Component<{
    data: unknown;
    previewMode?: boolean;
    agentId?: string;
  }>,
);
registry.set(
  "infographic",
  InfographicCanvas as unknown as Component<{
    data: unknown;
    previewMode?: boolean;
    agentId?: string;
  }>,
);
registry.set(
  "audio",
  AudioCanvas as unknown as Component<{
    data: unknown;
    previewMode?: boolean;
    agentId?: string;
  }>,
);
registry.set(
  "spreadsheet",
  SpreadsheetCanvas as unknown as Component<{
    data: unknown;
    previewMode?: boolean;
    agentId?: string;
  }>,
);
registry.set(
  "chart",
  BlockCanvas as unknown as Component<{
    data: unknown;
    previewMode?: boolean;
    agentId?: string;
  }>,
);
registry.set(
  "interactive",
  InteractiveArtifactCanvas as unknown as Component<{
    data: unknown;
    previewMode?: boolean;
    agentId?: string;
  }>,
);

export function registerCanvasComponent(
  type: CanvasTabType,
  component: Component<{
    data: unknown;
    previewMode?: boolean;
    agentId?: string;
  }>,
) {
  registry.set(type, component);
}

export function getCanvasComponent(
  type: CanvasTabType,
):
  | Component<{ data: unknown; previewMode?: boolean; agentId?: string }>
  | undefined {
  return registry.get(type);
}

export function hasCanvasComponent(type: CanvasTabType): boolean {
  return registry.has(type);
}
