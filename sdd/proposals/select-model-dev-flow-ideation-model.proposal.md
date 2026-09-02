---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Proposal: select-model-DEV_FLOW_IDEATION_MODEL

**Date**: 2026-09-02
**Author**: jesuslarag@gmail.com (with sdd-ideation)
**Status**: draft

## Origin

> "in dev_flow interface `examples/dev_loop/server_dev.py` (check if it is also affecting the flow itself), there is no way to select another LLM model than Claude-Opus-5 (but in some cases we are expecting to use Fable)"

The ideation (research-primary) seat in the dev-flow is currently defaulted to
`claude-opus-5` (`DEFAULT_RESEARCH_PRIMARY` in
`packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py:62`). The
`DEV_FLOW_IDEATION_MODEL` env key and the `research_primary` form field
**exist** in the server and flow wiring (FEAT-486, TASK-2656), but:

1. `"claude-fable"` / `"claude-fable-5"` is absent from the `claude-code`
   backend's curated model list in `catalog.py` — only Bedrock cross-region id
   `"global.anthropic.claude-fable-5"` appears (line 342), for the nova/mantle
   path. Operators using the direct Anthropic API (`claude-code` backend) cannot
   discover Fable as an option.
2. `_model_plan_payload` in `server_dev.py` (lines 374–391) serialises
   `research_primary` as a **plain string** (the current value), but does not
   include a `research_primary_models` list alongside it — unlike `pool_backends`
   and `review_primary_backends` which ARE exposed. The UI therefore has no
   curated model list to render for the ideation seat picker.
3. `catalog_payload()` in `catalog.py` exposes roles `development`, `judge`,
   `primary_review`, `adversarial`, `research_partner` — but **no**
   `research_primary` role. Any UI or CLI surface that builds its picker from
   role lists sees the seat as invisible.

## Scope

### What Changes

1. **`packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py`** — add
   `"claude-fable"` (and `"claude-fable-5"` if the CLI accepts that alias) to
   the `claude-code` backend's `models` tuple, alongside the existing Opus 5 /
   Sonnet 5 / Sonnet 4.6 / Haiku 4.5 entries. Also add a `research_primary`
   role listing to `catalog_payload()` → `"roles"` so future UI/CLI surfaces can
   query it.

2. **`examples/dev_loop/server_dev.py` — `_model_plan_payload`** — extend the
   returned dict with a `research_primary_models` key: the curated model list for
   the `claude-code` backend (the sole backend that drives the ideation seat
   today), resolved through `catalog.py` so the entry is kept in one place.

3. **`examples/dev_loop/static/dev.html`** (if the research-primary picker is
   absent or incomplete) — ensure a model selector (or free-text field with a
   datalist) is rendered for the research-primary seat, pre-populated from
   `defaults.model_plan.research_primary_models`. The user's selection is sent
   as `research_primary` in the POST body — the server's `_parse_model_plan`
   already reads this field (lines 219–222), so no server-side parsing changes
   are needed.

### What's New

- `"claude-fable"` (Anthropic direct API model id) added to the `claude-code`
  backend's model list in the catalog.
- `research_primary_models` key in the `/api/config` `defaults.model_plan`
  payload.
- `research_primary` role in `catalog_payload()` → `"roles"`.
- UI picker (or datalist) for the ideation model in `dev.html`.

### What's Untouched (Non-Goals)

- The env-key `DEV_FLOW_IDEATION_MODEL` already works — no changes to env-key
  resolution.
- `model_plan.py` `DEFAULT_RESEARCH_PRIMARY` stays `"claude-opus-5"` — this is
  an exposure fix, not a default change.
- `IdeationNode` dispatch logic is not touched — it already accepts any non-empty
  string as the model id (free-text policy, `catalog.py:22-24`).
- The Bedrock cross-region ids (`global.anthropic.claude-fable-5`) in
  `catalog.py` line 342 are unrelated (nova/mantle path) — left as-is.
- Research-partner seat logic (the Anthropic family guard in
  `resolve_research_partner_backend`) is NOT affected — the guard applies to the
  partner, not the primary.
- `server.py` (ops console) is untouched — FEAT-486 did not wire a
  `research_primary` seat there, and this enhancement does not add one.

## Rationale

FEAT-486 / TASK-2656 made the ideation model configurable end-to-end (env key,
form field, flow wiring), but the UI surface for that knob was never completed:
the catalog omits the model from its curated list, the `/api/config` payload
does not include a selectable model list for the seat, and the UI likely does
not render a picker for it. This means an operator who wants to use Fable for
ideation must either set an env var before startup (a deployment-level change,
not a per-run choice) or craft a raw POST with the `research_primary` field
outside the browser UI — both are friction-heavy for a knob the system already
supports. The gap is a presentation bug, not a design gap.

## Impact

| Layer | File | Change |
|---|---|---|
| Catalog | `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py` | Add `"claude-fable"` (+ alias) to `claude-code` models; add `research_primary` role to `catalog_payload` |
| Server payload | `examples/dev_loop/server_dev.py` | Add `research_primary_models` to `_model_plan_payload` |
| UI | `examples/dev_loop/static/dev.html` | Add/complete ideation model picker |
| Tests | `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py` | Assert `research_primary_models` present in `/api/config` response; assert `"claude-fable"` in that list |

**Backward compatibility**: purely additive — new keys in the payload, new entry
in a model list. Clients that ignore unknown keys are unaffected.

**Risk**: minimal. The `claude` CLI's actual acceptance of `"claude-fable"` as
a `--model` flag should be verified before release; if the alias differs
(`claude-fable-5`), both ids can be included — the catalog's model lists are
never a whitelist.

## Code Context

- `packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py:62` —
  `DEFAULT_RESEARCH_PRIMARY = "claude-opus-5"`
- `packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py:85` —
  `ENV_RESEARCH_PRIMARY: str = "DEV_FLOW_IDEATION_MODEL"` — env key (already
  wired).
- `packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py:366-371` —
  `resolve_model_plan` reads `DEV_FLOW_IDEATION_MODEL` (already wired).
- `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py:383-385` —
  `_research_primary_model()`: uses `self._model` or falls back to
  `conf.DEV_FLOW_IDEATION_MODEL or "claude-opus-5"`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:231-247` —
  `claude-code` backend entry; `models` tuple is the target for the Fable
  addition.
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:507-541` —
  `catalog_payload()` — `roles` dict does not contain `research_primary`.
- `examples/dev_loop/server_dev.py:353-391` — `_model_plan_payload()` —
  returns `research_primary` as a string, missing the model list.
- `examples/dev_loop/server_dev.py:219-222` — `_parse_model_plan()` already
  reads `research_primary` from the form body — no server-side parsing changes
  needed.
- `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py` —
  existing test file for `/api/config` model plan surface (FEAT-486 TASK-2658).
- `packages/ai-parrot/tests/flows/dev_flow/test_ideation_model.py` —
  existing tests for configurable ideation model (FEAT-486 TASK-2656).
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:342` —
  `"global.anthropic.claude-fable-5"` already appears (Bedrock cross-region,
  unrelated to this change).

## Open Questions

- [ ] What is the exact Claude CLI model id string for Fable? (`"claude-fable"`,
  `"claude-fable-5"`, or another alias?) Verify against the `claude --help`
  model list or Anthropic model catalogue before finalising the catalog entry.
  — *Owner: user*
- [ ] Should Fable be the NEW default for the ideation seat, or remain a
  selectable alternative (keeping `claude-opus-5` as default)? — *Owner: user*
