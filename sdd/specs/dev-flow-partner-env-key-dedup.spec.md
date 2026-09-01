---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Collapse the duplicate research-partner env keys

**Feature ID**: FEAT-487
**Date**: 2026-09-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.29.0
**Origin**: FEAT-486 TASK-2657 Completion Note ("Open follow-up")

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-flow research-partner seat is now configurable through **two
competing sets of environment keys**, because FEAT-482 and FEAT-486 were
developed in parallel and each invented its own:

| Owner | Keys | Semantics |
|---|---|---|
| **FEAT-482** (shipped, authoritative) | `DEV_FLOW_RESEARCH_PARTNER` | `""` = disabled, `"gpt"`, `"nova"` — enable flag AND backend in one key |
| | `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL` | model, per backend (`gpt-5.6-sol`) |
| | `DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL` | model, per backend (`us.amazon.nova-2-lite-v1:0`) |
| **FEAT-486** (invented, redundant) | `DEV_FLOW_RESEARCH_PARTNER_ENABLED` | separate boolean (`model_plan.py:81`) |
| | `DEV_FLOW_RESEARCH_PARTNER_BACKEND` | separate backend (`model_plan.py:82`) |
| | `DEV_FLOW_RESEARCH_PARTNER_MODEL` | single model, backend-agnostic (`model_plan.py:83`) |

FEAT-486's keys were written before FEAT-482 merged, against a *predicted*
API (see FEAT-486 TASK-2657's contract-corrections table). They are read
only by `resolve_model_plan()` (`model_plan.py:341,346,352`), and FEAT-482's
are read by `resolve_research_partner_backend()`
(`dev_loop/catalog.py:157`) and `resolve_backend_model()`
(`dev_flow/research_partner.py:171`).

Concrete harm:

- **Two ways to say the same thing, with different shapes.** An operator
  who sets `DEV_FLOW_RESEARCH_PARTNER=nova` (FEAT-482's documented key)
  does NOT enable the seat through a `DevFlowModelPlan`, because the plan
  reads `_ENABLED`/`_BACKEND` instead — and vice versa.
- **A backend-agnostic model key cannot express FEAT-482's model space.**
  FEAT-486's single `_MODEL` has no per-backend dimension, so it silently
  cannot represent "gpt→X, nova→Y".
- **The docs are now wrong in three places** — `docs/dev_loop/dev-flow-model-plan.md`,
  `examples/dev_loop/README.md`, `examples/dev_loop/GUIA.md` all publish
  FEAT-486's key names as the way to configure this seat.

### Goals

- **G1** — One key set for the research-partner seat: FEAT-482's, since it
  shipped first, is referenced by its own spec/docs, and carries the
  per-backend model dimension.
- **G2** — `DevFlowModelPlan.research_partner` keeps its current *field*
  shape (`enabled`/`backend`/`model`) — it is a plan object, not an env
  mirror, and `factories._resolve_research_coordinator()` plus the console
  payload already depend on those field names. Only where the resolver
  reads its **defaults from config** changes.
- **G3** — Explicit-argument precedence is unchanged: an explicit plan
  value still beats config, which still beats the built-in default.
- **G4** — Docs corrected wherever the retired keys appear.
- **G5** — No behaviour change for a deployment that configures nothing.

### Non-Goals

- Changing FEAT-482's keys, resolver or coordinator in any way.
- Changing `ResearchPartnerPlan`'s field names or the console payload shape.
- Adding a per-backend model dimension to the plan object (the plan's single
  `model` applies to whichever backend the plan selects — that is
  sufficient, since a plan names exactly one backend).
- Touching any other seat group (`research_primary`, `dev_pool`, `review`).

---

## 2. Architectural Design

Retire the three FEAT-486 key constants and repoint
`resolve_model_plan()`'s partner block at FEAT-482's keys:

```
research_partner.enabled  <- bool(DEV_FLOW_RESEARCH_PARTNER != "")
research_partner.backend  <- DEV_FLOW_RESEARCH_PARTNER or "gpt"
research_partner.model    <- DEV_FLOW_RESEARCH_PARTNER_{GPT,NOVA}_MODEL,
                             chosen by the resolved backend
```

`enabled` and `backend` collapsing onto one source is the point: FEAT-482
deliberately encodes both in a single key (`""` = disabled), and mirroring
that removes the possibility of the two disagreeing.

The model default becomes **backend-dependent**, which is what makes the
plan's default correct for a `nova` partner — today an unset plan on a
`nova` backend still defaults `model` to `gpt-5.6-sol`, a latent
mismatch that only avoids being a bug because `_resolve_research_coordinator`
passes `model or None` and FEAT-482 then re-resolves per backend.

### Integration Points

| Component | Type | Note |
|---|---|---|
| `resolve_model_plan()` (`model_plan.py:330-360`) | modifies | partner block reads FEAT-482's keys |
| `ENV_PARTNER_*` constants (`model_plan.py:81-83`) | removes | no external importer outside `test_model_plan.py` |
| `catalog.resolve_research_partner_backend()` | reuses | may be called with the same injectable `config_getter`, keeping one parse of `DEV_FLOW_RESEARCH_PARTNER` |
| `factories._resolve_research_coordinator()` (`factories.py:52`) | unchanged | consumes plan *fields*, not keys |
| console `/api/config` + `_parse_model_plan` | unchanged | payload shape is field-based |

---

## 3. Module Breakdown

### Module 1: Resolver repoint + docs
- **Path**: `dev_flow/model_plan.py`, `tests/flows/dev_flow/test_model_plan.py`,
  `docs/dev_loop/dev-flow-model-plan.md`, `examples/dev_loop/README.md`,
  `examples/dev_loop/GUIA.md`
- **Responsibility**: everything above. Single task — the change is one
  cohesive edit and splitting it would leave the tree inconsistent.

---

## 4. Test Specification

| Test | Description |
|---|---|
| `test_partner_enabled_from_feat482_key` | `DEV_FLOW_RESEARCH_PARTNER=gpt` ⇒ `enabled=True`, `backend="gpt"` |
| `test_partner_disabled_when_key_unset` | unset ⇒ `enabled=False` (pure-addition guarantee) |
| `test_partner_model_follows_backend` | `=nova` ⇒ model from `_NOVA_MODEL`; `=gpt` ⇒ from `_GPT_MODEL` |
| `test_explicit_plan_still_beats_config` | explicit `ResearchPartnerPlan(...)` unchanged by config |
| `test_retired_keys_are_ignored` | `DEV_FLOW_RESEARCH_PARTNER_ENABLED=1` alone does NOT enable the seat |
| `test_invalid_backend_surfaces_feat482_error` | `=bogus` raises naming `gpt, nova` |

---

## 5. Acceptance Criteria

- [ ] `ENV_PARTNER_ENABLED` / `_BACKEND` / `_MODEL` are gone from `model_plan.py`
- [ ] `resolve_model_plan()` derives the partner group from
  `DEV_FLOW_RESEARCH_PARTNER` + `_GPT_MODEL`/`_NOVA_MODEL`
- [ ] `ResearchPartnerPlan` field names and the console payload are unchanged
- [ ] Explicit plan values still beat config (precedence test)
- [ ] Unconfigured deployment behaves identically (partner disabled)
- [ ] `grep -rn DEV_FLOW_RESEARCH_PARTNER_ENABLED` returns nothing outside history
- [ ] The three docs publish only FEAT-482's key names
- [ ] Full `packages/ai-parrot/tests/flows/dev_flow/` green; `ruff check` clean

---

## 6. Codebase Contract

> Verified against `dev` at `95957471a` (post-FEAT-486 merge), 2026-09-01.

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py
DEFAULT_PARTNER_BACKEND: str = "gpt"                  # :66  (KEEP)
DEFAULT_PARTNER_MODEL: str = "gpt-5.6-sol"            # :67  (KEEP as gpt fallback)
ENV_PARTNER_ENABLED = "DEV_FLOW_RESEARCH_PARTNER_ENABLED"   # :81 (REMOVE)
ENV_PARTNER_BACKEND = "DEV_FLOW_RESEARCH_PARTNER_BACKEND"   # :82 (REMOVE)
ENV_PARTNER_MODEL   = "DEV_FLOW_RESEARCH_PARTNER_MODEL"     # :83 (REMOVE)
class ResearchPartnerPlan(BaseModel):                 # :109 — fields UNCHANGED
def resolve_model_plan(plan=None, *, config_getter=None) -> DevFlowModelPlan
#   partner block at :335-353 — the only reader of the three constants

# packages/ai-parrot/src/parrot/conf.py — FEAT-482's shipped keys (authoritative)
DEV_FLOW_RESEARCH_PARTNER            = config.get(..., fallback="")        # :1131
DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL  = config.get(..., "gpt-5.6-sol")      # :1137
DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL = config.get(..., "us.amazon.nova-2-lite-v1:0")  # :1141

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
def resolve_research_partner_backend(config_getter=None) -> str  # :157
#   "" | "gpt" | "nova"; ALSO validates the resolved model against the
#   Anthropic family guard, and raises ValueError naming (gpt, nova).

# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py
def _resolve_research_coordinator(explicit, plan)      # :52 — consumes plan
#   FIELDS only; requires NO change.
```

### Does NOT Exist
- Any importer of `ENV_PARTNER_*` outside `model_plan.py` and
  `tests/flows/dev_flow/test_model_plan.py` (verified by grep).
- A per-backend model field on `ResearchPartnerPlan` — deliberately not added.

---

## 7. Implementation Notes & Constraints

- Prefer calling `resolve_research_partner_backend(config_getter)` over
  re-parsing `DEV_FLOW_RESEARCH_PARTNER` locally, so the enable/backend
  semantics AND the Anthropic family guard stay in one place. Note it
  RAISES on an invalid value — `resolve_model_plan` currently raises on a
  bad `dev_pool` backend too, so that is consistent.
- `resolve_model_plan` reads config through an injectable `config_getter`
  (tests pass a dict-backed lambda); keep that, and pass it through.
- The model default must be chosen AFTER the backend is known.

---

## 8. Open Questions

- [x] Which key set wins? — *Resolved*: FEAT-482's. It shipped first, owns
  the seat's implementation, and carries the per-backend model dimension.
- [x] Should `ResearchPartnerPlan` gain per-backend model fields? — *Resolved*:
  no. A plan names exactly one backend, so one `model` is sufficient.
- [ ] Should the retired keys emit a deprecation warning for one release
  instead of vanishing? They shipped only in FEAT-486 (same day, unreleased),
  so almost certainly not — confirm at implementation time.

---

## Worktree Strategy

- **Isolation unit**: single task, single worktree
  (`.claude/worktrees/feat-487-dev-flow-partner-env-key-dedup`, from `dev`).
- **Cross-feature dependencies**: none — FEAT-482 and FEAT-486 are both
  merged to `dev` (`95957471a`). **This spec exists precisely because
  FEAT-486 was decomposed before FEAT-482 merged**; do not repeat that —
  branch from a `dev` that already contains both.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | Jesus Lara (with Claude) | Initial — carved out of FEAT-486 TASK-2657's open follow-up |
