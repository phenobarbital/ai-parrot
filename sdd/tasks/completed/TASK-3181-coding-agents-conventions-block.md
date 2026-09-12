# TASK-3181: `coding_agents.install()` writes the conventions block (canonical gemini→google)

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3180
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (stdlib installer half, §8 Q3 = yes). `parrot wiki <agent>
install` goes through `knowledge/wiki/coding_agents.py`, a deliberately
stdlib-only module. It must write the same `parrot:conventions:*` block as
TASK-3180's installers, keyed by the *canonical* name — `_AGENTS` maps both
`gemini` and `google` to `GEMINI.md`, so a raw-alias marker would produce two
blocks in one file (spec §10 R4). `claude` writes no conventions block (§10 R5).

---

## Scope

- Add `_CONVENTIONS_AGENT`, `_conventions_markers`, `_conventions_block` to `coding_agents.py`.
- `install()`: after the wiki upsert, upsert the conventions block for agents in `_CONVENTIONS_AGENT`.
- Tests: per-agent block + idempotency, `claude` writes none, cross-installer single block in `GEMINI.md`.

**NOT in scope**: an uninstall for `coding_agents` (none exists; not promised);
hooks/skills parts of `install()`; TASK-3180's installers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py` | MODIFY | conventions block in `install()` |
| `packages/ai-parrot/tests/test_coding_agents.py` | MODIFY | three new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.conventions import load_project_conventions   # TASK-3178; stdlib-only leaf, ~8 ms — the ONLY parrot import this module may add
from parrot.knowledge.wiki import coding_agents                  # verified: tests/test_coding_agents.py:6
from parrot.knowledge.wiki.google import assets as google_assets # verified (for the cross-installer test): google/assets.py CONVENTIONS_BEGIN (TASK-3180)
from parrot.knowledge.wiki.google.installer import _install_gemini_md   # verified: google/installer.py:81
```

### Existing Signatures to Use
```python
# knowledge/wiki/coding_agents.py
_AGENTS = {"codex": ("AGENTS.md", …), "claude": ("CLAUDE.md", …), "gemini": ("GEMINI.md", …), "google": ("GEMINI.md", …)}   # lines 43-55
def _markers(agent: str) -> tuple[str, str]      # line 57 — f"<!-- parrot:wiki:{agent}:begin -->" … (raw alias; pre-existing gemini/google duplication is OUT of scope)
def _block(agent: str) -> str                    # line 61
def _upsert(text: str, block: str, begin: str, end: str) -> str   # line 66 — idempotent; reuse as-is
def install(agent: str, root: Path = Path.cwd()) -> list[str]:    # line 89
    begin, end = _markers(agent)                                  # line 98
    after = _upsert(before, _block(agent), begin, end)            # line 99
    if after != before:                                           # line 100
        instruction_path.write_text(after, encoding="utf-8")      # line 101
    changes.append(instruction)                                   # line 102
# tests/test_coding_agents.py
def test_install_is_idempotent_and_preserves_settings(tmp_path)   # line 9 — pattern: call install twice, compare bytes
# TASK-3180 marker strings (must match byte-for-byte):
#   "<!-- parrot:conventions:codex:begin -->" / "<!-- parrot:conventions:codex:end -->"
#   "<!-- parrot:conventions:google:begin -->" / "<!-- parrot:conventions:google:end -->"
```

### Does NOT Exist
- ~~`coding_agents.uninstall`~~ — only `install` (:89) and `hook` (:125) exist; do not add one.
- ~~`_CONVENTIONS_AGENT["claude"]`~~ — no entry; `install("claude")` must write no conventions block.
- ~~`parrot:conventions:gemini` markers~~ — never emitted.
- ~~importing `parrot.flows.dev_loop._subagent_defs` here~~ — forbidden (2.2 s import; breaks the stdlib-only contract).

---

## Implementation Notes

### Key Constraints
- Keep the import of `load_project_conventions` local to `_conventions_block` (inside the function) so `coding_agents` import stays as cheap as today.
- `changes` still lists the instruction file once.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three helpers below `_block` — *why*: they mirror `_markers`/`_block` so the module keeps one style.
2. Extend `install()` with the second upsert — *why*: AC-6.
3. Add the tests; run `pytest packages/ai-parrot/tests/test_coding_agents.py -v`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def _upsert(' …/coding_agents.py)
# BEFORE — insert directly above `def _upsert(text: str, block: str, begin: str, end: str) -> str:` (verified: coding_agents.py:66)
# FEAT-553: conventions block, keyed by the canonical instruction-file owner so `gemini` and
# `google` (both GEMINI.md) share ONE block with the google/ installer. No entry for `claude`:
# Claude Code already reads .claude/rules/ and this module has no uninstaller.
_CONVENTIONS_AGENT: dict[str, str] = {"codex": "codex", "gemini": "google", "google": "google"}


def _conventions_markers(agent: str) -> tuple[str, str] | None:
    canonical = _CONVENTIONS_AGENT.get(agent)
    if canonical is None:
        return None
    return f"<!-- parrot:conventions:{canonical}:begin -->", f"<!-- parrot:conventions:{canonical}:end -->"


def _conventions_block(agent: str, root: Path) -> str:
    from parrot.flows.conventions import load_project_conventions  # stdlib-only leaf; local import keeps this module cheap

    begin, end = _conventions_markers(agent)  # type: ignore[misc]  # caller checked for None
    return f"{begin}\n## Project conventions\n\n{load_project_conventions(root)}\n\n{end}\n"


# occurrences: 1 (verified: grep -c '    after = _upsert(before, _block(agent), begin, end)' …/coding_agents.py)
# AFTER — insert below `    after = _upsert(before, _block(agent), begin, end)` (verified: coding_agents.py:99)
    conv = _conventions_markers(agent)
    if conv is not None:
        after = _upsert(after, _conventions_block(agent, root), *conv)
```
**Why**: the wiki upsert stays first; the conventions upsert operates on `after`, so the file is written once (`if after != before` at :100 is unchanged).

### `packages/ai-parrot/tests/test_coding_agents.py` (MODIFY)
```python
# AFTER — append at end of file (verified: last test starts at :27)
import pytest


@pytest.mark.parametrize("agent,canonical", [("codex", "codex"), ("gemini", "google"), ("google", "google")])
def test_install_writes_conventions_block(tmp_path, agent, canonical):
    (tmp_path / ".agent" / "rules").mkdir(parents=True)
    (tmp_path / ".agent" / "rules" / "codebase-conventions.md").write_text("RULE-ONE\n")
    (tmp_path / ".agent" / "rules" / "python-development.md").write_text("RULE-TWO\n")
    coding_agents.install(agent, tmp_path)
    instruction = tmp_path / coding_agents._AGENTS[agent][0]
    text = instruction.read_text()
    assert f"<!-- parrot:conventions:{canonical}:begin -->" in text and "RULE-ONE" in text
    coding_agents.install(agent, tmp_path)
    assert instruction.read_text() == text


def test_claude_install_writes_no_conventions_block(tmp_path):
    # FILL IN: install("claude"); assert "parrot:conventions" not in CLAUDE.md — bounded by spec §10 R5


def test_gemini_and_google_share_one_conventions_block(tmp_path):
    # FILL IN: seed .agent/rules as above; coding_agents.install("gemini", tmp_path); then
    #   from parrot.knowledge.wiki.google.installer import _install_gemini_md; _install_gemini_md(tmp_path)
    #   assert (tmp_path/"GEMINI.md").read_text().count("<!-- parrot:conventions:google:begin -->") == 1
    #   and the reverse order gives the same count — bounded by spec §10 R4 / AC-6
```

### FILL IN checklist
- [ ] `test_claude_install_writes_no_conventions_block` body; bounded by §10 R5
- [ ] `test_gemini_and_google_share_one_conventions_block` body (both orders); bounded by §10 R4

---

## Acceptance Criteria

- [ ] `coding_agents.install("codex"|"gemini"|"google", root)` writes one idempotent `parrot:conventions:<canonical>` block; `install("claude")` writes none (spec AC-6)
- [ ] `GEMINI.md` ends with exactly one conventions block after both installers ran, in either order
- [ ] `python -X importtime -c "import parrot.knowledge.wiki.coding_agents" 2>&1 | grep -c dev_loop` prints `0`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_coding_agents.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py` clean

---

## Test Specification

See the MODIFY test block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M3, §10 R4/R5)
2. **Check dependencies** — `TASK-3180` in `sdd/tasks/completed/` (its marker strings are the contract)
3. **Verify the Codebase Contract** — `coding_agents.py:66` and `:99` anchors
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the blueprint; never emit a `gemini` marker; never add an uninstall
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3181-coding-agents-conventions-block.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none
