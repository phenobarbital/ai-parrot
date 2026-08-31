/**
 * Infographic Block Registry — maps InfographicBlockType to Svelte component.
 *
 * FEAT-039: Separate registry from canvas-registry.ts which handles CanvasTabType.
 * This registry maps individual infographic block types to their renderer components.
 */
import type { Component } from "svelte";
import type { InfographicBlockType } from "./infographic-types";
import InfographicTitleBlock from "./blocks/InfographicTitleBlock.svelte";
import InfographicHeroCardBlock from "./blocks/InfographicHeroCardBlock.svelte";
import InfographicSummaryBlock from "./blocks/InfographicSummaryBlock.svelte";
import InfographicChartBlock from "./blocks/InfographicChartBlock.svelte";
import InfographicTableBlock from "./blocks/InfographicTableBlock.svelte";
import InfographicBulletListBlock from "./blocks/InfographicBulletListBlock.svelte";
import InfographicImageBlock from "./blocks/InfographicImageBlock.svelte";
import InfographicQuoteBlock from "./blocks/InfographicQuoteBlock.svelte";
import InfographicCalloutBlock from "./blocks/InfographicCalloutBlock.svelte";
import InfographicDividerBlock from "./blocks/InfographicDividerBlock.svelte";
import InfographicTimelineBlock from "./blocks/InfographicTimelineBlock.svelte";
import InfographicProgressBlock from "./blocks/InfographicProgressBlock.svelte";

const registry = new Map<InfographicBlockType, Component>();

// Register all block types
registry.set("title", InfographicTitleBlock as unknown as Component);
registry.set("hero_card", InfographicHeroCardBlock as unknown as Component);
registry.set("summary", InfographicSummaryBlock as unknown as Component);
registry.set("chart", InfographicChartBlock as unknown as Component);
registry.set("table", InfographicTableBlock as unknown as Component);
registry.set("bullet_list", InfographicBulletListBlock as unknown as Component);
registry.set("image", InfographicImageBlock as unknown as Component);
registry.set("quote", InfographicQuoteBlock as unknown as Component);
registry.set("callout", InfographicCalloutBlock as unknown as Component);
registry.set("divider", InfographicDividerBlock as unknown as Component);
registry.set("timeline", InfographicTimelineBlock as unknown as Component);
registry.set("progress", InfographicProgressBlock as unknown as Component);

export function registerInfographicBlock(
  type: InfographicBlockType,
  component: Component,
): void {
  registry.set(type, component);
}

export function getInfographicBlock(
  type: InfographicBlockType,
): Component | undefined {
  return registry.get(type);
}

export function hasInfographicBlock(type: InfographicBlockType): boolean {
  return registry.has(type);
}
