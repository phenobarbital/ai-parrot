# TASK-3180: Conventions block in the codex/google wiki installers + AGENTS.md prune

**Feature**: FEAT-553 — sdd-coder Shared Conventions & Turn Budget
**Spec**: `sdd/specs/sdd-coder-shared-conventions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3178
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (installer pair half + AGENTS.md prune). `parrot wiki codex
install` / `parrot wiki google install` already upsert a `parrot:wiki:*`
marker block; this task adds a second, `parrot:conventions:<agent>`, rendered
from `load_project_conventions(root)`, and removes it on uninstall. `AGENTS.md`
also loses its stale prose (Svelte/Capacitor, `isort`/`prettier`, the
`@RTK.md` include) — `black` stays, it is the active formatter (spec §10 R3).

---

## Scope

- `codex/assets.py`: `CONVENTIONS_BEGIN/END` + `conventions_section(root)`.
- `codex/installer.py`: `_install_agents` upserts wiki block THEN conventions
  block; `uninstall_codex_integration` removes the conventions block too.
- `google/assets.py` + `google/installer.py`: same pair for `GEMINI.md`.
- Regenerate the blocks in the repo's `AGENTS.md` and `GEMINI.md` and commit them.
- Prune `AGENTS.md` outside the managed blocks per the exact list below.
- Tests for both installers (there are none today for these functions).

**NOT in scope**: `coding_agents.py` (TASK-3181); any `CLAUDE.md` block
(deliberately none — spec §10 R5); MCP/bookstore/hooks parts of the installers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | markers + `conventions_section` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | install/uninstall the block |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` | MODIFY | markers + `conventions_section` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | install/uninstall the block |
| `AGENTS.md` | MODIFY | prune stale prose + regenerated block |
| `GEMINI.md` | MODIFY | regenerated block |
| `packages/ai-parrot/tests/knowledge/wiki/test_codex_installer_conventions.py` | CREATE | codex tests |
| `packages/ai-parrot/tests/knowledge/wiki/test_google_installer_conventions.py` | CREATE | google tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.conventions import load_project_conventions        # TASK-3178; import cost ~8 ms — safe in assets modules
from parrot.knowledge.wiki.codex import assets as codex_assets        # verified: knowledge/wiki/codex/assets.py
from parrot.knowledge.wiki.codex.installer import _install_agents, uninstall_codex_integration   # verified: codex/installer.py:77, :235
from parrot.knowledge.wiki.google import assets as google_assets      # verified: knowledge/wiki/google/assets.py
from parrot.knowledge.wiki.google.installer import _install_gemini_md, uninstall_google_integration  # verified: google/installer.py:81, :247
from pathlib import Path
```

### Existing Signatures to Use
```python
# knowledge/wiki/codex/assets.py
AGENTS_BEGIN = "<!-- parrot:wiki:codex:begin -->"      # line 13
AGENTS_END = "<!-- parrot:wiki:codex:end -->"          # line 14
AGENTS_SECTION = f"""{AGENTS_BEGIN}\n## Codebase Knowledge Graph (LLM Wiki)\n\n…\n\n{AGENTS_END}\n"""   # lines 23-28 — shape to mirror
# knowledge/wiki/codex/installer.py
def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str   # line 17
def _remove_marker_block(text: str, begin: str, end: str) -> str               # line 31
def _install_agents(root: Path) -> str:                                        # lines 77-89 — reads AGENTS.md, one upsert, returns "AGENTS.md — wiki section updated|created|already current"
def uninstall_codex_integration(root: Path) -> list[str]:                      # line 235; the AGENTS.md wiki-block removal is lines 243-249 (`agents_path = root / "AGENTS.md"` …)
# knowledge/wiki/google/assets.py
AGENTS_BEGIN = "<!-- parrot:wiki:google:begin -->"     # line 15 ; AGENTS_END line 16
GEMINI_PATH = Path("GEMINI.md")                        # line 17
GEMINI_SECTION = f"""{AGENTS_BEGIN}\n## Codebase Knowledge Graph (LLM Wiki)\n\n{NUDGE}\n\n{AGENTS_END}\n"""   # lines 30-36
# knowledge/wiki/google/installer.py
def _upsert_marker_block(...)   # line 18 ; def _remove_marker_block(...)  # line 32
def _install_gemini_md(root: Path) -> str:                                     # lines 81-93 — same shape as codex _install_agents
def uninstall_google_integration(root: Path, mcp_config_path: Optional[Path] = None) -> list[str]:   # line 247; GEMINI.md wiki-block removal lines 258-268

# AGENTS.md (103 lines, verified 2026-09-12) — sections, in order:
#   "# AGENT PERSONA & BEHAVIOR" … "## MUST-READ FILES" … "## SAFETY & GIT PROTOCOLS" … "## ARCHITECTURE & PATTERN" …
#   "## DYNAMIC TECH STACK & STANDARDS" → "### Frontend / Mobile (If React/Web detected)" (DELETE whole subsection)
#                                       → "### Python / Backend" (keep heading; replace body, see blueprint)
#                                       → "### Rust Development" (keep heading; replace body)
#   "## CODING STANDARDS" → "**Code Style:**" bullets: `black` (KEEP), `prettier` (DELETE), `isort` (DELETE), 4-space/f-strings/snake_case/PascalCase-python (KEEP),
#                            "Use camelCase for JavaScript/TypeScript variables and functions." (DELETE), "Use PascalCase for JavaScript/TypeScript classes." (DELETE)
#   … Completeness / No Hallucinations / Dependency Hygiene / Change Discipline / Correctness First (KEEP verbatim)
#   "<!-- parrot:wiki:codex:begin -->" … "<!-- parrot:wiki:codex:end -->" (KEEP; managed)
#   last line "@RTK.md" (DELETE — a Claude-Code import codex cannot expand)
# GEMINI.md — only the parrot:wiki:google block (443 bytes)
```

### Does NOT Exist
- ~~`tests/knowledge/wiki/test_codex_installer*.py` / `test_google_installer*.py`~~ — no test exercises `_install_agents` / `_install_gemini_md` today; this task creates them.
- ~~`codex_assets.CONVENTIONS_SECTION` as a module constant~~ — it must be a FUNCTION of `root` (the rule text is read from the repo at install time); do not freeze it at import.
- ~~a conventions block for `CLAUDE.md`~~ — none (spec §10 R5).
- ~~`parrot:conventions:gemini` markers~~ — the google installer uses `google`; TASK-3181 canonicalises the alias.

---

## Implementation Notes

### Key Constraints
- Marker strings are shared with TASK-3181 byte-for-byte: `<!-- parrot:conventions:codex:begin -->` / `…:end -->` and the `google` pair.
- Block body: `## Project conventions\n\n{load_project_conventions(root)}` — regenerated, never hand-edited.
- Upsert order on a fresh file: wiki block first, then conventions; re-running must not reorder (both `_upsert_marker_block` calls replace in place).
- Return strings from `_install_agents` / `_install_gemini_md` must now name both sections (existing CLI prints them).

### References in Codebase
- `knowledge/wiki/codex/installer.py:77-89` — the upsert idiom to duplicate.

---

## Implementation Blueprint

### Steps (in order)
1. Add markers + `conventions_section(root)` to both `assets.py` — *why*: installers only reference `assets.*`.
2. Extend `_install_agents` / `_install_gemini_md` with a second upsert and both uninstallers with a second `_remove_marker_block` — *why*: AC-6 promises install AND removal.
3. Prune `AGENTS.md` per the contract list, then regenerate both files from the repo root with `python -c "from pathlib import Path; from parrot.knowledge.wiki.codex.installer import _install_agents; from parrot.knowledge.wiki.google.installer import _install_gemini_md; print(_install_agents(Path('.'))); print(_install_gemini_md(Path('.')))"` — *why*: the committed blocks must be exactly what the installer produces.
4. Write the two test modules; run them.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^RULES_PATH = Path' …/codex/assets.py)
# AFTER — insert below `RULES_PATH = Path(".codex/rules/parrot-wiki.rules")` (verified: codex/assets.py:21)
CONVENTIONS_BEGIN = "<!-- parrot:conventions:codex:begin -->"
CONVENTIONS_END = "<!-- parrot:conventions:codex:end -->"


def conventions_section(root: Path) -> str:
    """Managed `## Project conventions` block rendered from the repo's `.agent/rules/` (FEAT-553)."""
    from parrot.flows.conventions import load_project_conventions  # local import: keeps module import order unchanged

    return f"{CONVENTIONS_BEGIN}\n## Project conventions\n\n{load_project_conventions(root)}\n\n{CONVENTIONS_END}\n"
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` (MODIFY)
```python
# occurrences: 1 — REPLACE `_install_agents` (verified: codex/installer.py:77-89) with:
def _install_agents(root: Path) -> str:
    path = root / "AGENTS.md"
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    after = _upsert_marker_block(before, assets.AGENTS_SECTION, assets.AGENTS_BEGIN, assets.AGENTS_END)
    after = _upsert_marker_block(
        after, assets.conventions_section(root), assets.CONVENTIONS_BEGIN, assets.CONVENTIONS_END
    )
    if after != before:
        path.write_text(after, encoding="utf-8")
        return f"AGENTS.md — wiki + conventions sections {'updated' if before else 'created'}"
    return "AGENTS.md — wiki + conventions sections already current"

# occurrences: 1 (verified: grep -c 'after = _remove_marker_block(before, assets.AGENTS_BEGIN, assets.AGENTS_END)' …/codex/installer.py)
# AFTER — insert below that line inside uninstall_codex_integration (verified: codex/installer.py:246)
        after = _remove_marker_block(after, assets.CONVENTIONS_BEGIN, assets.CONVENTIONS_END)
# and change the following actions.append text to "AGENTS.md — wiki + conventions sections removed"
```
**Why**: two upserts on the same text keep the wiki block first on a fresh file and idempotent on re-run.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` / `installer.py` (MODIFY)
```python
# google/assets.py — AFTER `PLUGIN_DIR = Path(".agents/plugins/parrot")` (verified: google/assets.py:19; occurrences: 1):
CONVENTIONS_BEGIN = "<!-- parrot:conventions:google:begin -->"
CONVENTIONS_END = "<!-- parrot:conventions:google:end -->"
def conventions_section(root: Path) -> str:   # identical body to the codex one
# google/installer.py — REPLACE `_install_gemini_md` (verified: :81-93) with the same two-upsert shape on `assets.GEMINI_SECTION` then `assets.conventions_section(root)`;
#   in uninstall_google_integration, AFTER `after = _remove_marker_block(before, assets.AGENTS_BEGIN, assets.AGENTS_END)` (verified: :261; occurrences: 1) add the conventions removal.
```

### `AGENTS.md` (MODIFY — prune, then regenerate)
```markdown
# DELETE: the whole "### Frontend / Mobile (If React/Web detected)" subsection (heading through its last "Always check for synchronization scripts…" bullet)
# REPLACE the body of "### Python / Backend" with exactly:
- See **Project conventions** below (managed block) — stack, forbidden libraries, layout, tooling.
# REPLACE the body of "### Rust Development" with exactly:
- PyO3 + Maturin; see `.agent/rules/rust-development.md`.
# DELETE these bullets under "**Code Style:**": `- Use `prettier` …`, `- Use `isort` …`, `- Use camelCase for JavaScript/TypeScript …`, `- Use PascalCase for JavaScript/TypeScript classes.`
# DELETE the bullet `- **Rules:** are specific rules for python development, use it.`
# DELETE the final line `@RTK.md`
# KEEP everything else byte-for-byte (persona, MUST-READ, SAFETY & GIT PROTOCOLS, ARCHITECTURE & PATTERN, the black line, Completeness…Correctness First, the wiki block).
# THEN run Step 3's regeneration command — it appends the conventions block after the wiki block.
```
**Why**: spec §3 M3 prune list; `test_agents_md_has_no_stale_prose` (below) is the guard.

### `packages/ai-parrot/tests/knowledge/wiki/test_codex_installer_conventions.py` (CREATE)
```python
"""Codex installer writes/removes the managed conventions block (FEAT-553, AC-6/AC-6b)."""
from __future__ import annotations

import re
from pathlib import Path

from parrot.knowledge.wiki.codex import assets
from parrot.knowledge.wiki.codex.installer import _install_agents, _remove_marker_block

_REPO_ROOT = Path(__file__).resolve().parents[4]   # FILL IN: verify parents[N] lands on the repo root (has AGENTS.md) — bounded by this test file's location


def _seed(root: Path) -> None:
    (root / ".agent" / "rules").mkdir(parents=True)
    (root / ".agent" / "rules" / "codebase-conventions.md").write_text("---\nx: 1\n---\nRULE-ONE\n")
    (root / ".agent" / "rules" / "python-development.md").write_text("RULE-TWO\n")


def test_install_agents_upserts_conventions_block(tmp_path):
    _seed(tmp_path)
    (tmp_path / "AGENTS.md").write_text("# Persona\nkeep me\n")
    first = _install_agents(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text()
    assert "created" in first and text.index(assets.AGENTS_BEGIN) < text.index(assets.CONVENTIONS_BEGIN)
    assert "RULE-ONE" in text and "RULE-TWO" in text and "keep me" in text
    assert "already current" in _install_agents(tmp_path)


def test_uninstall_removes_conventions_block(tmp_path):
    # FILL IN: install, then apply _remove_marker_block for both pairs the way uninstall_codex_integration does (or call it if it tolerates a bare tmp dir); assert "keep me" survives and no marker remains — bounded by AC-6


def test_agents_md_has_no_stale_prose():
    text = (_REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    unmanaged = re.sub(r"<!-- parrot:(wiki|conventions):codex:begin -->.*?<!-- parrot:\1:codex:end -->", "", text, flags=re.S)
    for token in ("Svelte", "Capacitor", "isort", "prettier", "camelCase", "@RTK.md", "are specific rules for python development"):
        assert token not in unmanaged, token
    assert assets.AGENTS_BEGIN in text and assets.CONVENTIONS_BEGIN in text
```
**Why**: the stale-prose check must ignore managed blocks (spec §10 R7) because the generated table legitimately contains `isort`.

### `packages/ai-parrot/tests/knowledge/wiki/test_google_installer_conventions.py` (CREATE)
```python
# Same three-part shape for `_install_gemini_md` on GEMINI.md with google assets; no stale-prose test (GEMINI.md has no prose).
# FILL IN: bodies — bounded by AC-6
```

### FILL IN checklist
- [ ] `test_codex_installer_conventions.py::_REPO_ROOT` — verify the parents index; `test_uninstall_removes_conventions_block` body; bounded by AC-6
- [ ] `test_google_installer_conventions.py` — bodies; bounded by AC-6

---

## Acceptance Criteria

- [ ] `_install_agents(Path("."))` and `_install_gemini_md(Path("."))` are idempotent and the committed `AGENTS.md` / `GEMINI.md` contain the regenerated `parrot:conventions:*` blocks after the wiki blocks (spec AC-6)
- [ ] `uninstall_codex_integration` / `uninstall_google_integration` remove the conventions block and nothing else (spec AC-6)
- [ ] `AGENTS.md` outside managed blocks has none of: Frontend/Mobile section, `isort`, `prettier`, camelCase lines, "Rules: are specific rules…", `@RTK.md`; the `black` line and safety/git sections are byte-unchanged (spec AC-6b)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_codex_installer_conventions.py packages/ai-parrot/tests/knowledge/wiki/test_google_installer_conventions.py -v`
- [ ] `ruff check` clean on the four modified source files

---

## Test Specification

See the CREATE test blocks above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M3, §10 R3/R5/R7)
2. **Check dependencies** — `TASK-3178` in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — line anchors in both installers; `AGENTS.md` section list
4. **Update status** in `sdd/tasks/index/sdd-coder-shared-conventions.json` → `"in-progress"`
5. **Implement** — from the blueprint; never hand-write text inside markers; never delete the `black` line
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3180-installer-conventions-block-and-agents-md.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none
