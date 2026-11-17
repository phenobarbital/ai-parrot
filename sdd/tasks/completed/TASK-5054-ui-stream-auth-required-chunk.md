# TASK-5054: `auth_required` stream chunk in the admin UI stream parser

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5052
**Assigned-to**: unassigned

---

## Context

Spec §2 "Chat (M4)": in streaming mode AgentTalk (TASK-5051) appends a NUL-framed trailer after the envelope,
`\x00{"auth_required": {…AuthRequiredPayload}, "turn_id": "…", "retry_safe": false}` — the same framing as the
FEAT-752 suggestions trailer. Today `StreamChunk` has `chunk | done | suggestions` only (`stream.ts:27-30`), so
the default streaming mode never shows a Connect pill (problem 3 in spec §1). This task teaches the parser the new
trailer; TASK-5055 renders it.

---

## Scope

- Add the `auth_required` variant to `StreamChunk` exactly as the spec §2 TS block.
- Yield it from `consumeStream` for a trailer frame whose `auth_required` is an object; `retry_safe` is `true`
  only when the frame carries boolean `true` (absent/other = `false` semantics — keep `undefined` when absent).
- Add tests to `stream.test.ts`.

**NOT in scope**: AgentChat rendering and retry (TASK-5055); the server trailer (TASK-5051); bot chat (`streamChatWithBot` is unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/api/stream.ts` | MODIFY | new `StreamChunk` variant + trailer branch |
| `packages/ai-parrot-server/ui/src/lib/api/stream.test.ts` | MODIFY | auth_required trailer tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import type { AgentChatSuggestion } from "$lib/types/generated/AgentChatResponse";   // verified: stream.ts:25 (existing)
import type { AuthRequiredPayload } from "$lib/types/generated/AuthRequiredPayload";  // created by TASK-5052
```

### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/api/stream.ts
export type StreamChunk =                                    // :27
  | { type: "chunk"; text: string }                          // :28
  | { type: "done"; message: AgentChatResponse | BotChatResponse }   // :29
  | { type: "suggestions"; suggestions: AgentChatSuggestion[]; turn_id?: string };   // :30
const SEPARATOR = "\x00";                                    // :32
function parseObjectFrame(text: string): Record<string, unknown> | null   // :47 — null on empty/malformed/non-object
async function* consumeStream(response: Response): AsyncGenerator<StreamChunk>   // :73
//   trailers are processed after EOF: `for (const frame of frames.slice(1)) { const trailer = parseObjectFrame(frame);
//   if (trailer && Array.isArray(trailer.suggestions)) { yield {type:"suggestions", …} } }`   (:141-150)
// stream.test.ts — FEAT-752 trailer tests from :113; helper `collect([...chunks])`, const ENVELOPE (see :140-195)
// Existing wrapper: packages/ai-parrot-server/tests/ui/test_vitest_suggestion_stream_trailer.py runs stream.test.ts + AgentChat.test.ts
```

### Does NOT Exist
- ~~An `auth_required` StreamChunk~~ — added here.
- ~~A separate HTTP header advertising the auth trailer~~ — none; the frame is detected by its `auth_required` key.
- ~~Ordering guarantees between the suggestions and auth_required trailers~~ — both may appear; handle each frame independently.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/ui/src/lib/api/stream.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/api/stream.test.ts", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Clients that ignore unknown trailers must keep working (spec §7 "NUL-framed trailers"): do not change how `done`
  or `suggestions` are yielded; existing tests must still pass untouched.
- The client never derives `retry_safe` from tool status — copy it only from the frame (spec M4).

---

## Implementation Blueprint

### Steps (in order)
1. Import `AuthRequiredPayload` and extend `StreamChunk` — *why*: the variant shape is fixed by spec §2.
2. Add an `else if` for `auth_required` in the trailer loop — *why*: independent of suggestions; one frame, one chunk.
3. Update the module docstring line describing trailers — *why*: keep the protocol comment accurate.
4. Add tests; run the Validation Command.

### `packages/ai-parrot-server/ui/src/lib/api/stream.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c 'import type { AgentChatSuggestion } from "$lib/types/generated/AgentChatResponse";' stream.ts)
// AFTER — insert below that import (verified: stream.ts:25)
import type { AuthRequiredPayload } from "$lib/types/generated/AuthRequiredPayload";
```
```ts
// occurrences: 1 (verified: grep -c '  | { type: "suggestions"; suggestions: AgentChatSuggestion[]; turn_id?: string };' stream.ts)
// REPLACE that line (verified: stream.ts:30) with:
  | { type: "suggestions"; suggestions: AgentChatSuggestion[]; turn_id?: string }
  | { type: "auth_required"; payload: AuthRequiredPayload; turn_id?: string; retry_safe?: boolean }; // absent = false
```
```ts
// occurrences: 1 (verified: grep -c '    if (trailer && Array.isArray(trailer.suggestions)) {' stream.ts)
// The existing `if (…suggestions…) { yield … }` block (stream.ts:143-149) gains an `else if` after its closing brace:
    } else if (trailer && trailer.auth_required !== null && typeof trailer.auth_required === "object"
               && !Array.isArray(trailer.auth_required)) {
      yield {
        type: "auth_required",
        payload: trailer.auth_required as AuthRequiredPayload,
        turn_id: typeof trailer.turn_id === "string" ? trailer.turn_id : undefined,
        retry_safe: trailer.retry_safe === true ? true : trailer.retry_safe === false ? false : undefined,
      };
    }
```
**Why**: mirrors the suggestions branch; strict `=== true` so a string/number never grants auto-retry (AC-7).

### FILL IN checklist
- [ ] Docstring at stream.ts:11-16 mentions the auth_required trailer.
- [ ] Tests below.

---

## Acceptance Criteria

- [ ] `StreamChunk` has the `auth_required` variant exactly as spec §2.
- [ ] Parser yields `{type:"auth_required"}` after `done` for an auth trailer, with and without a suggestions trailer.
- [ ] `retry_safe` is `true` only for boolean `true`; non-object `auth_required` is ignored.
- [ ] All pre-existing `stream.test.ts` tests still pass.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_suggestion_stream_trailer.py -q`

---

## Test Specification

```ts
// append to src/lib/api/stream.test.ts (reuse collect() and ENVELOPE)
it("yields an auth_required chunk for an auth trailer frame", async () => {
  const out = await collect([`\x00${ENVELOPE}\x00{"auth_required":{"provider":"jira","message":"m"},"turn_id":"t","retry_safe":false}`]);
  expect(out.map((c) => c.type)).toEqual(["done", "auth_required"]);
  // FILL IN: payload.provider === "jira", turn_id "t", retry_safe false
});
it("handles suggestions and auth_required trailers in either order", async () => { /* FILL IN */ });
it("treats non-boolean retry_safe as absent and ignores non-object auth_required", async () => { /* FILL IN */ });
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Blueprint; complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5054 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat codex luna (5053, test fixes by orchestrator d8b605fa); 5054 by orchestrator after two empty codex deliveries; 5059 nova glm
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
