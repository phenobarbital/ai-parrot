# TASK-2075: `wikitoolkit ingest` CLI command + end-to-end integration

**Feature**: FEAT-402 — Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)
**Spec**: `sdd/specs/supervised-wiki-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2074
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec (§3) — the user-facing surface that
wires charter, triage, manifest, and the apply pipeline into one command.
`wiki/cli.py` is a HOT file (2062 lines, 8+ commits in 3 weeks): keep the
diff to ONE additive command block + imports; ALL logic lives in the new
modules. Rebase on `dev` before starting.

---

## Scope

- Add `wikitoolkit ingest <folder>` to `wiki/cli.py`:
  - Flags: `--charter <path>` (falls back to `WikiConfig.charter_path`),
    mutually-exclusive modes `--dry-run` / `--review <manifest.jsonl>` /
    `--interactive` / `--auto`, and `--extract` (experimental, off by
    default — includes extracted claims in the manifest; document as
    experimental in help text).
  - `--dry-run`: triage all docs, emit manifest (decisions null), ingest
    NOTHING, print a rich summary table (admit/gray/reject counts).
  - `--review`: read edited manifest, validate, run the async apply
    pipeline (admit → orchestrator with hint; archive → ARCHIVE category;
    discard → record only). Idempotent on re-run.
  - `--interactive`: questionary per-doc prompt (show briefing, scores,
    proposed action; accept/override) — ALL prompting completes BEFORE
    the async apply pipeline starts (questionary is blocking).
  - `--auto`: thresholds decide; stratified audit sample flagged
    (charter fractions); print audit-sample summary + `agreement_rate`
    placeholder note for post-hoc review.
  - Human decisions (interactive/review) append to the charter
    `examples_file`; every run logs `TRIAGE` ops; run header carries
    charter sha256/version + novelty backend.
- Integration tests (spec §4):
  - `test_supervised_ingest_end_to_end` — folder → dry-run → simulated
    edits → review apply → pages/categories/bookkeeper assertions.
  - `test_build_unaffected` — `build` output identical with FEAT-402
    code present.
- Extend `tests/knowledge/wiki/test_cli.py` (CliRunner-based, stub LLM).

**NOT in scope**: any change to `build`/`upsert`/`repo_scan` (hard
non-goal), new logic in cli.py beyond argument handling + orchestration
calls, charter autotune apply.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | ONE additive `ingest` command block + imports |
| `tests/knowledge/wiki/test_cli.py` | MODIFY | CLI tests for all four modes |
| `tests/knowledge/wiki/test_integration.py` | MODIFY | end-to-end + build-unaffected tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ad6365242` (2026-08-02). cli.py drifts fast —
> re-anchor ALL line numbers before editing.

### Verified Imports
```python
import click                                              # >=8.1.7, core dep
from parrot.knowledge.wiki.charter import load_charter    # TASK-2069
from parrot.knowledge.wiki.review import ManifestReader, ManifestWriter, stratified_sample  # TASK-2070
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer  # TASK-2071
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
# rich>=13.0 and questionary>=2.1.1 are core deps (pyproject:80,101) — no new deps allowed
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (2062 lines @ ad6365242)
# @click.group(name="wiki")                    lines 685-686
# def main() -> None:                          line 2028
# shared --path decorator: path_option         lines 71-73
# build: decorators 695-722, function 723-847  — MUST remain untouched
# async def _ingest_files(...)                 316-378 — build's helper; do NOT reuse for supervised path
# Existing @wiki.command inventory (NO "ingest" — the name is free):
#   build 695, upsert 886, query 1005, page 1090, related 1133, status 1171,
#   communities 1221, export 1323, remember 1577, note 1732, link 1796,
#   memories 1847, audit 1884, ground 1943, claude-hook(hidden) 2013,
#   codex/claude/gemini dynamic 2046-2062
# ground command (1947-2011) — reference for constructing the grounding stack
#   and for how CLI commands run async code (asyncio.run pattern used in this file)
```

### Does NOT Exist
- ~~`wikitoolkit ingest`~~ — you are adding it; verified free in the full command inventory above.
- ~~a shared "supervised" flag on `build`~~ — explicitly rejected in the spec (§1 Non-Goals); do not add flags to `build`.
- ~~async questionary~~ — questionary is synchronous/blocking; NEVER call it inside async code. Collect decisions first, then `asyncio.run(...)` the apply pipeline.

---

## Implementation Notes

### Key Constraints
- **Hot-file discipline**: one additive command block; helper logic goes in
  `charter.py` / `review.py` / `triage.py`, not cli.py. Rebase on `dev`
  immediately before starting AND before committing.
- Follow the file's existing conventions: `path_option` for `--path`,
  rich console output style used by `build`/`status`, `asyncio.run` for
  async bodies (see `ground` at 1947-2011).
- Mode flags mutually exclusive — fail fast with a clear click error if
  more than one is passed; default (no mode flag) → error telling the user
  to pick one (safest for a destructive-ish operation).
- `--extract` help text must say "experimental".

### References in Codebase
- `cli.py::ground` (1947-2011) — async + grounding-stack construction pattern.
- `cli.py::build` (723-847) — rich progress/summary conventions.
- `tests/knowledge/wiki/test_cli.py` — CliRunner conventions to extend.

---

## Acceptance Criteria

- [ ] `wikitoolkit ingest --dry-run` emits a valid manifest (null decisions) and ingests nothing.
- [ ] `--review` applies edited decisions; re-run is idempotent (no duplicate pages).
- [ ] `--interactive` prompts before any async work starts; decisions appended to `examples_file`.
- [ ] `--auto` flags the stratified audit sample per charter fractions.
- [ ] Mutually-exclusive mode flags enforced; `--extract` off by default and labeled experimental.
- [ ] Run header carries charter sha256/version + novelty backend; bookkeeper shows TRIAGE/ADMIT/ARCHIVE/DISCARD in `wikitoolkit audit`.
- [ ] `test_supervised_ingest_end_to_end` and `test_build_unaffected` pass.
- [ ] Full wiki suite green: `pytest tests/knowledge/wiki/ -v`; `ruff check` clean on cli.py.

---

## Test Specification

```python
# tests/knowledge/wiki/test_cli.py (add — CliRunner + stubbed adapter)
def test_cli_ingest_dry_run(...): ...
def test_cli_ingest_review_apply(...): ...
def test_cli_ingest_auto_audit_flags(...): ...
def test_cli_ingest_mode_flags_exclusive(...): ...

# tests/knowledge/wiki/test_integration.py (add)
async def test_supervised_ingest_end_to_end(...): ...
def test_build_unaffected(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2074 (and transitively 2069-2073) in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — cli.py is hot: re-anchor every line
   number listed above against the current file before editing
4. **Update status** in `sdd/tasks/index/supervised-wiki-ingestion.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and **update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude, autonomous)
**Date**: 2026-08-02
**Notes**: Added `wikitoolkit ingest <folder>` to `wiki/cli.py` as one
additive section (helper functions + the command), inserted between
`ground` and the `claude-hook` command, matching the file's own
established grouping/lazy-import conventions (every new heavy import —
charter/review/triage/ingest/bookkeeper/PageIndexToolkit/LLMFactory — is
local to the command function or a helper, exactly like `ground`/
`remember`). Re-anchored the Codebase Contract against the current file
(still exactly 2062 lines pre-edit, confirming no drift since the spec's
`ad6365242` verification) before touching anything. `wikitoolkit build`
verified unaffected by direct regression test
(`test_build_unaffected`: identical `store.stats()` across two runs, and
no page ever carries `WikiPageCategory.ARCHIVE`).

Implemented all four modes: `--dry-run` (triage → `ManifestWriter`,
decisions null, nothing ingested, rich summary table), `--review`
(`ManifestReader` → apply via `WikiIngestOrchestrator.ingest(triage=...)`,
idempotent by construction since TASK-2074's `replace_source_slice`
path), `--interactive` (triage completes first, THEN a synchronous
`questionary.select` loop — verified no async work runs during
prompting, then the async apply pipeline), `--auto` (thresholds decide,
`stratified_sample` flags the audit subset per `charter.calibration`
fractions, prints an `agreement_rate()` follow-up note). Mode flags are
mutually exclusive (`click.UsageError` on 0 or >1 selected). `--extract`
is off by default and documented as EXPERIMENTAL in its help text;
off means triage claims are stripped from the written manifest (the
router still uses them internally for novelty scoring — only the
manifest *representation* is affected, matching v1's document-level
admission non-goal). Every triaged document logs a `TRIAGE` bookkeeper
line; `ADMIT`/`ARCHIVE`/`DISCARD` come from TASK-2074's orchestrator
wiring. `ManifestRunHeader` carries `charter.fingerprint`/`.version` +
`novelty_scorer.backend` on every run. Human decisions (interactive
overrides, and manifest rows read back with `decision_source="human"`
in `--review`) append to `charter.examples_file` via `append_example`
when one is configured.

All acceptance-criteria tests pass: `test_cli_ingest_dry_run`,
`test_cli_ingest_review_apply` (+ idempotent re-run), `test_cli_ingest_auto_audit_flags`,
`test_cli_ingest_mode_flags_exclusive`, plus extras (missing-charter/
missing-model errors, `--extract` claim-stripping, interactive
prompt-before-apply ordering) — 8 new tests in `test_cli.py`, all 42
tests in the file green. `test_supervised_ingest_end_to_end` and
`test_build_unaffected` added to `test_integration.py` per the Test
Specification (6/6 green). Full `tests/knowledge/wiki/` suite: 755
passed, 2 skipped (pre-existing/unrelated), `test_arango_integration.py`
deselected (live-DB-only, pre-existing convention). `ruff check` clean
on every new line in all three files (verified line-by-line against
`git diff` — the pre-existing top-of-file `test_integration.py` I001 and
two unused-import F401s, and cli.py's handful of pre-existing SIM/UP/ISC
findings elsewhere in the 2062-line original file, are untouched by this
diff).

**Deviations from spec / resolved contract gaps** (all additive, all
documented here per the mandatory anti-hallucination process — none
change any class/method signature fixed elsewhere in the spec):

1. **`WikiConfig` (models.py, carries `charter_path`) is never
   constructed anywhere in the pre-existing `cli.py`** — every other
   command operates on `WikiProjectConfig` (`.parrot/wiki.json`) plus raw
   store/sources objects, bypassing `WikiIngestOrchestrator.ingest()`
   entirely (`build`'s `_ingest_files` is a wholly separate, deterministic
   pipeline; confirmed zero `WikiConfig(` construction hits pre-edit).
   Resolved by constructing a `WikiConfig` inline inside the new `ingest`
   command from `WikiProjectConfig` fields + the resolved `--charter`
   path, exactly where TASK-2074's `orch.ingest(..., wiki_config)` needs
   one.
2. **No client/model-selection infrastructure exists anywhere in
   `cli.py`** (zero `PageIndexToolkit`/`PageIndexLLMAdapter`/LLM-client
   construction pre-edit — `build`/`upsert` are LLM-free, `remember`/
   `note`/`link` author pages directly). Added `--lightweight-model`/
   `--model` flags (falling back to `$WIKI_LIGHTWEIGHT_MODEL`/
   `$WIKI_MODEL`) and a `_build_triage_adapters` seam using the existing,
   general-purpose `parrot.clients.factory.LLMFactory.create("provider:model")`
   — not a new construct, an existing factory this task's spec did not
   name explicitly but the codebase already provides for exactly this
   "provider:model" string format (matches `WikiConfig.lightweight_model`/
   `.model`'s documented format).
3. **`WikiProjectConfig` has no `charter_path`/model fields** (verified
   its full field list; not in this task's file-modify list either).
   `--charter` resolution therefore falls back to a project-relative
   convention (`<root>/.parrot/charter.yaml`) rather than a persisted
   config field, with a clear `ClickException` when neither is found.
4. **`--audit-rate`** (float, default 0.1) was added because
   `CalibrationPolicy` (TASK-2069, as shipped) has no overall
   audit-sample-rate field — `stratified_sample`'s `sample_size` param
   (TASK-2070's own documented gap resolution) has to come from
   somewhere at the CLI layer; this closes that chain.
5. **`_DESTINATION_TO_SOURCES_COLUMN`, `heavy_adapter`, `charter_version`
   param, size/suffix-cap router params** — all pre-resolved by
   TASK-2071/2073/2074's own Completion Notes; this task consumes them
   as documented, no new gaps introduced there.

All five are additive CLI surface (new flags / a new inline config
construction / an existing factory reused), never a substitution of any
fixed class name or method signature named in the spec.
