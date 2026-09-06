# TASK-2895: Document auto-detection and add the end-to-end degraded-mode regression test

**Feature**: FEAT-531 — Auto-detect Claude Code / Codex CLI and default wikitoolkit + bookstore's LLM to it
**Spec**: `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2893, TASK-2894
**Assigned-to**: unassigned

---

## Context

Closes out FEAT-531: documents the new `PARROT_NO_AUTO_LLM` opt-out and the auto-detection
behavior in `docs/guides/llm-wiki-guide.md` (spec §5 acceptance criterion), and adds the one
integration test from spec §4 that exercises the full "neither configured nor detected"
regression path end-to-end across both subsystems. This task runs last because it documents
and regression-tests the combined behavior of TASK-2893 and TASK-2894.

---

## Scope

- Update the "Environment Variables" table in `docs/guides/llm-wiki-guide.md`
  (`packages/ai-parrot`'s doc, currently at lines 1333-1348 — verify before editing) to:
  - Change the `Default` column for `WIKI_MODEL`, `WIKI_LIGHTWEIGHT_MODEL`, and
    `WIKI_EXTRACT_LLM` from `*(none)*` to something like `*(none — auto-detects a Claude
    Code/Codex CLI session if available; see below)*`.
  - Add a new row: `PARROT_NO_AUTO_LLM` | `*(none)*` | `Set to disable coding-agent CLI
    auto-detection for WIKI_MODEL/WIKI_LIGHTWEIGHT_MODEL/WIKI_EXTRACT_LLM and
    PARROT_BOOKSTORE_LLM` (adjust wording to match the surrounding table's style).
  - Add a short prose paragraph (3-5 sentences, near the table) explaining: when unset, these
    variables auto-detect an available Claude Code or Codex CLI session (Claude Code
    preferred) and default to it with a visible warning; `PARROT_NO_AUTO_LLM=1` restores the
    old strict degraded-mode behavior.
- Also check `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`'s module docstring
  (lines 1-19) — it documents `PARROT_BOOKSTORE_LLM`/`PARROT_BOOKSTORE_LLM_LIGHT` and
  currently says degraded mode is the sole no-config behavior; update it to mention the new
  auto-detection fallback and `PARROT_NO_AUTO_LLM`, consistent with TASK-2893's code change.
- Add the integration test described in spec §4: with no relevant env vars set and
  `shutil.which` mocked to return `None` for both `"claude"` and `"codex"`, verify the
  `bookstore` CLI still runs in degraded (BM25) mode exactly as before this feature.

**NOT in scope**:
- Any further code changes to `detection.py`, `_llm.py`, or `wiki/cli.py` beyond the
  docstring update named above — if TASK-2893/TASK-2894 left something incomplete, note it in
  the Completion Note rather than fixing it here.
- Rewriting unrelated parts of `llm-wiki-guide.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/guides/llm-wiki-guide.md` | MODIFY | Update env-var table + add explanatory paragraph |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py` | MODIFY | Update module docstring only (no logic change) |
| `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` | MODIFY | Add the end-to-end degraded-mode regression test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# no new imports — this task only edits docs and one docstring, plus a test file that
# already imports the bookstore CLI test harness (see existing test_cli.py for its fixtures)
```

### Existing Signatures to Use
```markdown
<!-- docs/guides/llm-wiki-guide.md, lines 1333-1348 -->
### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PARROT_HOME` | `~/.parrot` | Root for all parrot data (wikis, registries) |
| `WIKI_ENV` | *(none)* | Active wiki environment override — `WIKI_ENV` > `ENV` > `"local"` (FEAT-461) |
| `WIKI_STORE` | *(none)* | Override: read a pre-built store directly |
| `WIKI_STORE_BACKEND` | `sqlite` | Backend for `WIKI_STORE` (also honoured by `build`, FEAT-461) |
| `WIKI_MODEL` | *(none)* | LLM for `ingest` stage-2 and page generation |
| `WIKI_LIGHTWEIGHT_MODEL` | *(none)* | LLM for `ingest` stage-1 triage |
| `WIKI_EXTRACT_LLM` | *(none)* | LLM for `remember --extract` entity extraction |
| `CLAUDE_AGENT_ID` | *(none)* | Identity for `remember`/`note`/`link` attribution |
| `PARROT_AGENT_ID` | *(none)* | Fallback identity for attribution |
| `ARANGODB_HOST` | `127.0.0.1` | ArangoDB host (prefix configurable) |
...
```

### Does NOT Exist
- ~~A `PARROT_NO_AUTO_LLM` row in this table today~~ — does not exist yet; this task adds it.
- ~~Any prior mention of auto-detection in `llm-wiki-guide.md` or `_llm.py`'s docstring~~ —
  confirmed absent (spec §3 research); do not phrase the docstring update as clarifying
  pre-existing behavior.

---

## Implementation Notes

### Pattern to Follow
Match the existing table row style exactly (pipe-delimited, `*(none)*` for unset defaults,
short imperative-style descriptions) — do not reformat the whole table, only edit the four
affected rows/add the one new row in place.

For the `_llm.py` docstring update, keep the existing structure (bulleted env var list, then
the "When nothing is configured..." paragraph) and add one more bullet plus a sentence, rather
than restructuring the docstring.

### Key Constraints
- Documentation only for `llm-wiki-guide.md` — no code changes there.
- The `_llm.py` change is a **docstring-only** edit — do not touch `resolve_adapter()`'s logic
  in this task (that was TASK-2893's job; if it's not done or not landed, this task is
  blocked, not a place to redo it).

### References in Codebase
- `packages/ai-parrot/tests/knowledge/bookstore/test_cli.py` — existing CLI test fixtures to
  extend for the new integration test.
- `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:1-19` — module docstring to
  update.

---

## Acceptance Criteria

- [ ] `docs/guides/llm-wiki-guide.md`'s Environment Variables table documents
      `PARROT_NO_AUTO_LLM` and the updated auto-detection behavior for `WIKI_MODEL` /
      `WIKI_LIGHTWEIGHT_MODEL` / `WIKI_EXTRACT_LLM`.
- [ ] `bookstore/_llm.py`'s module docstring mentions the auto-detection fallback and
      `PARROT_NO_AUTO_LLM`, without describing any logic change (docstring-only edit).
- [ ] A new integration test verifies: with no `PARROT_BOOKSTORE_LLM` and no CLI available
      (`shutil.which` mocked to `None` for both `claude` and `codex`), the `bookstore` CLI
      still produces the exact same degraded-mode outcome as before this feature existed.
- [ ] All tests pass:
      `pytest packages/ai-parrot/tests/knowledge/bookstore/ packages/ai-parrot/tests/knowledge/wiki/ packages/ai-parrot/tests/clients/test_detection.py -v`
- [ ] No linting errors on any file touched by this task.
- [ ] No breaking changes to existing public API.

---

## Test Specification

```python
# append to packages/ai-parrot/tests/knowledge/bookstore/test_cli.py
from unittest.mock import patch


def test_bookstore_cli_degrades_without_any_config_or_cli(monkeypatch, cli_runner):
    for var in ("PARROT_BOOKSTORE_LLM", "PARROT_BOOKSTORE_LLM_LIGHT", "PARROT_NO_AUTO_LLM"):
        monkeypatch.delenv(var, raising=False)
    with patch("shutil.which", return_value=None):
        # invoke whatever bookstore CLI command exercises resolve_adapter() in this file's
        # existing fixtures (e.g. `add`/`search`) and assert it completes in degraded
        # (BM25/no-LLM) mode with the same user-visible outcome as before this feature.
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md` for full context.
2. **Check dependencies** — verify TASK-2893 and TASK-2894 are both in
   `sdd/tasks/completed/` before starting.
3. **Verify the Codebase Contract** — re-read the current env-var table and `_llm.py`
   docstring before editing (line numbers may have shifted after TASK-2893/2894 landed).
4. **Update status** in the per-spec index → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2895-docs-and-regression.md`.
8. **Update the index** → `"done"`, and set the per-spec index header's `completed_at`
   (this is the last task in the feature).
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
