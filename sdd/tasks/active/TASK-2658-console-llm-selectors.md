# TASK-2658: Dev-flow console LLM selectors (server_dev.py + dev.html)

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2651, TASK-2652, TASK-2655, TASK-2656
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (goal G7). The console gains three selector groups + the
partner toggle, all resolving to a `DevFlowModelPlan` in the run payload.

---

## Scope

- **`GET /api/config`** (`server_dev.py:195-245`): extend the `defaults`
  block with the plan defaults —
  dev pool rows `[{agent:"nova",model:"zai.glm-5"},{agent:"nova",model:"qwen.qwen3-coder-480b-a35b-v1:0"}]`;
  `research_primary: "claude-opus-5"`; partner `{enabled:false, backend:"gpt", model:"gpt-5.6-sol"}`;
  review `{primary:{agent:"claude-code",model:"claude-opus-5"}, counter_model:"gpt-5.6-sol"}`.
  Model options come from `llm_catalog.catalog_payload()` (already spread
  at `:198`) — NVIDIA NIM rows stay listed, never preselected.
- **`POST /api/flow/run`** (`server_dev.py:248-334`): parse the new fields
  into a `DevFlowModelPlan` — reuse `ops_server._parse_dev_agents`
  (`server.py:1026-1058`) for the pool rows (backend strict, model
  free-text); add small parsers for research/review fields with the same
  validation posture; pass the plan into the run (via the TASK-2652
  threading — re-read how the runner receives per-run config after 2652).
- **`static/dev.html`**: three selector groups + partner toggle, populated
  from `/api/config`; editable rows for the pool (same UX shape as the ops
  console's dev_agents rows); free-text model inputs with picker
  suggestions.
- Tests: config payload contents, run parsing (happy path + unknown
  backend rejected with the supported-list message), NIM-not-default.

**NOT in scope**: partner coordinator wiring (TASK-2657 — the toggle may
ship first; an enabled toggle before 2657 lands simply produces a plan
whose partner field no-ops), ops console (`server.py`) UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/server_dev.py` | MODIFY | config defaults + run parsing |
| `examples/dev_loop/static/dev.html` | MODIFY | selector UI |
| `packages/ai-parrot/tests/flows/dev_loop/test_server_dev_model_plan.py` (or the existing server_dev test module — grep first) | CREATE/MODIFY | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan  # TASK-2651
# server_dev.py imports llm_catalog (examples/dev_loop/llm_catalog.py:20-31 — a pure
# re-export shim over parrot.flows.dev_loop.catalog; identity-guarded by
# packages/ai-parrot/tests/flows/dev_loop/test_catalog.py — do NOT add logic to the shim)
```

### Existing Signatures to Use
```python
# examples/dev_loop/server_dev.py (verified 2026-09-01)
# :190-192 index handler; :195-245 handle_config; :209-231 defaults block
#   (:210 development_agent fallback "claude-code"; :232-243 adversarial_review block)
# :248-334 handle_run; :283-292 skip_qa/skip_jira/require_plan_approval reads
# :109-181 _build_dev_brief_from_form — reads form["dev_agents"] via
#   ops_server._parse_dev_agents (:169) and form["judge_panel"] via _parse_judge_panel (:172)
# :30-34 reuse policy: import from server.py, don't copy
# :545 build_app(redis_url=...); routes :553-565

# examples/dev_loop/server.py
# :1026-1058 _parse_dev_agents — rejects unknown backend via llm_catalog.get_backend (:1051-1054);
#   model is free text (:1057). REUSE for pool rows.
# :1065-1094 _parse_judge_panel — judge-panel only; NOT for the review pair (pair is not judges)

# parrot/flows/dev_loop/catalog.py
# :299-317 _backend_payload (env-overridden model preselection); :349-372 catalog_payload
```

### Does NOT Exist
- ~~A `model_plan` field in the current run payload~~ — created by this task.
- ~~Selector UI groups in dev.html for research/review/pool~~ — none exist.
- ~~`moonshotai/kimi-k3` on the NVIDIA NIM backend~~ — kimi-k3 is `moonshot`-backend-only; NIM is 401 for this account: listed, never default.
- ~~A model whitelist~~ — model inputs stay free text (catalog policy `catalog.py:22-24`).

---

## Implementation Notes

- Keep `server_dev.py`'s import-don't-copy discipline (`:30-34`).
- The `adversarial_review` block at `:232-243` documents the mandatory
  read-only second seat — the new review-pair selectors complement it; do
  not remove the mandatory note, update its wording to reflect
  configurability of models (not of the seat's existence).
- aiohttp handlers, async throughout; JSON field names mirror the
  `DevFlowModelPlan` schema exactly to keep parsing trivial.

---

## Acceptance Criteria

- [ ] `/api/config` carries the plan defaults exactly as specified (GLM + Qwen pool, Opus 5 research, partner off, Opus 5 + gpt-5.6-sol review)
- [ ] Run payload parses into `DevFlowModelPlan`; unknown backend rejected naming supported backends
- [ ] NIM appears in options, never preselected
- [ ] UI: three selector groups + partner toggle functional against /api/config
- [ ] Tests pass; `ruff check examples/dev_loop/server_dev.py` clean

---

## Test Specification

```python
# tests for server_dev model-plan surface (locate/extend existing server_dev tests first)
class TestServerDevModelPlan:
    async def test_config_carries_plan_defaults(self): ...
    async def test_run_parses_plan_fields(self): ...
    async def test_unknown_backend_rejected(self): ...
    async def test_nim_listed_not_default(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — TASK-2651/2652/2655/2656 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** first (server_dev.py line anchors especially — file moves often)
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
