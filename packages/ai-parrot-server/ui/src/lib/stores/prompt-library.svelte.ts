/**
 * Prompt Library Store
 *
 * Reactive store that manages public prompts (shared per chatbot) and user prompts
 * (per-user, per-agent). Both lists are server-backed. Uses Svelte 5 runes.
 */

import { get } from "svelte/store";
import type { Prompt } from "$lib/types/prompt-library";
import * as publicApi from "$lib/api/prompt-library";
import * as userApi from "$lib/api/user-prompts";
import { auth } from "$lib/auth";

const MAX_PROMPTS_PER_AGENT = 10;

// The public prompt_library endpoint rejects non-UUID chatbot_id values with
// a 400; callers sometimes pass a bot name/slug in chatbotId (registry bots).
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Resolve the authenticated user_id, waiting for auth hydration if needed.
 *
 * On a full page reload the auth store starts as {loading: true, session: null}
 * and hydrates from storage asynchronously. Components mount (and call
 * loadPrompts) before that finishes, so a plain get(auth.session) read would
 * skip the user-prompts fetch for logged-in users.
 */
function resolveUserId(): Promise<number | null> {
  return new Promise((resolve) => {
    let settled = false;
    const settle = (userId: number | null) => {
      if (settled) return;
      settled = true;
      resolve(userId);
      queueMicrotask(() => unsub());
    };
    // Safety net: never block prompt loading on a stuck auth store.
    const timer = setTimeout(() => settle(null), 5000);
    const unsub = auth.subscribe((s) => {
      if (!s.loading) {
        clearTimeout(timer);
        settle(s.session?.user_id ?? null);
      }
    });
  });
}

// ============================================================================
// State (Svelte 5 runes)
// ============================================================================

let publicPrompts = $state<Prompt[]>([]);
let userPrompts = $state<Prompt[]>([]);
let isLoading = $state(false);
let error = $state<string | null>(null);
let currentAgentId = $state<string | null>(null);
let currentChatbotId = $state<string | null>(null);

// ============================================================================
// Computed helpers (for derived values)
// ============================================================================

/**
 * Compute all prompts merged and sorted alphabetically by title.
 * Using a function instead of $derived for better test compatibility.
 */
function computeAllPrompts(): Prompt[] {
  return [...userPrompts, ...publicPrompts].sort((a, b) =>
    a.title.localeCompare(b.title),
  );
}

/**
 * Compute total number of prompts (user + public).
 */
function computePromptCount(): number {
  return userPrompts.length + publicPrompts.length;
}

/**
 * Compute whether more user prompts can be added.
 * Public prompts do not count toward the cap.
 */
function computeCanAddMore(): boolean {
  return userPrompts.length < MAX_PROMPTS_PER_AGENT;
}

// ============================================================================
// Getters (expose reactive state)
// ============================================================================

export function getPrompts(): Prompt[] {
  return computeAllPrompts();
}

export function getPublicPrompts(): Prompt[] {
  return publicPrompts;
}

export function getUserPrompts(): Prompt[] {
  return userPrompts;
}

/**
 * Starter prompts for the welcome-screen bubbles ("Try one of these").
 * Only system (public) prompts — user prompts stay in the toolbar so the empty
 * state shows the same onboarding suggestions to every user of the agent.
 * Ordered by created_at ascending and capped at `limit` (default 5).
 *
 * Single source of truth: both the text chat (AgentChat) and the voice chat
 * (AgentVoiceChat) call this so their starter bubbles stay consistent. See the
 * homologation note — this rule used to live only inside AgentChat.
 */
export function getStarterPrompts(limit = 5): Prompt[] {
  return [...publicPrompts]
    .sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
      return ta - tb;
    })
    .slice(0, limit);
}

export function isLoadingPrompts(): boolean {
  return isLoading;
}

export function getError(): string | null {
  return error;
}

export function getCanAddMore(): boolean {
  return computeCanAddMore();
}

export function getPromptCount(): number {
  return computePromptCount();
}

export function getCurrentAgentId(): string | null {
  return currentAgentId;
}

export function getChatbotId(): string | null {
  return currentChatbotId;
}

// ============================================================================
// Actions
// ============================================================================

/**
 * Load both public and user prompts for a chatbot/agent.
 *
 * Uses Promise.allSettled so a one-sided outage still renders the other list.
 *
 * @param agentId - The agent slug (used as fallback for user-prompts lookup)
 * @param chatbotId - The chatbot UUID (preferred for both APIs)
 */
export async function loadPrompts(
  agentId: string,
  chatbotId?: string,
): Promise<void> {
  currentAgentId = agentId;
  currentChatbotId = chatbotId ?? null;
  isLoading = true;
  error = null;

  const userId = await resolveUserId();

  const publicFetch =
    chatbotId && UUID_RE.test(chatbotId)
      ? publicApi.getPrompts(chatbotId)
      : Promise.resolve<Prompt[]>([]);

  // users_prompts.chatbot_id holds either the chatbot UUID or the agent slug.
  const userFetch =
    userId != null && (chatbotId || agentId)
      ? userApi.getUserPrompts({
          user_id: userId,
          chatbot_id: chatbotId || agentId,
        })
      : Promise.resolve<Prompt[]>([]);

  const [publicResult, userResult] = await Promise.allSettled([
    publicFetch,
    userFetch,
  ]);

  if (publicResult.status === "fulfilled") {
    publicPrompts = publicResult.value;
  } else {
    publicPrompts = [];
    error =
      publicResult.reason instanceof Error
        ? publicResult.reason.message
        : "Failed to load public prompts";
    console.error(
      "[PromptLibrary] Public prompts fetch failed:",
      publicResult.reason,
    );
  }

  if (userResult.status === "fulfilled") {
    userPrompts = userResult.value;
  } else {
    userPrompts = [];
    if (!error) {
      error =
        userResult.reason instanceof Error
          ? userResult.reason.message
          : "Failed to load user prompts";
    }
    console.error(
      "[PromptLibrary] User prompts fetch failed:",
      userResult.reason,
    );
  }

  isLoading = false;
}

/**
 * Add a new user prompt.
 *
 * @throws Error if user is not authenticated, or 10-prompt cap is reached.
 */
export async function addPrompt(
  agentId: string,
  title: string,
  query: string,
  chatbotId?: string,
): Promise<Prompt> {
  if (!computeCanAddMore()) {
    throw new Error(
      `Maximum ${MAX_PROMPTS_PER_AGENT} user prompts per agent reached`,
    );
  }

  const userId = get(auth.session)?.user_id;
  if (userId == null) {
    throw new Error("You must be signed in to create a prompt");
  }

  const effectiveChatbotId = chatbotId ?? currentChatbotId ?? undefined;
  if (!effectiveChatbotId && !agentId) {
    throw new Error("Missing chatbot_id and agent_id — cannot create prompt");
  }

  error = null;

  try {
    const created = await userApi.createUserPrompt({
      user_id: userId,
      chatbot_id: effectiveChatbotId ?? agentId,
      title,
      query,
    });
    userPrompts = [...userPrompts, created];
    return created;
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to create prompt";
    throw e;
  }
}

/**
 * Update an existing user prompt.
 *
 * Public prompts are read-only via the modal; trying to update one throws.
 */
export async function updatePrompt(prompt: Prompt): Promise<Prompt> {
  error = null;

  if (!prompt.is_user_prompt) {
    throw new Error("Only user prompts can be edited");
  }

  try {
    const updated = await userApi.updateUserPrompt(prompt.id, {
      title: prompt.title,
      query: prompt.query,
    });
    const index = userPrompts.findIndex((p) => p.id === prompt.id);
    if (index !== -1) {
      userPrompts = [
        ...userPrompts.slice(0, index),
        updated,
        ...userPrompts.slice(index + 1),
      ];
    }
    return updated;
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to update prompt";
    throw e;
  }
}

/**
 * Remove a user prompt from the library.
 */
export async function removePrompt(id: string): Promise<void> {
  error = null;
  try {
    await userApi.deleteUserPrompt(id);
    userPrompts = userPrompts.filter((p) => p.id !== id);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to delete prompt";
    throw e;
  }
}

/**
 * Clear the store state. Called on logout (see navauth/store.svelte.ts).
 */
export function clearStore(): void {
  publicPrompts = [];
  userPrompts = [];
  isLoading = false;
  error = null;
  currentAgentId = null;
  currentChatbotId = null;
}
