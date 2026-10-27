# TASK-4766: PandasAgent CONFIGURE: default utterances + route-bank loading

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4759, TASK-4760
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (CONFIGURE half). Two edit sites in `bots/data.py`:

1. `DEFAULT_OUTPUT_MODE_ROUTES` (`:297`) gains the four composite routes with ≥8 EN and
   ≥8 ES utterances each — this is what makes *"show me total worked hours this month"*
   land on a KPI card, the NAV-10382 trigger case.
2. `PandasAgent.configure` (`:903`) calls `resolve_route_banks` before
   `configure_output_router`, so `routes.yaml` at agent and tenant level is merged over
   the code constant.

Split from TASK-4767 (the `ask()` seams) purely for size — both touch `data.py`, so
they are serialized by the file-overlap rule regardless.

**Threshold risk**: `output_mode_threshold=0.85` was calibrated for three
semantically distant routes. Four more, some close to `structured_chart`
("show me the total…" vs "chart the totals…"), may need a re-sweep — that is a
tracked open question in spec §8, not this task's job to resolve.

---

## Scope

- Add `a2ui:KPICard`, `a2ui:InfoCard`, `a2ui:Timeline`, `a2ui:Graph` to `DEFAULT_OUTPUT_MODE_ROUTES` with ≥8 EN + ≥8 ES utterances each.
- Call `resolve_route_banks` in `configure` and build the `IntentRouterConfig` from the result (including `tenant_output_mode_routes` and any threshold/margin overrides).
- Keep an explicitly supplied `output_routing_config` taking precedence.
- Add tests for the default bank and the configure wiring.

**NOT in scope**: The `ask()` seams — prompt addon, structured forcing, emitter call (all TASK-4767). Do not touch `data.py` below the `configure` method.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Default composite routes + route-bank loading at configure |
| `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` | MODIFY | Default-bank + configure tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.conf import AGENTS_DIR  # verified: parrot/conf.py:181 — NOT yet imported in data.py
from parrot.registry.routing.route_bank import resolve_route_banks  # verified: TASK-4759
from parrot.registry.capabilities.models import IntentRouterConfig  # verified: capabilities/models.py:149
```

### Existing Signatures to Use
```python
# parrot/bots/data.py:297
DEFAULT_OUTPUT_MODE_ROUTES: Dict[str, List[str]] = {
    # today: "structured_chart", "structured_table", "structured_map" — EN + ES
}

# parrot/bots/data.py:903 — inside PandasAgent.configure
            await asyncio.to_thread(self.configure_output_router, router_cfg)

# parrot/registry/routing/route_bank.py (TASK-4759)
def resolve_route_banks(agent_root: Optional[Path], *, defaults: Mapping[str, Sequence[str]],
                        tenant_based: bool) -> ResolvedRouteBanks: ...

# parrot/registry/capabilities/models.py (AFTER TASK-4759)
class IntentRouterConfig(BaseModel):
    enable_output_mode_routing: bool = False
    embedding_model: str = "intfloat/multilingual-e5-small"
    output_mode_routes: dict[str, list[str]]
    tenant_output_mode_routes: dict[str, dict[str, list[str]]]   # NEW
    output_mode_threshold: float = 0.85
    discrepancy_margin: float = 0.05
```

### Does NOT Exist
- ~~`PandasAgent._resolve_agents_dir()`~~ — **CONFIRMED NOT TO EXIST.** `grep -c '_resolve_agents_dir' packages/ai-parrot/src/parrot/bots/data.py` returns **0** — the spec's §3 M7 skeleton names a method that was never written. Do NOT call it. Use `AGENTS_DIR.joinpath(self.agent_id)`, the verified pattern at `bots/agent.py:506`. `AGENTS_DIR` is NOT currently imported in `data.py`, so add `from parrot.conf import AGENTS_DIR`.
- ~~`PandasAgent.tenant_based`~~ — verify with `getattr(self, "tenant_based", False)`; it is a FEAT-707 attribute that may not be set on every agent.
- ~~a `routes.yaml` shipped in the repo~~ — none exists; the default bank remains the code constant and the file is purely an operator override.
- ~~`OutputMode.KPICARD` or any new enum member~~ — G5 forbids it; the route key is the string `"a2ui:KPICard"`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/data.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_intent_router_component_routes.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/data.py#PandasAgent",
    "sym:packages/ai-parrot/src/parrot/bots/data.py#PandasAgent.configure",
    "sym:packages/ai-parrot/src/parrot/registry/routing/route_bank.py#resolve_route_banks",
    "sym:packages/ai-parrot/src/parrot/registry/capabilities/models.py#IntentRouterConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **≥8 EN and ≥8 ES utterances per new route** (an explicit acceptance criterion). Write natural phrasings a user would actually type, not templated variations of one sentence.
- **Keep the legacy routes' behaviour unchanged.** The existing chart/table/map test phrases must still resolve to the same modes — four new semantically-close routes are the main regression risk, so run the FEAT-224 integration test and treat a changed result as a failure, not a surprise.
- An explicitly supplied `output_routing_config` still wins — the bank resolution only applies when the caller did not pass one (today's branch at `:898-903`).
- `resolve_route_banks` never raises (TASK-4759 guarantees it), so no try/except is needed around it; do not add one that would mask a real bug.
- `configure_output_router` already runs under `asyncio.to_thread` — keep it there; bank resolution is file I/O and should go in the same thread hop.

### References in Codebase
- `parrot/bots/data.py:297` — the existing bank, including its EN/ES structure to copy.
- `parrot/bots/data.py:896-903` — the configure branch this extends.
- `parrot/bots/agent.py:506,522` — the `AGENTS_DIR.joinpath(self.agent_id, ...)` pattern to use for the agent root.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Use `AGENTS_DIR.joinpath(self.agent_id)` for the agent root — *why*: the spec's skeleton names `_resolve_agents_dir`, which does not exist; calling it would be an AttributeError at agent startup.
2. Add the four composite routes with EN+ES utterances — *why*: without them the router can never select a component.
3. Resolve banks in `configure` and build the config from the result — *why*: makes the bank data, per agent and per tenant.
4. Run the FEAT-224 integration test — *why*: the new routes sit close to `structured_chart` in embedding space and must not steal its phrases.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY — default bank)
```python
# occurrences: 1 (verified: grep -c 'DEFAULT_OUTPUT_MODE_ROUTES: Dict\[str, List\[str\]\] = {' packages/ai-parrot/src/parrot/bots/data.py)
# AFTER — add four keys inside the existing dict literal (verified: bots/data.py:297),
# matching the EN+ES structure the three existing routes already use:
    "a2ui:KPICard": [
        # FILL IN: >= 8 EN + >= 8 ES utterances. EN seeds: "show me total worked hours this month",
        #   "what is the total revenue", "give me the KPI for ...", "how many visits this week".
        #   ES seeds: "dame el KPI de ...", "cuantas horas trabajadas este mes",
        #   "cual es el total de ventas", "muestrame el indicador de ...".
        #   Phrase them as a user would TYPE them — bounded by AC-1
    ],
    "a2ui:InfoCard": [
        # FILL IN: >= 8 EN + >= 8 ES — summary/profile/"tell me about X" phrasings — bounded by AC-1
    ],
    "a2ui:Timeline": [
        # FILL IN: >= 8 EN + >= 8 ES — chronology phrasings ("timeline of the releases this
        #   quarter", "linea de tiempo de ...") — bounded by AC-1
    ],
    "a2ui:Graph": [
        # FILL IN: >= 8 EN + >= 8 ES — flow/dependency phrasings ("diagram the approval flow",
        #   "diagrama el flujo de ...") — bounded by AC-1
    ],
```
**Why**: these utterances ARE the feature's UX — the router is lexical/embedding-based, so coverage of real phrasings is what decides whether a KPI card ever appears. Keep them clearly distinct from the chart phrases ("show me the total X" vs "chart X over time") or the two routes will fight.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY — configure)
```python
# occurrences: 1 (verified: grep -c '            await asyncio.to_thread(self.configure_output_router, router_cfg)' packages/ai-parrot/src/parrot/bots/data.py)
# BEFORE — insert above `await asyncio.to_thread(self.configure_output_router, router_cfg)`
# (verified: bots/data.py:903)
# FILL IN: when routing is enabled AND no explicit output_routing_config was supplied:
#   1. agent_root = AGENTS_DIR.joinpath(self.agent_id)
#      (_resolve_agents_dir does NOT exist — 0 hits; see Does NOT Exist)
#   2. banks = resolve_route_banks(agent_root, defaults=DEFAULT_OUTPUT_MODE_ROUTES,
#                                  tenant_based=getattr(self, "tenant_based", False))
#   3. build router_cfg from banks.routes / banks.tenant_routes, applying any
#      threshold/margin overrides the banks carry
# An explicit output_routing_config still wins — do not overwrite it.
# — bounded by AC-2/AC-3
```
**Why**: resolution happens at CONFIGURE, once, because the banks are encoded into the router's vectors — doing it per request would re-encode the phrase bank on every turn.

### `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestConfigureValidation:' packages/ai-parrot/tests/bots/test_intent_router_component_routes.py)
# AFTER — append a new sibling class below the classes TASK-4760 created
# (this file is created by TASK-4760; this task extends it):
class TestDefaultBankAndConfigure:
    # FILL IN: all four composite keys present in DEFAULT_OUTPUT_MODE_ROUTES, every
    #          utterance non-empty, >= 8 EN and >= 8 ES each (count by a simple
    #          language heuristic or by splitting the list at a documented index);
    #          configure resolves banks and passes them to configure_output_router;
    #          an explicit output_routing_config is NOT overwritten
    #          — bounded by AC-1/AC-2/AC-3
```
**Why**: extending TASK-4760's module rather than creating another keeps all composite-routing assertions in one place.

### FILL IN checklist
- [ ] `data.py::DEFAULT_OUTPUT_MODE_ROUTES` — four routes × (≥8 EN + ≥8 ES) utterances; bounded by AC-1
- [ ] `data.py::PandasAgent.configure` — agent-root resolution + `resolve_route_banks` wiring; bounded by AC-2/AC-3
- [ ] `test_intent_router_component_routes.py::TestDefaultBankAndConfigure` — bank and configure assertions; bounded by AC-1..AC-3

---

## Acceptance Criteria

- [ ] **AC-1**: `DEFAULT_OUTPUT_MODE_ROUTES` contains `a2ui:KPICard`, `a2ui:InfoCard`, `a2ui:Timeline`, `a2ui:Graph`, each with ≥8 EN and ≥8 ES non-empty utterances.
- [ ] **AC-2**: `configure` calls `resolve_route_banks` with the agent root and `tenant_based`, and the resulting banks reach `configure_output_router` (including per-tenant banks).
- [ ] **AC-3**: an explicitly supplied `output_routing_config` still takes precedence and is not overwritten.
- [ ] **AC-4**: legacy routing is unchanged — `test_intent_router_output_mode_integration.py` passes and the existing chart/table/map phrases resolve to the same modes as before.
- [ ] The agent root comes from `AGENTS_DIR.joinpath(self.agent_id)` — `_resolve_agents_dir` is confirmed absent (0 hits) and must not be called.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_intent_router_component_routes.py -q`
- `pytest packages/ai-parrot/tests/bots/test_intent_router_output_mode_integration.py -q`
- `pytest packages/ai-parrot/tests/bots/test_intent_router_output_mode.py -q`

---

## Test Specification

Extend `packages/ai-parrot/tests/bots/test_intent_router_component_routes.py` (created by TASK-4760).

AC-4 is the one to take seriously: run
`packages/ai-parrot/tests/bots/test_intent_router_output_mode_integration.py` and confirm the existing
chart/table/map phrases still resolve to the same modes. Four new semantically-close
routes are exactly the kind of change that silently steals a phrase.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by codex/gpt-5.6-terra (attempt 1, 1170s)
**Date**: 2026-10-27
**Notes**: Default composite routes and route-bank loading at configure in bots/data.py, plus tests. Merge-tier validation green: 345 passed. Reviewed for file fidelity only (no line-level diff review). Closed via close_task.sh (no durable review EvidenceRef available for finalize_task).

**Deviations from spec**: none
