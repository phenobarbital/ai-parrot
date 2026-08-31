/**
 * Canvas Persistence — saves and loads canvas state to/from IndexedDB.
 *
 * @deprecated FEAT-042: This entire module is currently unused. All consumers
 * were removed because the debounced auto-save mechanism has race conditions
 * with Svelte 5 reactive effects that cause deleted blocks to reappear.
 * The module is kept for future reuse when backend (DocumentDB) persistence
 * is implemented. See sdd/specs/maincanvas-broken-localstorage.spec.md.
 *
 * Uses Dexie's `canvas_state` table keyed by session_id.
 * Save is debounced to prevent excessive writes on rapid edits.
 */
import { db } from "$lib/services/chat-db";
import * as tabManager from "./canvas-tab-manager.svelte.js";
import type { CanvasTabType } from "./canvas-tab-manager.svelte.js";

// ─── Debounce state ───────────────────────────────────────────────────────────

let saveTimer: ReturnType<typeof setTimeout> | null = null;
const DEBOUNCE_MS = 500;

// Track the active session ID so immediateFlush() can be called without args
let activeSessionId: string | null = null;

// ─── Internal helpers ─────────────────────────────────────────────────────────

/**
 * Internal: performs the actual save to IndexedDB.
 * Uses structuredClone to strip Svelte 5 reactive Proxy objects before writing to Dexie.
 * Dexie's structured clone algorithm rejects Proxy objects, causing DexieError.
 */
async function performSave(sessionId: string): Promise<void> {
  try {
    // Deep-clone tab data to remove Svelte 5 $state reactive proxies.
    const tabs = tabManager.getTabs().map((tab) => {
      let safeData: unknown;
      try {
        safeData = structuredClone(tab.data);
      } catch {
        // Fallback: JSON round-trip strips proxies (loses non-JSON values)
        safeData = JSON.parse(JSON.stringify(tab.data ?? null));
      }
      return {
        id: tab.id,
        type: tab.type as string,
        title: tab.title,
        data: safeData,
        closable: tab.closable,
      };
    });
    const activeTabId = tabManager.getActiveTabId();
    await db.canvas_state.put({
      session_id: sessionId,
      tabs,
      activeTabId,
      updated_at: new Date(),
    });
  } catch (err) {
    console.warn("[canvas-persistence] Failed to save canvas state:", err);
  }
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * @deprecated FEAT-042: Canvas persistence disabled due to race conditions with
 * Svelte 5 reactive effects. Will be repurposed for backend DocumentDB persistence.
 *
 * Saves the current canvas state to IndexedDB for the given session.
 * Debounced: rapid calls within 500ms collapse into a single write.
 * Returns a promise that resolves when the save completes.
 */
export function saveCanvasState(sessionId: string): Promise<void> {
  if (!sessionId) return Promise.resolve();
  activeSessionId = sessionId;

  return new Promise((resolve) => {
    if (saveTimer !== null) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        await performSave(sessionId);
      } finally {
        saveTimer = null;
        resolve();
      }
    }, DEBOUNCE_MS);
  });
}

/**
 * @deprecated FEAT-042: Canvas persistence disabled due to race conditions with
 * Svelte 5 reactive effects. Will be repurposed for backend DocumentDB persistence.
 *
 * Immediately flushes the current canvas state to IndexedDB, bypassing the debounce.
 */
export async function immediateFlush(sessionId?: string): Promise<void> {
  const sid = sessionId ?? activeSessionId;
  if (!sid) return;
  // Cancel any pending debounced save
  if (saveTimer !== null) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  await performSave(sid);
}

/**
 * @deprecated FEAT-042: Canvas persistence disabled due to race conditions with
 * Svelte 5 reactive effects. Will be repurposed for backend DocumentDB persistence.
 *
 * Loads canvas state from IndexedDB for the given session.
 * Returns true if state was restored, false if no saved state exists.
 */
export async function loadCanvasState(sessionId: string): Promise<boolean> {
  if (!sessionId) return false;
  activeSessionId = sessionId;

  try {
    const state = await db.canvas_state.get(sessionId);
    if (!state || !state.tabs || state.tabs.length === 0) return false;

    // Reset current canvas state
    tabManager.resetCanvas();

    // Restore tabs
    for (const tab of state.tabs) {
      if (tab.id === "main-canvas") {
        // Main canvas is created by initCanvas() — just update its data
        tabManager.initCanvas();
        tabManager.updateTabData("main-canvas", tab.data);
      } else {
        tabManager.addTab(tab.type as CanvasTabType, tab.title, tab.data);
      }
    }

    // Restore active tab
    if (state.activeTabId) {
      tabManager.setActiveTab(state.activeTabId);
    }

    return true;
  } catch (err) {
    console.warn("[canvas-persistence] Failed to load canvas state:", err);
    return false;
  }
}

/**
 * @deprecated FEAT-042: Canvas persistence disabled due to race conditions with
 * Svelte 5 reactive effects. Will be repurposed for backend DocumentDB persistence.
 *
 * Deletes canvas state for a given session from IndexedDB.
 */
export async function clearCanvasState(sessionId: string): Promise<void> {
  if (!sessionId) return;
  try {
    await db.canvas_state.delete(sessionId);
  } catch (err) {
    console.warn("[canvas-persistence] Failed to clear canvas state:", err);
  }
}

/**
 * @deprecated FEAT-042: Canvas persistence disabled due to race conditions with
 * Svelte 5 reactive effects. Will be repurposed for backend DocumentDB persistence.
 *
 * Initializes canvas persistence for a session:
 * Attempts to load saved state; if none, initializes the default empty canvas.
 */
export async function initCanvasPersistence(sessionId: string): Promise<void> {
  if (!sessionId) {
    tabManager.resetCanvas();
    tabManager.initCanvas();
    return;
  }
  activeSessionId = sessionId;

  const restored = await loadCanvasState(sessionId);
  if (!restored) {
    tabManager.resetCanvas();
    tabManager.initCanvas();
  }
}
