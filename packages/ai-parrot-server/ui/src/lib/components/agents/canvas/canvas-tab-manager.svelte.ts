/**
 * Canvas Tab Manager — runes-based state for the canvas tab system.
 */
import { v4 as uuidv4 } from "uuid";

export type CanvasTabType =
  | "markdown"
  | "chart"
  | "spreadsheet"
  | "infographic"
  | "audio"
  | "interactive";

export interface CanvasTab {
  id: string;
  type: CanvasTabType;
  title: string;
  data: unknown;
  closable: boolean;
}

const MAIN_CANVAS_ID = "main-canvas";

let tabs = $state<CanvasTab[]>([]);
let activeTabId = $state<string | null>(null);

function ensureMainCanvas() {
  if (tabs.length === 0) {
    tabs.push({
      id: MAIN_CANVAS_ID,
      type: "markdown",
      title: "Main Canvas",
      data: [], // FEAT-034: empty CanvasBlock[] instead of string
      closable: false,
    });
    activeTabId = MAIN_CANVAS_ID;
  }
}

export function getTabs(): CanvasTab[] {
  return tabs;
}

export function getActiveTabId(): string | null {
  return activeTabId;
}

export function getActiveTab(): CanvasTab | undefined {
  return tabs.find((t) => t.id === activeTabId);
}

export function initCanvas() {
  ensureMainCanvas();
}

export function addTab(
  type: CanvasTabType,
  title: string,
  data: unknown = null,
): string {
  const id = uuidv4();
  tabs.push({ id, type, title, data, closable: true });
  activeTabId = id;
  return id;
}

export function removeTab(id: string) {
  const tab = tabs.find((t) => t.id === id);
  if (!tab || !tab.closable) return;

  const idx = tabs.findIndex((t) => t.id === id);
  tabs.splice(idx, 1);

  if (activeTabId === id) {
    // Activate the previous tab, or first tab
    const newIdx = Math.min(idx, tabs.length - 1);
    activeTabId = tabs[newIdx]?.id ?? null;
  }
}

export function setActiveTab(id: string) {
  if (tabs.find((t) => t.id === id)) {
    activeTabId = id;
  }
}

export function updateTabData(id: string, data: unknown) {
  const tab = tabs.find((t) => t.id === id);
  if (tab) {
    tab.data = data;
  }
}

export function updateTabTitle(id: string, title: string) {
  const tab = tabs.find((t) => t.id === id);
  if (tab && tab.closable) {
    tab.title = title;
  }
}

export function resetCanvas() {
  tabs.length = 0;
  activeTabId = null;
}
