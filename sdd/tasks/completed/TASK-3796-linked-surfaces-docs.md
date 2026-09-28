# TASK-3796: Docs — wire doc, a2ui-v1 extension table, dashboard reference §6.5/§7.4, toolkit

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3785, TASK-3787, TASK-3788, TASK-3795, TASK-3776, TASK-3789, TASK-3805
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 and **AC13**, verbatim:

> AC13 Docs updated: `docs/outputs/a2ui-v1.md` extension table (`parrot_data_sources`, `parrot_param`), `docs/frontend/agentdashboard-a2ui-reference.md` §6.5 + §7.4 (Filter vs Refresh vs Reload), `docs/tools/querysource-toolkit.md` (new tool, `tenant`), new `docs/outputs/a2ui-linked-surfaces.md` stating that `locked` is not security, that server lanes run as a trusted service behind a mandatory guard, and that `ref` module CSP is the host page's responsibility.

Docs are written LAST so they describe what was built: the tool (TASK-3785), the server lanes
(TASK-3787/TASK-3788), the bundled UI lane (TASK-3795), the transforms publisher (TASK-3776) and FilterBar
`parrot_param` (TASK-3789). Where an implementation deviated from the spec (read those tasks'
Completion Notes), the docs follow the code and the deviation is noted.

---

## Scope

- New `docs/outputs/a2ui-linked-surfaces.md` (the wire doc for renderer teams).
- `docs/outputs/a2ui-v1.md`: extension-table rows for `parrot_data_sources` (surface-level) and `parrot_param` (FilterBar filter / lowered ChoicePicker).
- `docs/frontend/agentdashboard-a2ui-reference.md`: new §6.5 "Linked surfaces" + TOC; §7.4 amended with the Filter vs Refresh vs Reload distinction.
- `docs/tools/querysource-toolkit.md`: `qs_build_linked_surface` + the `tenant` argument on list/describe/execute; fix the tool count sentence.
- `packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py`: asserts the AC13 statements exist.

**NOT in scope**: any code change; regenerating the JSON Schema (link to `contract/schema.json`, TASK-3771).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/a2ui-linked-surfaces.md` | CREATE | linked-surface wire + trust-model doc |
| `docs/outputs/a2ui-v1.md` | MODIFY | extension table rows |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | TOC, §6.5, §7.4 |
| `docs/tools/querysource-toolkit.md` | MODIFY | new tool + `tenant` |
| `packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py` | CREATE | AC13 presence test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path   # stdlib only; the test reads markdown files
# repo root from packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py = Path(__file__).resolve().parents[5]
```

### Existing Signatures to Use
```text
docs/outputs/a2ui-v1.md
  L145-156  metadata.extensions paragraph + "| Key | Meaning |" table; last row (L156):
            | `parrot_unit`, `parrot_trend`, `parrot_series_data`, ... | Component-specific presentation hints (KPICard's unit/trend, a lowered Chart series' original binding, ...) |
  L349      prose mention of `parrot_series_data` (NOT the anchor)
docs/frontend/agentdashboard-a2ui-reference.md
  L22-35    Table of contents; L29 `6. [Dashboards, infographics and widgets](#6-dashboards-infographics-and-widgets)` (numbered list, no sub-entries)
  L710      ## 6. Dashboards, infographics and widgets; §6.1 L712 … §6.4 L749 `### 6.4 FlexDashboard specifics (FEAT-491)`
  L777      ## 7. The interactive HTML lane (FEAT-493)  — §6.5 goes immediately BEFORE this heading (after the `---` separator that precedes it)
  L805      ### 7.4 Client-side filtering contract (FilterBar, TASK-2716); items 1-8, item 8 starts `8. On non-interactive surfaces (SSR, PDF)`
            item 1 already says: "Filter" is instant and local, "Refresh" re-runs the recipe
docs/tools/querysource-toolkit.md
  L33       ## Tools ; L35-37 "Seven tools are always present; the eighth (`qs_save_multiquery`) appears only when … allow_write=True"
  last tool bullet ends: `  program; set \`overwrite=True\` to update your own.`   then blank line, then `## Tenancy semantics`
```

### Does NOT Exist
- ~~`docs/outputs/a2ui-linked-surfaces.md`~~ — created here.
- ~~`docs/outputs/schemas/`~~ — the published schema lives at `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/schema.json` (package data, S7); link there.
- ~~a TypeScript package for third-party renderers~~ — never (G1): the contract is schema + fixtures.
- ~~`/api/v3/{tenant}/queries/{slug}`~~ — tenant route is `/api/v1/{tenant}/queries/{slug}`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/outputs/a2ui-linked-surfaces.md", "action": "CREATE"},
    {"path": "docs/outputs/a2ui-v1.md", "action": "MODIFY"},
    {"path": "docs/frontend/agentdashboard-a2ui-reference.md", "action": "MODIFY"},
    {"path": "docs/tools/querysource-toolkit.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Mandatory content of `docs/outputs/a2ui-linked-surfaces.md` (from spec §2, §7 risks, AC13)
1. What a linked surface is (component + presentation props, descriptor, optional transform, optional snapshot) and G9 (baked renderers are unaffected; a snapshot makes it indistinguishable from baked).
2. Wire: `createSurface.metadata.extensions.parrot_data_sources` keyed by `dataModel` root key; field table from spec §2 Data Models; `conditions` is a derived cache of `request` (S5); link to `contract/schema.json` and `contract/fixtures/` (the executor contract — G1).
3. Fetch path: renderer → QuerySource with the viewer's JWT (`POST /api/v3/queries/{slug}` | `POST /api/v1/{tenant}/queries/{slug}`), `refresh` boolean `true` only, `querylimit`, every denial is 404 → "unavailable".
4. Refresh policy (`on_mount` / `manual` / `interval` ≥ 30 s, paused while hidden), snapshot rules (≤ 500 rows, `snapshot_truncated`, mandatory once persisted, `GET` never executes, loading state while `snapshot_at` is null — AC16).
5. DSL v1 (ten ops, spec §7 semantics) and `transform.ref` (opaque `name@version`, manifest + SRI, `deprecated` never deleted).
6. **Security statements (AC13, exact phrases the test asserts)**:
   - "`locked` is not security" — it is a UX hint; security is QuerySource PBAC + slug design. Tenant is routing, not security.
   - "server lanes run as a trusted service behind a mandatory guard" — `LinkedSurfaceService` fails closed without a guard (`LinkedGuardRequired` → 403); owner `principal=` is defense in depth (PBAC can no-op when QuerySource's bootstrap is absent). Document the default wiring (TASK-3805): `BotManager.setup` (`packages/ai-parrot-server/src/parrot/manager/manager.py`) builds `app["dataplane_guard"]` / injects `bot._dataplane_guard` via `setup_dataplane_guard()` (`packages/ai-parrot/src/parrot/auth/pbac.py`) when PBAC initializes (navigator-auth + `PARROT_PBAC_POLICY_DIR`); otherwise linked saves answer 403 until an operator configures PBAC. Owner-check resource naming (confirmed 2026-09-26): `source:read` on `query_slug:<tenant|public>:<slug>`.
   - "`ref` module CSP is the host page's responsibility" — SRI authenticates bytes, not behaviour.
7. Share-token viewers: last snapshot + "data as of `snapshot_at`" + server-side refresh button.

### Key Constraints
- Match the surrounding doc style (tables, backticked identifiers, spec/FEAT references).
- Every endpoint/field name must be copied from the implemented code (read TASK-3785/TASK-3787/TASK-3788/TASK-3795 diffs), not from memory.

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged implementations and the Completion Notes of TASK-3785, TASK-3787, TASK-3788, TASK-3795, TASK-3776, TASK-3789 — *why*: docs describe what shipped.
2. Write `docs/outputs/a2ui-linked-surfaces.md` — *why*: the other three docs link to it.
3. Apply the three MODIFY blocks — *why*: AC13 names each location.
4. Write the test; run `pytest packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py -q`.

### `docs/outputs/a2ui-linked-surfaces.md` (CREATE)
```markdown
# A2UI Linked Surfaces (FEAT-598)

> Surfaces that carry **how to fetch their rows**, not only the rows.

## 1. What a linked surface is
<!-- FILL IN: item 1 of "Mandatory content" -->

## 2. Wire format — `metadata.extensions.parrot_data_sources`
<!-- FILL IN: item 2 (field table; S5; links to packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/{schema.json,fixtures/}) -->

## 3. Fetch path and errors
<!-- FILL IN: item 3 -->

## 4. Refresh policy and snapshots
<!-- FILL IN: item 4 -->

## 5. Transforms — DSL v1 and `transform.ref`
<!-- FILL IN: item 5 -->

## 6. Trust model
- `locked` is not security: …
- Tenant is routing, not security: …
- Server lanes run as a trusted service behind a mandatory guard: …
- `ref` module CSP is the host page's responsibility: …
<!-- FILL IN: complete each bullet from spec §7 Known Risks — keep the four lead phrases verbatim (the test asserts them) -->

## 7. Share-token viewers
<!-- FILL IN: item 7 -->
```

### `docs/outputs/a2ui-v1.md` (MODIFY)
```markdown
<!-- occurrences: 2 for `parrot_series_data` (L156 table row, L349 prose) → use the full unique row:
     occurrences: 1 (verified: grep -cF '| `parrot_unit`, `parrot_trend`, `parrot_series_data`, ... |' docs/outputs/a2ui-v1.md) -->
<!-- AFTER that row (verified: docs/outputs/a2ui-v1.md:156) insert: -->
| `parrot_data_sources` | **Surface-level** (`createSurface.metadata.extensions`, FEAT-598): linked data-source descriptors keyed by `dataModel` root key — see [a2ui-linked-surfaces.md](a2ui-linked-surfaces.md). TOOL-origin only (`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`) |
| `parrot_param` | On a `FilterBar` filter / its lowered `ChoicePicker` (FEAT-598): `{"source": "<key>", "name": "<param>"}` — changing the filter re-fetches that source instead of filtering locally |
```

### `docs/frontend/agentdashboard-a2ui-reference.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '## 7. The interactive HTML lane (FEAT-493)' docs/frontend/agentdashboard-a2ui-reference.md) -->
<!-- BEFORE `## 7. The interactive HTML lane (FEAT-493)` (L777; keep the `---` separator above §7) insert: -->
### 6.5 Linked surfaces (FEAT-598)

<!-- FILL IN: how a linked envelope is recognised (metadata.extensions.parrot_data_sources), the renderer lane (fetch with viewer JWT, DSL, scheduler, ref loader),
     loading / "unavailable" / "data as of" states, and a link to ../outputs/a2ui-linked-surfaces.md — bounded by what TASK-3795 shipped -->

<!-- occurrences: 1 (verified: grep -cF '8. On non-interactive surfaces (SSR, PDF)' docs/frontend/agentdashboard-a2ui-reference.md) -->
<!-- AFTER item 8 of §7.4 (the line starting `8. On non-interactive surfaces (SSR, PDF)`, L~818) insert: -->
9. **Filter vs Refresh vs Reload (FEAT-598)**: *Filter* is local over embedded rows (items 1-8); a filter carrying `parrot_param` is a **Reload** — it re-fetches its linked source from QuerySource with the new param (§6.5); *Refresh* re-runs the server lane (`POST …/ui/surfaces/{id}/refresh` — recipe or descriptor).
```
**Why**: AC13 names §6.5 and §7.4 explicitly; §7.4 item 1 already defines Filter vs Refresh, so Reload is appended rather than rewriting it. The TOC lists only top-level sections — no TOC edit needed (confirm; the TOC at L22-35 has no `6.x` entries).

### `docs/tools/querysource-toolkit.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '  program; set `overwrite=True` to update your own.' docs/tools/querysource-toolkit.md) -->
<!-- AFTER the last line of the `qs_save_multiquery` bullet (above `## Tenancy semantics`) insert: -->
- **`qs_build_linked_surface`** — (FEAT-598) Emits a linked A2UI surface for a query-slug: checks the slug
  (and `tenant`) against the allowlist, derives `params` from `qs_describe_slug`, builds `conditions` (forced
  keys become `locked`; `@variables` are rejected), **executes the slug once** to validate the component's
  axes/columns against the real columns, and embeds ≤ 500 rows only when `snapshot=True`. Returns
  `{a2ui_envelope, artifacts}`. See [A2UI linked surfaces](../outputs/a2ui-linked-surfaces.md).
<!-- FILL IN: also (a) fix the "Seven tools are always present" sentence (L35, occurrences: 1) to the new count; (b) document the optional `tenant` argument on
     qs_list_slugs / qs_describe_slug / qs_execute_slug and `required` / `accepts_keywords` in describe output — bounded by TASK-3784/TASK-3785 as shipped -->
```

### `packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py` (CREATE)
```python
"""FEAT-598 (TASK-3796): AC13 — the linked-surface docs exist and state the required facts."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
DOCS = REPO_ROOT / "docs"


def _read(rel: str) -> str:
    """Return a docs file's text, failing clearly when it is missing."""
    path = DOCS / rel
    assert path.is_file(), f"missing doc: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "phrase",
    [
        "`locked` is not security",
        "trusted service behind a mandatory guard",
        "CSP is the host page's responsibility",
        "parrot_data_sources",
    ],
)
def test_linked_surfaces_doc_states(phrase: str) -> None:
    """The wire doc carries the AC13 trust-model statements."""
    assert phrase in _read("outputs/a2ui-linked-surfaces.md")


def test_a2ui_v1_extension_table() -> None:
    """a2ui-v1.md lists both new extension keys."""
    text = _read("outputs/a2ui-v1.md")
    assert "| `parrot_data_sources` |" in text
    assert "| `parrot_param` |" in text


# FILL IN: agentdashboard reference has "### 6.5" and the §7.4 Reload item; querysource-toolkit.md mentions
#          `qs_build_linked_surface` and `tenant` — bounded by AC13
```

### FILL IN checklist
- [ ] `a2ui-linked-surfaces.md` sections 1-7; bounded by "Mandatory content" + shipped code.
- [ ] dashboard reference §6.5 body; bounded by TASK-3795.
- [ ] toolkit doc tool-count sentence + `tenant` args; bounded by TASK-3784/TASK-3785.
- [ ] remaining test cases; bounded by AC13.

---

## Acceptance Criteria

- [ ] AC13 satisfied at all four locations.
- [ ] The three trust-model phrases appear verbatim in `docs/outputs/a2ui-linked-surfaces.md`.
- [ ] No doc references a non-existent endpoint, field or file (cross-checked against the code).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/test_linked_docs.py -q`

---

## Test Specification

See the `test_linked_docs.py` block above.

---

## Agent Instructions

1. **Read the spec** (§2, §7 Known Risks, AC13) and the dependency tasks' Completion Notes.
2. **Check dependencies** — TASK-3785, TASK-3787, TASK-3788, TASK-3795, TASK-3776, TASK-3789 done.
3. **Verify the anchors** (re-run the grep counts above).
4. **Update status** → `"in-progress"`; write; run the test.
5. Move to `sdd/tasks/completed/`; index → `"done"`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (nova seat qwen.qwen3-coder-480b-a35b-instruct), execution b99e4988-4438-4226-a71a-362798fa8ca2
**Date**: 2026-09-26
**Notes**: Implementation commit `2ff066692`. `docs/outputs/a2ui-linked-surfaces.md` written per the task's
declared anchors and trust-model phrases; `test_linked_docs.py` (TASK-3792's cross-check test) confirmed
green: `8 passed`. This is the LAST task of FEAT-598 — all 28 tasks are now complete.
`coder_record_feedback`/`coder_record_review` (MCP) were unavailable for this entire run (object-param tool
outage) — feedback/review metrics **NOT recorded**.

**Deviations from spec**: none.
