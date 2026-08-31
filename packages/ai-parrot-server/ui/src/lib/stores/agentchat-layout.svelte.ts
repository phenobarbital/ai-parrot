/**
 * AgentChat Layout Store — manages the 3-pane layout state and global nav integration.
 *
 * Panes: [History | Chat | Canvas]
 */

// Left pane (conversation history) — collapsed by default
let historyOpen = $state(false);

// Right pane (canvas) — collapsed by default
let canvasOpen = $state(false);

// Canvas expanded mode — hides the chat thread to maximize canvas space
let canvasExpanded = $state(false);

// Tracks whether we auto-collapsed the global (Program) sidebar
let _prevGlobalNavState = $state(false);
let _didCollapseGlobalNav = $state(false);

// Global nav collapse callback — set by Program.svelte
let _globalNavCollapseSetter: ((collapsed: boolean) => void) | null = null;

export function registerGlobalNavControl(
  setter: (collapsed: boolean) => void,
  currentState: boolean,
) {
  _globalNavCollapseSetter = setter;
  _prevGlobalNavState = currentState;
}

export function unregisterGlobalNavControl() {
  _globalNavCollapseSetter = null;
}

export function collapseGlobalNav() {
  if (_globalNavCollapseSetter) {
    _prevGlobalNavState = false; // save that it was expanded
    _globalNavCollapseSetter(true);
    _didCollapseGlobalNav = true;
  }
}

export function restoreGlobalNav() {
  if (_globalNavCollapseSetter && _didCollapseGlobalNav) {
    _globalNavCollapseSetter(_prevGlobalNavState);
    _didCollapseGlobalNav = false;
  }
}

// --- History pane ---
export function getHistoryOpen() {
  return historyOpen;
}

export function toggleHistory() {
  historyOpen = !historyOpen;
}

export function openHistory() {
  historyOpen = true;
}

export function closeHistory() {
  historyOpen = false;
}

// --- Canvas pane ---
export function getCanvasOpen() {
  return canvasOpen;
}

export function toggleCanvas() {
  canvasOpen = !canvasOpen;
  if (!canvasOpen) canvasExpanded = false;
}

export function openCanvas() {
  canvasOpen = true;
  historyOpen = false; // auto-close history when canvas opens
}

export function closeCanvas() {
  canvasOpen = false;
  canvasExpanded = false;
}

// --- Canvas expanded mode ---
export function getCanvasExpanded() {
  return canvasExpanded;
}

export function toggleCanvasExpanded() {
  canvasExpanded = !canvasExpanded;
  if (canvasExpanded) {
    historyOpen = false; // close history when going full-screen
  }
}
