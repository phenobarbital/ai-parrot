# TASK-3297: `test-optional-integrations` CI job + core-side skip guards + result gate

**Feature**: FEAT-562 — CI Test-Failure Root-Cause Remediation
**Spec**: `sdd/specs/ci-test-failures-root-cause-remediation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-3296
**Assigned-to**: unassigned

---

## Context

Implements Module 2 §2a–2c (environment contract, test-to-job mapping,
installation/execution design) — the largest module. Today `test-core` runs a
broad `uv run pytest tests/` after `uv sync --package ai-parrot`, and dozens of
files hard-fail collection because they import optional satellites
(`parrot.clients.*` from the 15 `ai-parrot-client-*` packages — FEAT-523 split
them out — plus `mcp`, `ai-parrot-integrations`, `ai-parrot-embeddings`,
`ai-parrot-server[scheduler]`, `ai-parrot-pipelines`). This task (a) guards
those files so bare `test-core` degrades to real skips, and (b) adds one new
`test-optional-integrations` job that installs those satellites and runs the
tests for real, gated by TASK-3296's structured result checker so a satellite
that was never really installed cannot hide behind a skip.

**Environment caveat (spec §2a):** `test-core`'s `uv run` is UNSCOPED and
auto-syncs the workspace-root project, so the historical logs do NOT prove
these satellites were absent. Establish the real inventory (installed
distributions + module origins under `artifacts/logs/`) BEFORE classifying any
failure; add a guard only for a confirmed-missing optional dependency, never to
mask a broken installed import.

---

## Scope

- Add `pytest.importorskip("<module>")` (or `pytest.mark.skipif(<probe> is
  None, ...)` where the seam has its own probe) at module scope of every file
  in the mapping table below, guarding ONLY the confirmed missing optional
  dependency — import the real target normally so broken installed code still
  fails. Mixed modules keep dependency-independent tests active (per-test /
  fixture guards, never a blanket module skip).
- Add a `test-optional-integrations` job to `.github/workflows/ci.yml` (Python
  3.12) that performs ONE combined `uv sync` of core + the 15 client packages +
  server[scheduler] + integrations + embeddings + pipelines + `ai-parrot[mcp]`,
  then runs each mapped selection and every provider-local suite via `uv run
  --no-sync pytest --junitxml=artifacts/logs/<selection>.xml`, then invokes
  `scripts/ci/check_ci_results.py` (TASK-3296) as the gate.
- Wire the same structured gate into the wiki/map required selections and make
  `lint-and-registry` execute `tests/scripts/test_generate_a2ui_css.py::
  test_generate_a2ui_css_vendor_check` with its dependencies.
- Author the coverage inventory JSON (TASK-3296's schema) recording exact node
  IDs, min-executed counts, and audited live/credential-gated deselections.

**NOT in scope**: the checker tool itself (TASK-3296); the 4 M8 handler/auth
files and `test_netsuite_mcp.py`'s netsuite source fix (TASK-3300 / TASK-3299
own those); `test_infographic_html.py` (TASK-3298); `test_store_migration_v2.py`
(TASK-3301). This task guards `test_netsuite_mcp.py` for the `mcp` dependency
only — its `token_store` signature fix is TASK-3299's.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/ci.yml` | MODIFY | Add `test-optional-integrations` job; wire gate into it + wiki/map jobs |
| `scripts/ci/optional_integrations_inventory.json` | CREATE | Coverage inventory (TASK-3296 schema) for the new job's selections |
| `tests/clients/test_bridged_hitl.py` | MODIFY | `importorskip("parrot.clients.anthropic")` |
| `tests/clients/test_google_fallback.py` | MODIFY | `importorskip("parrot.clients.google")` |
| `tests/clients/test_google_function_name_sanitization.py` | MODIFY | `importorskip("parrot.clients.google")` |
| `tests/clients/test_meta_client.py` | MODIFY | `importorskip("parrot.clients.meta")` |
| `tests/clients/test_meta_grounding.py` | MODIFY | `importorskip("parrot.clients.meta")` |
| `tests/clients/test_meta_models.py` | MODIFY | `importorskip("parrot.clients.meta")` |
| `tests/clients/test_meta_responses.py` | MODIFY | `importorskip("parrot.clients.meta")` |
| `tests/clients/test_meta_tool_search.py` | MODIFY | `importorskip("parrot.clients.meta")` |
| `tests/clients/test_moonshot_client.py` | MODIFY | `importorskip("parrot.clients.moonshot")` |
| `tests/clients/test_openai_base_parity.py` | MODIFY | `importorskip("parrot.clients.openai")` |
| `tests/clients/test_openai_fallback.py` | MODIFY | `importorskip("parrot.clients.openai")` |
| `tests/clients/test_openai_compatible_defaults.py` | MODIFY | guard per its actual import (openai/anthropic — verify) |
| `tests/clients/test_client_fallback.py` | MODIFY | guard per its actual import (openai — verify) |
| `tests/handlers/test_document_understanding_integration.py` | MODIFY | `importorskip("parrot.clients.google")` |
| `tests/integration/test_claude_agent_tool_bridge.py` | MODIFY | `importorskip("parrot.clients.anthropic")` |
| `tests/mcp/test_oauth2_e2e.py` | MODIFY | `importorskip("mcp")` |
| `tests/mcp/test_oauth2_integration.py` | MODIFY | `importorskip("mcp")` |
| `tests/mcp/test_oauth2_storage.py` | MODIFY | `importorskip("mcp")` |
| `tests/mcp/test_netsuite_mcp.py` | MODIFY | `importorskip("mcp")` (dependency guard ONLY — signature fix is TASK-3299) |
| `tests/auth/test_mcp_oauth2_provider.py` | MODIFY | `importorskip("mcp")` |
| `tests/integration/oauth2/conftest.py` | MODIFY | `importorskip("parrot.integrations.oauth2")` (dir-level) |
| `tests/unit/test_faiss_s3.py` | MODIFY | `importorskip("parrot.stores.faiss_store")` (embeddings satellite) |
| `tests/test_fireflies_wiki_agent.py` | MODIFY | `importorskip("apscheduler")` (server[scheduler]) |
| `tests/pipelines/test_endcap_no_shelves.py` | MODIFY | `importorskip("parrot_pipelines")` — do NOT mask the `IdentifiedProduct` validation error; diagnose it (see §2a step 4) |
| `tests/scripts/test_generate_a2ui_css.py` | MODIFY | guard/route the vendor-check case to `lint-and-registry` (folium/map) |
| `tests/knowledge/wiki/languages/test_outline_parity.py` | MODIFY | `skipif` on ast-grep availability, mirroring the Luau `get_parser(...) is None` pattern |
| `tests/knowledge/wiki/structural/test_tools.py` | MODIFY | same ast-grep guard |
| `tests/knowledge/wiki/test_cli_symbols.py` | MODIFY | same ast-grep guard |
| `tests/knowledge/wiki/test_structural_e2e.py` | MODIFY | same ast-grep guard |

> The list is a **minimum floor** (spec §7 Known Risks). Re-run a real
> `test-core` collection against a verified core-only profile and add any file
> sharing this shape; record exact node IDs in the inventory.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest  # pytest.importorskip / pytest.mark.skipif — the ONLY guard mechanisms allowed

# The 15 client satellites contribute these namespaces via PEP 420 (FEAT-523):
#   parrot.clients.{amazon,anthropic,gemma4,google,grok,groq,hf,local,meta,
#                   moonshot,nvidia,openai,openrouter,vllm,zai}
# verified present: packages/ai-parrot-client-*/src/parrot/clients/<name>/

# TASK-3296's gate, invoked from ci.yml:
#   python scripts/ci/check_ci_results.py --inventory <path> --reports-dir artifacts/logs
```

### Existing Signatures to Use
```yaml
# .github/workflows/ci.yml — existing patterns to mirror:
#   test-wiki-extras (lines ~140-241): single combined `uv sync --package
#     ai-parrot --extra wiki --extra wiki-languages --extra wiki-structural`
#     (line 179), then NavConfig scaffold, then pytest.
#   test-wiki-extras "Confirm no Luau/Roblox tests were skipped" (lines ~208-218):
#     the -v + `grep -q SKIPPED && exit 1` gate this task REPLACES with the
#     structured checker for its own selections.
#   test-loaders is the LAST job (ends ~line 461) — insert the new job after it.
#   ai-parrot[mcp] extra declares BOTH `mcp>=1.28.1,<2` AND
#     `google-api-python-client>=2.151.0` (verified: packages/ai-parrot/pyproject.toml:459-478).
```
```python
# Luau skip precedent to mirror for the ast-grep structural tests:
#   tests/knowledge/wiki/languages/test_luau.py — pytestmark =
#   pytest.mark.skipif(get_parser("luau") is None, ...)  (verified pattern, FEAT-532)
```

### Does NOT Exist
- ~~a working `grep "SKIPPED"` gate in quiet pytest output~~ — empirically
  false (spec §2d); use TASK-3296's checker.
- ~~`--extra bridge` on `ai-parrot-client-openai` in this job~~ — not
  requested, so `mcp` does NOT come from that satellite; it comes from
  `ai-parrot[mcp]` (verified: pyproject.toml:459).
- ~~a `faiss` extra that installs faiss-cpu~~ — `ai-parrot-embeddings`'s
  `faiss` extra is empty/name-only; `faiss-cpu` is already core
  (`packages/ai-parrot/pyproject.toml:162`). `test_faiss_s3.py` needs the
  `parrot.stores.faiss_store` module from `ai-parrot-embeddings`, not an extra.
- ~~successive `uv sync` calls accumulating packages~~ — `uv sync` is exact by
  default; use ONE combined sync then `uv run --no-sync` (spec §2c).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": ".github/workflows/ci.yml", "action": "MODIFY" },
    { "path": "scripts/ci/optional_integrations_inventory.json", "action": "CREATE" },
    { "path": "tests/clients/test_bridged_hitl.py", "action": "MODIFY" },
    { "path": "tests/clients/test_google_fallback.py", "action": "MODIFY" },
    { "path": "tests/clients/test_google_function_name_sanitization.py", "action": "MODIFY" },
    { "path": "tests/clients/test_meta_client.py", "action": "MODIFY" },
    { "path": "tests/clients/test_meta_grounding.py", "action": "MODIFY" },
    { "path": "tests/clients/test_meta_models.py", "action": "MODIFY" },
    { "path": "tests/clients/test_meta_responses.py", "action": "MODIFY" },
    { "path": "tests/clients/test_meta_tool_search.py", "action": "MODIFY" },
    { "path": "tests/clients/test_moonshot_client.py", "action": "MODIFY" },
    { "path": "tests/clients/test_openai_base_parity.py", "action": "MODIFY" },
    { "path": "tests/clients/test_openai_fallback.py", "action": "MODIFY" },
    { "path": "tests/clients/test_openai_compatible_defaults.py", "action": "MODIFY" },
    { "path": "tests/clients/test_client_fallback.py", "action": "MODIFY" },
    { "path": "tests/handlers/test_document_understanding_integration.py", "action": "MODIFY" },
    { "path": "tests/integration/test_claude_agent_tool_bridge.py", "action": "MODIFY" },
    { "path": "tests/mcp/test_oauth2_e2e.py", "action": "MODIFY" },
    { "path": "tests/mcp/test_oauth2_integration.py", "action": "MODIFY" },
    { "path": "tests/mcp/test_oauth2_storage.py", "action": "MODIFY" },
    { "path": "tests/mcp/test_netsuite_mcp.py", "action": "MODIFY" },
    { "path": "tests/auth/test_mcp_oauth2_provider.py", "action": "MODIFY" },
    { "path": "tests/integration/oauth2/conftest.py", "action": "MODIFY" },
    { "path": "tests/unit/test_faiss_s3.py", "action": "MODIFY" },
    { "path": "tests/test_fireflies_wiki_agent.py", "action": "MODIFY" },
    { "path": "tests/pipelines/test_endcap_no_shelves.py", "action": "MODIFY" },
    { "path": "tests/scripts/test_generate_a2ui_css.py", "action": "MODIFY" },
    { "path": "tests/knowledge/wiki/languages/test_outline_parity.py", "action": "MODIFY" },
    { "path": "tests/knowledge/wiki/structural/test_tools.py", "action": "MODIFY" },
    { "path": "tests/knowledge/wiki/test_cli_symbols.py", "action": "MODIFY" },
    { "path": "tests/knowledge/wiki/test_structural_e2e.py", "action": "MODIFY" }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- ONE combined `uv sync` per profile, then `uv run --no-sync` for every probe /
  collection / execution step (spec §2c; also `.claude/rules/
  worktree-management.md` §4 — shared envs are read/execute-only for worktree
  agents, so this job's multi-package sync can only be authored here and is
  proven in CI / a disposable env, not in the shared `.venv`).
- The combined multi-`--package`/`--extra` command was NOT dry-run at spec
  time. **Dry-run it in a disposable environment before merge** and adjust flag
  grouping if `uv` errors; never drop a required package to force resolution.
- Guard for the *missing dependency*, not arbitrary import errors. E.g.
  `pytest.importorskip("parrot.clients.google")` at module top, THEN the file's
  own `from parrot.clients.google import GoogleGenAIClient` runs normally so a
  broken installed client is still a failure.
- If piping pytest through `tee`, set `shell: bash` and `set -o pipefail` so
  the real exit status (including collection errors / zero-test exits) survives.
- Upload `artifacts/logs/*.xml` with `if: always()`.

### The external resolver blocker (spec §1 addendum)
The `navigator-session>=1.0.0` vs py3.13 resolver-unsat is a SEPARATE,
already-tracked blocker. A `uv sync` blocked by it means this job is
*unvalidated*, not passed — do not weaken the security dependency floor to make
CI executable. Record the resolver fix reference + passing sync logs before
marking acceptance.

---

## Implementation Blueprint

### Steps (in order)
1. Establish the verified core-only inventory (installed dists + module
   origins → `artifacts/logs/`) and reproduce each failure — *why*: §2a proves
   the historical logs don't establish absence; classify before guarding.
2. Add the module-scope guard to each mapped file (representative block below)
   — *why*: bare `test-core` must degrade to real skips, not `ERROR`.
3. Author `scripts/ci/optional_integrations_inventory.json` with one selection
   per provider suite + root selection, min-executed counts, and node-ID
   deselections for live/credential-gated cases — *why*: the gate needs
   required coverage to enforce.
4. Add the `test-optional-integrations` job (block below) and wire TASK-3296's
   checker as its gate; wire the same gate into wiki/map selections — *why*:
   §2c/§2d; installing a package is not coverage — the mapped tests must execute.

### `tests/clients/test_google_fallback.py` (MODIFY) — representative guard
```python
# occurrences: 1 (verified: grep -c 'from parrot.clients.google.client import' tests/clients/test_google_fallback.py)
# BEFORE — insert directly above `from parrot.clients.google.client import GoogleGenAIClient` (verified: test_google_fallback.py:2)
import pytest

pytest.importorskip("parrot.clients.google")
```
**Why**: makes bare `test-core` skip (not `ERROR`) this file when the
`ai-parrot-client-google` satellite is absent, while running it for real in the
new job. Apply the same shape to every row in Files to Modify, substituting the
module named in that row's Description. For a mixed module where only some tests
need the dependency, guard those tests/fixtures individually (do NOT
module-skip). For the wiki structural files, use the Luau `skipif(<probe> is
None, ...)` shape instead of `importorskip`.

### `.github/workflows/ci.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '  test-loaders:' .github/workflows/ci.yml)
# AFTER — append a new job below the `test-loaders:` job (the last job, ends ~line 461)
  test-optional-integrations:
    name: "Test optional integrations (LLM clients + scheduler + oauth2 + mcp + embeddings + pipelines)"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      - name: Sync core + every optional-integration satellite (ONE combined sync)
        run: |
          uv sync --package ai-parrot --extra mcp \
            --package ai-parrot-client-amazon --package ai-parrot-client-anthropic \
            --package ai-parrot-client-gemma4 --package ai-parrot-client-google \
            --package ai-parrot-client-grok --package ai-parrot-client-groq \
            --package ai-parrot-client-hf --package ai-parrot-client-local \
            --package ai-parrot-client-meta --package ai-parrot-client-moonshot \
            --package ai-parrot-client-nvidia --package ai-parrot-client-openai \
            --package ai-parrot-client-openrouter --package ai-parrot-client-vllm \
            --package ai-parrot-client-zai \
            --package ai-parrot-server --extra scheduler \
            --package ai-parrot-integrations \
            --package ai-parrot-embeddings \
            --package ai-parrot-pipelines
      - name: Scaffold NavConfig environment
        run: mkdir -p env/dev && touch env/dev/.env
      - name: Record installed inventory (evidence, §2a)
        run: |
          mkdir -p artifacts/logs
          uv run --no-sync python -m pip list --format=freeze > artifacts/logs/optint-inventory.txt
      - name: Run mapped selections (offline; JUnit XML per selection)
        shell: bash
        run: |
          set -o pipefail
          # FILL IN: one `uv run --no-sync pytest <selection> --junitxml=artifacts/logs/<id>.xml`
          # per inventory selection — the root selections AND each of the 15
          # packages/ai-parrot-client-*/tests/ suites. Deselect live/credential
          # cases by exact node id or audited marker. Bounded by §2b/§2c.
      - name: Structured coverage + skip gate (TASK-3296)
        run: |
          uv run --no-sync python scripts/ci/check_ci_results.py \
            --inventory scripts/ci/optional_integrations_inventory.json \
            --reports-dir artifacts/logs
      - name: Upload optional-integration logs
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: optional-integrations-logs
          path: artifacts/logs/
          retention-days: 14
          if-no-files-found: ignore
```
**Why**: implements §2b/§2c/§2d — one combined sync, `--no-sync` execution,
per-selection XML, and the structured gate replacing the broken grep. Do NOT
split the sync into successive `uv sync` calls (exact-sync would undo prior
selections). The `lint-and-registry` and wiki jobs get the same gate on their
mapped selections (FILL IN their steps similarly).

### FILL IN checklist
- [ ] Module-scope guard added to every file in "Files to Modify"; mixed modules use per-test/fixture guards — bounded by §2a step 5.
- [ ] `optional_integrations_inventory.json` — one selection per provider suite + root selections, min-executed ≥ 1, audited live deselections by node id — bounded by §2b/§2d.
- [ ] ci.yml "Run mapped selections" step — the concrete pytest+junitxml commands — bounded by §2b/§2c.
- [ ] `lint-and-registry` executes `test_generate_a2ui_css_vendor_check` with folium/map + the structured gate — bounded by §2b.
- [ ] Combined sync dry-run in a disposable env recorded (or blocked-by-resolver noted) — bounded by §5.

---

## Acceptance Criteria

- [ ] Bare `test-core` no longer `ERROR`s on any file in the mapping table —
      each degrades to a reported `SKIPPED`; installed-package import/behaviour
      failures remain visible.
- [ ] `test-optional-integrations` runs every mapped selection AND all 15
      provider-local suites with nonzero required execution and no unexpected
      skips; the structured gate (TASK-3296) is green.
- [ ] The coverage inventory accounts for every added guard, expected case,
      and audited live deselection; a missing report / module-level skip /
      missing required coverage fails the gate.
- [ ] `lint-and-registry` executes the map/vendor test with its dependencies
      and the structured gate.
- [ ] The combined profile sync is dry-run in a disposable environment (or the
      resolver blocker is recorded as the reason it cannot yet run); no new
      resolver conflict is introduced.
- [ ] `ruff check` clean on every modified test file.

---

## Test Specification

The deliverable is CI config + guards; its "tests" are the CI jobs themselves.
Locally, an implementer verifies each guarded file skips (not errors) under a
core-only interpreter and that TASK-3296's gate flags a selection that produced
only skips. Full multi-package execution is proven in CI (worktree agents
cannot install these satellites — `.claude/rules/worktree-management.md` §4).

---

## Agent Instructions

Standard SDD flow. **Depends on TASK-3296** (its checker must exist — confirm
`scripts/ci/check_ci_results.py` is present before wiring the gate step). Do NOT
edit the 4 M8 files or `test_infographic_html.py` / `test_store_migration_v2.py`
/ the netsuite source — other tasks own those. Guard `test_netsuite_mcp.py` for
`mcp` only.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
