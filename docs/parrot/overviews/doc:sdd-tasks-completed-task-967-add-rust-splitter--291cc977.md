---
type: Wiki Overview
title: 'TASK-967: Add `semantic-text-splitter` dependency to ai-parrot-loaders'
id: doc:sdd-tasks-completed-task-967-add-rust-splitter-dependency-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 1 of FEAT-141. Adds the Rust-backed `semantic-text-splitter` library
---

# TASK-967: Add `semantic-text-splitter` dependency to ai-parrot-loaders

**Feature**: FEAT-141 — Rust-backed Semantic Text Splitter
**Spec**: `sdd/specs/rust-semantic-text-splitter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-141. Adds the Rust-backed `semantic-text-splitter` library
(Ben Brandt, PyPI) as a runtime dependency of the `ai-parrot-loaders` package.
Every subsequent task (rewriting `SemanticTextSplitter` and `MarkdownTextSplitter`,
the test suite, verification) needs this dependency available in the venv.

This task is intentionally tiny and isolated so the dep change can be
reviewed and reverted independently if a wheel-resolution issue surfaces.

Spec sections: §3 Module 1, §6 Codebase Contract → "New external dep",
§7 "External Dependencies".

---

## Scope

- Add `"semantic-text-splitter>=0.30,<1.0"` to the `dependencies = [ ... ]`
  block of `packages/ai-parrot-loaders/pyproject.toml`.
- Verify the install resolves cleanly inside the venv:
  `source .venv/bin/activate && uv pip install -e packages/ai-parrot-loaders`.
- Smoke-import the new module from Python to confirm wheel install:
  `python -c "from semantic_text_splitter import TextSplitter, MarkdownSplitter; print('ok')"`.

**NOT in scope**:
- Any code change in `splitters/*.py` (Modules 2–4).
- Any change to `[project.optional-dependencies]` groups.
- Bumping the package version of `ai-parrot-loaders` itself.
- Editing the top-level repo `pyproject.toml` (this is a workspace package).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/pyproject.toml` | MODIFY | Add one line in `dependencies = [ ... ]` |

---

## Codebase Contract (Anti-Hallucination)

### Verified file state

```toml
# packages/ai-parrot-loaders/pyproject.toml — current dependencies block
# (verified at task-write time — lines 28-33)
dependencies = [
    "ai-parrot>=0.24.39",
    "decorator>=5",
    "openpyxl>=3.1",
    "tabulate>=0.9",
]
```

### Required change (verbatim)

Insert the new dep line so the block becomes:

```toml
dependencies = [
    "ai-parrot>=0.24.39",
    "decorator>=5",
    "openpyxl>=3.1",
    "tabulate>=0.9",
    "semantic-text-splitter>=0.30,<1.0",
]
```

### Verified Library Surface (PyPI 0.30.x)

```python
from semantic_text_splitter import TextSplitter, MarkdownSplitter

# These constructors and methods are what later tasks will rely on:
TextSplitter(capacity=512, overlap=50)
TextSplitter.from_huggingface_tokenizer(tokenizer, capacity=512, overlap=50)
TextSplitter.from_tiktoken_model("gpt-4", capacity=512, overlap=50)
splitter.chunks(text)              # -> list[str]
splitter.chunk_indices(text)       # -> list[tuple[int, str]]  (BYTE offsets)

MarkdownSplitter(capacity=512, overlap=50)
```

### Does NOT Exist

- ~~`semantic_text_splitter.SentenceSplitter`~~ — only `TextSplitter` and
  `MarkdownSplitter` are public.
- ~~A `[tool.uv]` or `[tool.poetry]` block in this pyproject~~ — it uses
  setuptools (`build-backend = "setuptools.build_meta"`).
- ~~A separate optional-dependencies group called `splitters`~~ — do not
  invent one. The dep is core; it goes in the main `dependencies`.

---

## Implementation Notes

### Pattern to Follow

Single-line edit to the existing `dependencies` array. Preserve formatting
(four-space indent, trailing comma) so the diff is one line.

### Key Constraints

- Activate the venv before running any `uv` / `pip` / `python` command:
  `source .venv/bin/activate`.
- Pin `>=0.30,<1.0` exactly — pre-1.0 semver leaves room for breakage; we
  cap at <1.0 to force an explicit upgrade later (see spec §7 Risks).
- Do not edit `[project.optional-dependencies]`, build-system, or version.
- Keep the dep list alphabetically near-sorted (current order is roughly
  alphabetical; insert at the end is acceptable).

### References in Codebase

- `packages/ai-parrot-loaders/pyproject.toml:28-33` — current dependencies.
- Spec §7 → "Risk: dependency install fails on exotic platforms" — the
  Rust crate ships pre-built wheels for our targets; no Rust toolchain
  needed at install time.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-loaders/pyproject.toml` contains
      `"semantic-text-splitter>=0.30,<1.0"` inside `dependencies = [ ... ]`.
- [ ] `source .venv/bin/activate && uv pip install -e packages/ai-parrot-loaders`
      completes without errors.
- [ ] `python -c "from semantic_text_splitter import TextSplitter, MarkdownSplitter; print('ok')"`
      prints `ok`.
- [ ] No other file in the repo is modified by this task.

---

## Test Specification

Smoke-test only — no new pytest tests are added by this task (the test suite
arrives in TASK-971).

```bash
# Run inside the worktree, with venv activated
source .venv/bin/activate
uv pip install -e packages/ai-parrot-loaders
python -c "
from semantic_text_splitter import TextSplitter, MarkdownSplitter
s = TextSplitter(capacity=64, overlap=8)
chunks = s.chunks('hello world ' * 30)
assert isinstance(chunks, list) and all(isinstance(c, str) for c in chunks)
print('TextSplitter ok:', len(chunks), 'chunks')
m = MarkdownSplitter(capacity=64, overlap=8)
md_chunks = m.chunks('# H1\n\npara ' * 30)
assert isinstance(md_chunks, list) and all(isinstance(c, str) for c in md_chunks)
print('MarkdownSplitter ok:', len(md_chunks), 'chunks')
"
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/rust-semantic-text-splitter.spec.md` (§3, §6, §7).
2. Verify pyproject lines 28-33 still match the contract above; if not,
   adjust in place rather than blindly inserting.
3. Edit the file with the single-line addition.
4. Activate venv and run the install + smoke import.
5. Move this file to `sdd/tasks/completed/`, update `.index.json` → `done`,
   fill in the Completion Note, and commit.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-04
**Notes**: Added `semantic-text-splitter>=0.30,<1.0` to dependencies. Installed
version 0.30.1. Smoke test confirms `TextSplitter` and `MarkdownSplitter` work.
Key finding: `chunk_indices()` returns character offsets (not byte offsets) in
v0.30.1 — the `_byte_to_char` conversion in subsequent tasks should use the
offset directly as a char position.
**Deviations from spec**: none
