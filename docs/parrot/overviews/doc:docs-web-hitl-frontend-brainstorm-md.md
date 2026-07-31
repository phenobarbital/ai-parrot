---
type: Wiki Overview
title: Web HITL — Frontend Brainstorm
id: doc:docs-web-hitl-frontend-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This document describes what the `navigator-frontend-next` codebase must
  implement
---

# Web HITL — Frontend Brainstorm

**Date**: 2026-05-05
**Author**: AI-Parrot backend team (FEAT-146)
**Status**: Draft — for discussion with navigator-frontend-next team
**Intended audience**: Frontend engineers working on `navigator-frontend-next`

---

## Purpose

This document describes what the `navigator-frontend-next` codebase must implement
to support the **Web Human-in-the-Loop (HITL)** feature shipped in AI-Parrot FEAT-146.

It is self-contained: copy it into `navigator-frontend-next` to seed your own
SDD spec. All wire formats are authoritative and come directly from the backend
spec (sdd/specs/web-hitl-and-demo-agent.spec.md §2 Data Models).

---

## 1. Wire-Format Contract

### 1.1 WebSocket — `hitl:question`

Emitted by the backend over the user's existing WebSocket channel
(`ws/userinfo`, subscribed by `AgentChat.svelte` via the user's `session_id`).

```json
{
  "type": "hitl:question",
  "interaction_id": "uuid-string",
  "interaction_type": "approval" | "single_choice" | "multi_choice" | "form" | "free_text",
  "question": "string",
  "context": "optional string or null",
  "options": [
    {
      "key": "stable_id",
      "label": "What the user sees",
      "description": "optional hint or null"
    }
  ],
  "form_schema": { "...": "json-schema object or null" },
  "default_response": "any value or null",
  "timeout": 7200.0,
  "source_agent": "hitl_demo",
  "deadline": "2026-05-05T12:34:56Z"
}
```

**Field notes:**

| Field | Type | Always present? | Notes |
|---|---|---|---|
| `type` | string | yes | Always `"hitl:question"` |
| `interaction_id` | string (UUID) | yes | Use this to POST the response back |
| `interaction_type` | string | yes | Determines which UI component to render |
| `question` | string | yes | Main prompt text to display |
| `context` | string or null | no | Supporting context / instructions |
| `options` | array | conditional | Non-empty for `single_choice`, `multi_choice`, `approval` |
| `form_schema` | object or null | conditional | JSON Schema for `form` type |
| `default_response` | any or null | no | Pre-filled value; render as pre-selected or placeholder |
| `timeout` | number (seconds) | yes | Maximum wait time; show a countdown if useful |
| `deadline` | ISO-8601 string | yes | Absolute expiry; prefer this over computing from timeout |
| `source_agent` | string | yes | Name of the agent that sent the question |

### 1.2 WebSocket — `hitl:cancel`

Emitted when the backend cancels a pending interaction (timeout, agent abort).

```json
{
  "type": "hitl:cancel",
  "interaction_id": "uuid-string",
  "reason": "timeout" | "agent_cancelled" | "string"
}
```

On receiving this event: dismiss the HITL prompt for the given `interaction_id`
without sending a response.

### 1.3 HTTP — `POST /api/v1/agents/hitl/respond`

**Request body:**

```json
{
  "interaction_id": "uuid-string",
  "value": "any — type depends on interaction_type",
  "response_type": "single_choice"
}
```

**Field notes:**

| Field | Required | Notes |
|---|---|---|
| `interaction_id` | yes | Copied from the `hitl:question` payload |
| `value` | yes | See §2 for type per interaction_type |
| `response_type` | no | Optional override; if omitted, backend infers from interaction |

**Success response (HTTP 200):**

```json
{
  "ok": true,
  "interaction_id": "uuid-string"
}
```

**Error responses:**

| HTTP Status | Meaning |
|---|---|
| 400 | Malformed body (missing `interaction_id`, invalid JSON) |
| 401/403 | Unauthenticated or unauthorized user |
| 404 | `interaction_id` not found (already resolved, expired, or typo) |
| 500 | Backend error during response processing |
| 503 | HITL service not initialised (configuration error) |

---

## 2. Interaction Type → UI Component Mapping

| `interaction_type` | Suggested UI Component | `value` type in POST | Notes |
|---|---|---|---|
| `approval` | Confirm / Cancel buttons | `true` or `false` (boolean) | Binary decision; "options" may contain Approve/Reject labels |
| `single_choice` | Radio buttons or pill tabs | `string` — the chosen `key` | Render `options[].label`; submit the corresponding `key` |
| `multi_choice` | Checkboxes | `string[]` — array of chosen `key`s | Allow zero or more selections |
| `form` | Dynamic form from JSON Schema | `object` — key-value map | Use `form_schema` to render fields; validate client-side before POST |
| `free_text` | Single-line or multi-line text input | `string` | No options; show `default_response` as placeholder |

**For `approval`:** The backend typically sends two options with keys `"yes"` / `"no"` or
`"approve"` / `"reject"`. Render them as distinct CTA buttons, not a text input.

**For `handoff_to_human` (HandoffTool):** The backend may emit a special system message or a
plain `free_text` interaction explaining that the agent is handing off. There is no structured
choice; the user's next free-text message resumes the agent. See §5 for the difference
between HumanTool and HandoffTool rendering.

---

## 3. Edge Cases & Resilience

### 3.1 WebSocket Disconnect During Question Delivery

The WebSocket message is sent once. If the connection drops before the frontend
receives `hitl:question`, the question is lost (the backend will timeout and send
`hitl:cancel`). The frontend should:

- Reconnect as normal.
- **Not** attempt to replay lost messages — the backend timeout/cancel covers it.
- Show "Session reconnected" feedback to the user.

> Note: suspend/resume mode (where the agent suspends and a fresh POST can re-enter
> it) is not implemented in FEAT-146. Long-poll only — the original POST stays open.
> If the HTTP connection drops the agent request will also fail.

### 3.2 Timeout Behavior

The `deadline` field gives the absolute cutoff. The frontend should:

- Optionally show a countdown timer (e.g., "Respond within 2:00 minutes").
- Disable or hide the response widget when `deadline` is passed.
- Listen for `hitl:cancel` from the backend and dismiss the prompt gracefully.
- **Do not block the rest of the chat UI** — the HITL prompt should be non-modal
  or dismissible so the user can still read prior messages.

### 3.3 Cancel / Interruption

When `hitl:cancel` arrives:

- Animate the prompt out.
- Show a brief system message like "The agent moved on — this question expired."
- Do not attempt to POST a response.

### 3.4 Page Reload

On reload:

- The WebSocket reconnects and re-subscribes to the user's channel.
- The pending interaction is **not** re-emitted by the backend (no replay mechanism).
- The HTTP long-poll that is driving the agent is likely still alive on the server,
  but the frontend has no way to know the answer is still pending.
- Safe approach: store the pending `interaction_id` in `sessionStorage` before sending.
  On reload, if a pending ID exists and the channel has not received `hitl:cancel`,
  show a "You have a pending question" banner with the last-seen question (also cached).

> This is an open question — see §6.

### 3.5 Multiple Concurrent Interactions

FEAT-146 sends interactions to a single target (one session, one person). The backend
will not normally send two concurrent questions. However, the frontend should:

- Index pending prompts by `interaction_id`.
- If a second `hitl:question` arrives before the first is answered, show both
  (e.g., in a queue or stacked cards) and let the user answer in any order.
- POST responses independently for each `interaction_id`.

### 3.6 HumanTool vs. HandoffTool Rendering

| Scenario | Backend mechanism | What the frontend sees |
|---|---|---|
| Agent asks a question and waits | `HumanTool` → `WebHumanTool` | `hitl:question` with `interaction_type` and structured options |
| Agent hands off control to human | `HandoffTool` | A plain chat message from the agent saying "I'm handing off to a human"; the agent's long-poll completes immediately |

HandoffTool does **not** emit a `hitl:question` event. The frontend treats it as a
normal agent turn that ends with a text message. The human can then send a follow-up
chat message and the next agent invocation uses the handoff context.

---

## 4. Recommended File Layout in `navigator-frontend-next`

```
src/
  lib/
    hitl/
      HITLManager.ts        # subscribes to ws events; stores pending interactions
      HITLStore.ts          # Svelte store: Map<interaction_id, HITLQuestion>
      api.ts                # postHITLResponse(interaction_id, value, response_type?)
      types.ts              # TypeScript types for hitl:question / hitl:cancel payloads
    components/
      hitl/
        HitlPrompt.svelte       # Main container; delegates to sub-components
        HitlApproval.svelte     # Confirm/Cancel buttons
        HitlSingleChoice.svelte # Radio button group
        HitlMultiChoice.svelte  # Checkbox group
        HitlFreeText.svelte     # Text input
        HitlForm.svelte         # JSON-Schema-driven form
        HitlCountdown.svelte    # Optional countdown timer
  routes/
    (app)/
      chat/
        [agent_id]/
          +page.svelte        # AgentChat.svelte — add HITL prompt rendering here
```

**Where to mount `HitlPrompt`:**

Add it inside `AgentChat.svelte` just above or below the message input:

```svelte
{#each $pendingHITLInteractions as interaction (interaction.interaction_id)}
  <HitlPrompt {interaction} on:submit={handleHITLSubmit} />
{/each}
```

---

## 5. Minimal `HitlPrompt.svelte` Pseudocode Sketch

```svelte
<!-- HitlPrompt.svelte — minimal pseudocode -->
<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { HITLQuestion } from "$lib/hitl/types";
  import { postHITLResponse } from "$lib/hitl/api";
  import HitlApproval from "./HitlApproval.svelte";
  import HitlSingleChoice from "./HitlSingleChoice.svelte";
  import HitlMultiChoice from "./HitlMultiChoice.svelte";
  import HitlFreeText from "./HitlFreeText.svelte";
  import HitlForm from "./HitlForm.svelte";
  import HitlCountdown from "./HitlCountdown.svelte";

  export let interaction: HITLQuestion;

  const dispatch = createEventDispatcher();
  let submitting = false;
  let error: string | null = null;

  async function submit(value: unknown) {
    if (submitting) return;
    submitting = true;
    error = null;
    try {
      const ok = await postHITLResponse(
        interaction.interaction_id,
        value,
        interaction.interaction_type,
      );
      if (ok) {
        dispatch("submit", { interaction_id: interaction.interaction_id });
      } else {
        error = "Response failed. Please try again.";
      }
    } catch (e) {
      error = String(e);
    } finally {
      submitting = false;
    }
  }
</script>

<div class="hitl-prompt" role="dialog" aria-modal="false">
  <p class="hitl-question">{interaction.question}</p>

  {#if interaction.context}
    <p class="hitl-context">{interaction.context}</p>
  {/if}

  <HitlCountdown deadline={interaction.deadline} />

  {#if interaction.interaction_type === "approval"}
    <HitlApproval options={interaction.options} on:select={(e) => submit(e.detail)} />
  {:else if interaction.interaction_type === "single_choice"}
    <HitlSingleChoice options={interaction.options} on:select={(e) => submit(e.detail)} />
  {:else if interaction.interaction_type === "multi_choice"}
    <HitlMultiChoice options={interaction.options} on:select={(e) => submit(e.detail)} />
  {:else if interaction.interaction_type === "form"}
    <HitlForm schema={interaction.form_schema} on:submit={(e) => submit(e.detail)} />
  {:else}
    <!-- free_text default -->
    <HitlFreeText
      placeholder={interaction.default_response ?? "Type your answer..."}
      on:submit={(e) => submit(e.detail)}
    />
  {/if}

  {#if error}
    <p class="hitl-error" role="alert">{error}</p>
  {/if}
</div>
```

**`$lib/hitl/api.ts` sketch:**

```typescript
export async function postHITLResponse(
  interactionId: string,
  value: unknown,
  responseType?: string,
): Promise<boolean> {
  const res = await fetch("/api/v1/agents/hitl/respond", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      interaction_id: interactionId,
      value,
      ...(responseType ? { response_type: responseType } : {}),
    }),
    credentials: "include",
  });
  if (res.status === 200) return true;
  const body = await res.json().catch(() => ({}));
  console.error("HITL respond error", res.status, body);
  return false;
}
```

**`HITLManager.ts` (subscription logic):**

```typescript
// Inside the ws message handler in wsService / HITLManager
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "hitl:question") {
    HITLStore.add(msg);          // adds to the pending interactions store
  } else if (msg.type === "hitl:cancel") {
    HITLStore.remove(msg.interaction_id);   // dismisses the prompt
  }
};
```

---

## 6. Open Questions for the Frontend Author

The following decisions are not prescribed by the backend spec and should be
resolved by the frontend team before implementation begins:

1. **Modal vs. inline bubble**
   Should `HitlPrompt` appear as a modal overlay (blocking), a floating bubble
   above the input, or an inline card inside the message stream?
   - Modal: highest clarity but interrupts UX for concurrent tasks.
   - Inline: fits naturally into the chat timeline; multiple interactions are easy to stack.
   - Floating bubble: good if the user scrolls up in the message history.

2. **Theming and styling approach**
   Should HITL prompts use the same CSS variables as the rest of the chat UI,
   or have a distinct visual treatment (e.g., a different background colour,
   border, or icon) to make them clearly interactive?

3. **Accessibility requirements**
   - Focus management: when a `hitl:question` arrives, should focus move to the prompt?
   - Screen reader announcements: should an `aria-live` region announce new questions?
   - Keyboard navigation: all choice options and buttons must be reachable via Tab.
   - Countdown timers should not auto-update in a way that spams screen readers.

4. **Telemetry and analytics**
   Should interaction submission times, timeout rates, or user abandonment (no
   response before timeout) be tracked? If so, what events should be emitted
   and where (Plausible, Mixpanel, custom)?

5. **Multi-respondent scenarios (future)**
   FEAT-146 targets a single user session. If future work introduces
   consensus-mode interactions (multiple humans must approve), the `HitlPrompt`
   will need to display partial results and a "waiting for N more responses"
   state. Should the TypeScript types be designed to accommodate this now?

6. **Page reload / session persistence**
   Should pending interactions survive a page reload (via `sessionStorage`)?
   If yes, what is the maximum age of a cached question (to avoid showing
   stale, already-expired questions on reload)?

7. **Error recovery**
   If the HTTP POST to `/api/v1/agents/hitl/respond` fails with a 503 or
   network error, should the frontend automatically retry (how many times,
   with what backoff), or surface an error to the user?

8. **HandoffTool UX**
   When the agent sends a handoff message, the chat reply is a plain text
   message with no `hitl:question`. Should the frontend show any visual
   indicator (e.g., "Agent handed off — you can reply now") or is the
   standard agent reply sufficient?

---

## Appendix A: Backend Source References

| Item | File | Key line(s) |
|---|---|---|
| `WebHumanChannel` implementation | `packages/ai-parrot/src/parrot/human/channels/web.py` | Full file |
| `WebHumanTool` + ContextVar | `packages/ai-parrot/src/parrot/handlers/web_hitl.py` | Lines 52–191 |
| `HITLResponseHandler` | `packages/ai-parrot/src/parrot/handlers/web_hitl.py` | Lines 238–359 |
| `HITLDemoAgent` | `packages/ai-parrot/src/parrot/agents/demo.py` | Full file |
| `HumanInteraction` model | `packages/ai-parrot/src/parrot/human/models.py` | `HumanInteraction` class |
| Wire format spec | `sdd/specs/web-hitl-and-demo-agent.spec.md` | §2 Data Models (lines 170–212) |
| Endpoint registration | `packages/ai-parrot/src/parrot/manager/manager.py` | `setup_web_hitl` call |

---

*End of brainstorm document. Copy to `navigator-frontend-next/docs/` and begin the SDD spec from here.*
