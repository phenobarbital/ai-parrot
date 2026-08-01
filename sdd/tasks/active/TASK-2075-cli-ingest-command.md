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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
