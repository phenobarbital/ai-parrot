/**
 * Avatar toggle persistence helpers — FEAT-169 LiveAvatar Integration
 *
 * Provides per-agent localStorage persistence for the "Talk with avatar" toggle.
 * All functions are SSR-safe (no-ops when browser is false) and wrapped in
 * try/catch to handle storage quota or security errors gracefully.
 *
 * This module intentionally has NO Svelte runes — it is a pure helper module.
 * Per-agent toggle state is owned by each host component (AgentChat, FloatingChatPanel).
 */

import { browser } from "$app/environment";

/** LocalStorage key for the avatar toggle preference for a given agent. */
const KEY = (agentId: string) => `navigator:agentchat:avatar:${agentId}`;

/**
 * Load the avatar toggle preference for the given agent from localStorage.
 *
 * Returns false when:
 *   - not in a browser (SSR)
 *   - the key has never been set
 *   - localStorage access throws (private browsing / quota)
 */
export function loadAvatarPreference(agentId: string): boolean {
  if (!browser) return false;
  try {
    return localStorage.getItem(KEY(agentId)) === "true";
  } catch {
    return false;
  }
}

/**
 * Persist the avatar toggle preference for the given agent to localStorage.
 *
 * No-op when:
 *   - not in a browser (SSR)
 *   - localStorage access throws (private browsing / quota)
 */
export function saveAvatarPreference(agentId: string, enabled: boolean): void {
  if (!browser) return;
  try {
    localStorage.setItem(KEY(agentId), enabled ? "true" : "false");
  } catch {
    // ignore — preference is best-effort
  }
}

/**
 * Reset the avatar toggle preference for the given agent (e.g. on 403 opt-in failure).
 * Equivalent to calling saveAvatarPreference(agentId, false).
 */
export function resetAvatarPreference(agentId: string): void {
  saveAvatarPreference(agentId, false);
}

/** LocalStorage key for the FULL Mode avatar show/hide preference. */
const VISIBLE_KEY = (agentId: string) =>
  `navigator:agentchat:avatar-visible:${agentId}`;

/**
 * Load the FULL Mode avatar visibility preference for the given agent.
 *
 * Unlike {@link loadAvatarPreference}, this defaults to **visible (true)** when
 * the key has never been set — FULL Mode is avatar-centric, so the talking head
 * is shown unless the user has explicitly hidden it.
 *
 * Returns true when not in a browser (SSR) or on storage errors.
 */
export function loadAvatarVisible(agentId: string): boolean {
  if (!browser) return true;
  try {
    const v = localStorage.getItem(VISIBLE_KEY(agentId));
    return v === null ? true : v === "true";
  } catch {
    return true;
  }
}

/**
 * Persist the FULL Mode avatar visibility preference for the given agent.
 * No-op under SSR or on storage errors (best-effort).
 */
export function saveAvatarVisible(agentId: string, visible: boolean): void {
  if (!browser) return;
  try {
    localStorage.setItem(VISIBLE_KEY(agentId), visible ? "true" : "false");
  } catch {
    // ignore — preference is best-effort
  }
}
