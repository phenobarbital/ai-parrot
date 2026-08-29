# TASK-2577: Documentation and migration notes

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2576
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 9**. FEAT-469 introduces a genuinely new integration
surface — a renderer can now invoke **any** non-hidden tool on an agent — and
that carries an operational and security posture operators must understand
before they deploy it. Documentation here is not an afterthought; it is where
the `a2ui_hidden` escape hatch and the `PermissionContext`-only threat model get
explained.

Runs last so it can document what was actually built, including whatever the
earlier tasks recorded in their completion notes (the `ToolDefinition` permission
gap from TASK-2570, the Redis concurrency resolution, the measured dispatch
overhead from TASK-2576).

---

## Scope

- Write `docs/outputs/a2ui-agent-functions.md`.
- Add a FEAT-469 section to `docs/migration/feat-273-a2ui-deprecations.md`.
- Cross-link from the existing A2UI docs.

**NOT in scope**: code changes. If writing the docs exposes a defect, file it
against the owning task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/a2ui-agent-functions.md` | CREATE | Main feature documentation |
| `docs/migration/feat-273-a2ui-deprecations.md` | MODIFY | Append the FEAT-469 section |
| existing A2UI docs under `docs/outputs/` | MODIFY | Cross-links |

---

## Codebase Contract (Anti-Hallucination)

> Everything documented must be verified against the **merged** implementation,
> not against this spec. The spec was written before FEAT-470 landed and several
> of its claims were corrected during implementation (see §6 "Contract Refresh").

### Facts that MUST appear correctly (verify each against the code before writing)

| Fact | Verified value |
|---|---|
| HTTP endpoint | `POST /api/v1/agents/{agent_id}/a2ui` (TASK-2573) |
| SSE stream | `GET` same path, `text/event-stream` — **not** AgentTalk's `b'\n\x00'` framing |
| Capabilities | `GET /api/v1/agents/{agent_id}/a2ui/capabilities` |
| Deep-link route | `/api/v1/a2ui/resume/web` — GET is a confirm page (no consume), POST consumes |
| A2A extension URI | `https://a2ui.org/a2a-extension/a2ui/v1.0` (`a2a/models.py:335`) |
| A2UI media type | `application/a2ui+json` (`a2a/models.py:336`) |
| Default catalog id | `https://parrot.dev/catalogs/v1` (`catalog/base.py:52`) |
| Pending-call TTL | 900 s; surface state has **no** TTL of its own (session-scoped) |
| Data-model cap | `A2UI_MAX_DATA_MODEL_BYTES`, default 1 MiB |
| Tool opt-out | `a2ui_hidden: bool = False` on `AbstractTool` |
| User activation | `a2ui_requires_user_activation: bool = False`; enforced by the **renderer**, never the agent |
| Deep-link wire tag | `{"type": "a2ui_action", "action": <v1.0 action envelope>}` — shared with Teams and Telegram |

### Does NOT Exist — do not document these
- ~~an opt-in tool registration model~~ — it is opt-**out** via `a2ui_hidden`.
- ~~a per-surface function allowlist~~ — explicitly rejected in spec §1 Non-Goals; the control is the `PermissionContext`.
- ~~a JS runtime executing `callRendererFunction` in `interactive_html.py`~~ — a spec Non-Goal; static renderers keep `supports_actions=False` and deep links.
- ~~`inlineCatalogs` support~~ — `acceptsInlineCatalogs` is hard-coded `False`.
- ~~agent-initiated proactive surface pushes~~ — a Non-Goal, deferred to a later feature.
- ~~routing A2UI envelopes through the AgentTalk POST~~ — explicitly rejected in §8.

---

## Implementation Notes

### `docs/outputs/a2ui-agent-functions.md` — required sections
1. **What this adds** — the RPC leg, contrasted with the display-only surfaces of FEAT-470.
2. **The four flows** — `callAgentFunction`, `action` (+ `sendDataModel`),
   `callRendererFunction`, `rendererFunctionResponse`/`error` — each with a real
   envelope example copied from a passing test, not invented.
3. **Transports** — the HTTP endpoint, the A2A `DataPart` path, deep links; and
   which delivery mechanism each uses for `callRendererFunction`
   (stream **and** queued-for-next-send).
4. **Security posture** — this is the section that matters most. State plainly:
   - Every non-hidden `ToolManager` tool is renderer-invocable.
   - The **only** barrier is the session user's `PermissionContext`.
   - `build_principal_context` defaults `roles` to an empty frozenset, so
     role-gated PBAC policies deny by default.
   - Whatever TASK-2570 recorded about the `ToolDefinition` (`@tool`) path not
     enforcing permissions — document it honestly as a known limitation if it
     was not fixed.
   - How to hide a destructive tool (`a2ui_hidden = True`), with an example.
   - That an audit line is logged per invocation, and what it contains.
5. **Marking a tool** — both attributes, with a code example.
6. **The structured turn format** — visible user turn when `userMessage` is
   present, system turn otherwise; `dataModel` never in the turn text.
7. **Operational limits** — 900 s pending TTL, 1 MiB data-model cap, session-scoped
   surface state, and the concurrency caveat TASK-2570 recorded.

### Migration note
Append a FEAT-469 section covering:
- `Artifact.from_a2ui_envelope` gained `allow_actions` (default `False` — no
  behaviour change for existing callers).
- The Agent Card now advertises the A2UI extension.
- `setup_deeplink_routes` is now mounted by the manager; deployments that mounted
  it themselves should remove their own registration.
- The two new `AbstractTool` attributes and their defaults.

### Key Constraints
- Verify every code sample by running it or lifting it from a passing test.
- Match the existing style of `docs/outputs/` and `docs/migration/`.
- No aspirational features — document only what shipped.

### References in Codebase
- `docs/migration/feat-273-a2ui-deprecations.md` — the file to extend; follow its section structure.
- `docs/outputs/` — existing A2UI docs for tone and cross-linking.
- The completion notes of TASK-2570 and TASK-2576 — sources for the security and performance sections.

---

## Acceptance Criteria

- [ ] `docs/outputs/a2ui-agent-functions.md` exists with all seven sections above.
- [ ] Every envelope example is copied from a passing test, not invented.
- [ ] The security section states the "all non-hidden tools are exposed / `PermissionContext` is the only barrier" posture explicitly.
- [ ] Any unresolved permission gap recorded by TASK-2570 is documented as a known limitation.
- [ ] `a2ui_hidden` and `a2ui_requires_user_activation` are documented with examples and defaults.
- [ ] The migration note covers `allow_actions`, the Agent Card extension, the now-mounted deep-link routes, and the two tool attributes.
- [ ] Every endpoint, URI, constant and default in the doc matches the table in this task's contract.
- [ ] Cross-links from the existing A2UI docs resolve.
- [ ] Docs build cleanly (`mkdocs build --strict` if configured).

---

## Test Specification

Documentation task — verification is by review plus these mechanical checks:

```bash
# every documented path/constant actually exists in the code
grep -rn "api/v1/agents/{agent_id}/a2ui" packages/ai-parrot-server/src
grep -rn "a2ui_hidden\|a2ui_requires_user_activation" packages/ai-parrot/src
grep -n "A2UI_EXTENSION_URI\|A2UI_MEDIA_TYPE" packages/ai-parrot/src/parrot/a2a/models.py
grep -rn "setup_deeplink_routes" packages/ai-parrot-server/src   # must now show the manager call

# docs build
mkdocs build --strict
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 9, §1 Non-Goals (so you do not document rejected ideas), §7 Known Risks.
2. **Check dependencies** — TASK-2576 in `sdd/tasks/completed/`.
3. **Read the completion notes** of TASK-2570 (permission gap, Redis concurrency) and TASK-2576 (measured overhead) — they are inputs to the security and limits sections.
4. **Verify the Codebase Contract** — check every value in the facts table against the merged code; the spec is not authoritative here, the implementation is.
5. **Update status** in the index → `"in-progress"`.
6. **Write** the docs.
7. **Verify** every acceptance criterion, including the mechanical greps.
8. **Move this file** to `sdd/tasks/completed/`.
9. **Update index** → `"done"` and set the feature's `completed_at`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Known limitations documented**:

**Deviations from spec**: none | describe if any
