# TASK-5170: techwiki check, /sdd-task docs task, /sdd-done Step 4.6b

**Feature**: FEAT-801 — GitHub Wiki as the Technical Reference
**Spec**: `sdd/specs/github-wiki-technical-reference.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5166, TASK-5169
**Assigned-to**: unassigned

---

## Context

> Spec §3 M5. Creates the `techwiki check` command that reports a spec's declared documentation
> pages (never blocking), adds the documentation-task derivation rule to `/sdd-task`, and adds
> Step 4.6b to `/sdd-done`. Depends on TASK-5166 for the config model and TASK-5169 for the
> template changes (so `_assets/` regeneration covers both tasks' twin edits).

---

## Scope

- CREATE `parrot.sdd.techwiki.check` module: `DocsDecision`, `resolve_docs_policy`, `evaluate_docs`
- CREATE `parrot.sdd.scripts.techwiki_check` CLI shim
- CREATE `test_techwiki_check.py`
- MODIFY `/sdd-task` twins (claude + codex + google): add documentation-task rule
- MODIFY `/sdd-done` twins (claude + codex + google): add Step 4.6b
- (Operator, after merge) regenerate `_assets/` via `python scripts/sdd/check_asset_sync.py --write`; the coder must NOT touch `_assets/`
- CREATE `tests/sdd_scripts/test_techwiki_closeout_contract.py`

**NOT in scope**: API generator (TASK-5167), bundle (TASK-5168), spec template (TASK-5169), workflow (TASK-5171).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/techwiki/check.py` | CREATE | Docs check logic |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_check.py` | CREATE | CLI shim |
| `packages/ai-parrot/tests/sdd/test_techwiki_check.py` | CREATE | Unit tests |
| `.claude/commands/sdd-task.md` | MODIFY | Add documentation-task rule |
| `.agent/workflows/sdd-task.md` | MODIFY | Add documentation-task rule (twin) |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Add documentation-task rule (codex twin) |
| `.claude/commands/sdd-done.md` | MODIFY | Add Step 4.6b |
| `.agent/workflows/sdd-done.md` | MODIFY | Add Step 4.6b (twin) |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Add Step 4.6b (codex twin) |
| `tests/sdd_scripts/test_techwiki_closeout_contract.py` | CREATE | Closeout contract test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.techwiki.config import load_techwiki_config  # TASK-5166
import yaml                                                    # verified: check_e2e_closeout.py:22
from pathlib import Path                                       # stdlib
from dataclasses import dataclass, field                       # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py:53
def resolve_policy(spec_path: Path) -> str:
    # split('---', 2) + yaml.safe_load; absent → "optional"; malformed → "invalid"

# .claude/commands/sdd-task.md:121
# Anchor: `- Aim for tasks completable in 1–4 hours each.`

# .agent/workflows/sdd-task.md:117
# Anchor: `- Aim for tasks completable in 1–4 hours each.`

# .agents/skills/sdd-task/SKILL.md:69
# Anchor: `5. Plan task decomposition:`

# .claude/commands/sdd-done.md:290
# Anchor: `### 4.7. Test Report (FEAT-695)`

# .agent/workflows/sdd-done.md:227
# Anchor: `### 4.7. Test Report (FEAT-695)`

# .agents/skills/sdd-done/SKILL.md:128
# Anchor: `4.8. Closeout hooks — pre_pr (FEAT-764), after 4.7's test report and before step 6:`
```

### Does NOT Exist
- ~~`parrot.sdd.techwiki.check`~~ — created by this task
- ~~`parrot.sdd.scripts.techwiki_check`~~ — created by this task
- ~~`### 4.6b` in any `/sdd-done` twin~~ — added by this task
- ~~documentation-task rule in any `/sdd-task` twin~~ — added by this task
- ~~`resolve_docs_policy`~~ — created by this task (distinct from `resolve_policy` in check_e2e_closeout)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/techwiki/check.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/techwiki_check.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_techwiki_check.py", "action": "CREATE"},
    {"path": ".claude/commands/sdd-task.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-task.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-task/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-done.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-done.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_techwiki_closeout_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py#resolve_policy"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror `check_e2e_closeout.py`: same frontmatter parsing (`split('---', 2)` + `yaml.safe_load`),
same dataclass output, same `main()` pattern.

### Key Constraints
- `check` has **no blocking exit code** — exit 0 for ok/warning/skipped, exit 2 for invalid/usage (AC-7)
- No `--force` argument (AC-7)
- `check` runs without griffe and in a foreign repository (S12)
- Content rules: `docs_page_empty`, `docs_page_no_title`, `docs_api_module_syntax` (S6)
- Pages must stay inside root (no `..`, no absolute paths) → invalid `docs_page_outside_root`
- `/sdd-done` Step 4.6b: between 4.6 and 4.7; "Never blocks; `--force` has nothing to bypass"
- Both `/sdd-done` twins must state that no exit code of the check aborts closeout
- `.agent/workflows/sdd-task.md` must stay byte-identical to `.claude/commands/sdd-task.md` modulo frontmatter

---

## Implementation Blueprint

### Steps (in order)
1. Create `check.py` — *why*: core check logic
2. Create `techwiki_check.py` CLI shim — *why*: `parrot sdd techwiki check` command
3. Edit `/sdd-task` twins: add docs-task rule — *why*: derives documentation tasks from specs
4. Edit `/sdd-done` twins: add Step 4.6b — *why*: runs the check at closeout
5. Regenerate `_assets/` — *why*: packaged copies in sync
6. Create tests — *why*: AC-7, S6, S12

### `packages/ai-parrot/src/parrot/sdd/techwiki/check.py` (CREATE)
```python
"""Documentation-chapter check for ``parrot sdd techwiki check``."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_VALID_POLICIES = ("required", "none")


@dataclass
class DocsDecision:
    """Result of the documentation check."""

    policy: str
    status: str
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)


def resolve_docs_policy(spec_path: Path) -> tuple[str, list[str], list[str]]:
    """Return (policy, pages, api_modules) from the spec's ``docs:`` frontmatter.

    Absent ``docs`` key → ``("unset", [], [])``.
    Malformed → ``("invalid", [], [])``.
    Mirrors ``resolve_policy`` in ``check_e2e_closeout.py``: split on ``'---'``,
    ``yaml.safe_load``, never coerced.

    Args:
        spec_path: Path to the spec file.

    Returns:
        Tuple of (policy, pages list, api_modules list).
    """
    text = spec_path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ("unset", [], [])
    try:
        fm: dict[str, Any] = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return ("invalid", [], [])

    docs = fm.get("docs")
    if docs is None:
        return ("unset", [], [])
    if not isinstance(docs, dict):
        return ("invalid", [], [])

    policy = docs.get("policy", "unset")
    if policy not in _VALID_POLICIES and policy != "unset":
        return ("invalid", [], [])

    pages = docs.get("pages", [])
    if not isinstance(pages, list):
        return ("invalid", [], [])

    api_modules = docs.get("api_modules", [])
    if not isinstance(api_modules, list):
        api_modules = []

    return (policy, pages, api_modules)


def evaluate_docs(
    policy: str, pages: list[str], api_modules: list[str], root: Path
) -> DocsDecision:
    """Evaluate the documentation state for a spec.

    Args:
        policy: Resolved policy string.
        pages: List of declared wiki page paths.
        api_modules: List of dotted module names.
        root: Repository root.

    Returns:
        DocsDecision with status and reason codes.
    """
    # FILL IN: implement the decision table from spec §3 M5 — bounded by AC-7, S6
    # none → skipped; unset → skipped (docs_unset); required with pages present → ok;
    # required with missing → warning; empty/no-title → warning; bad api_modules → warning;
    # path traversal → invalid
    raise NotImplementedError
```
**Why this shape**: Same split-and-safe_load as `resolve_policy`. `resolve_docs_policy` is fully implemented because it's mechanical; `evaluate_docs` is FILL IN because the decision table has branching.

### `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_check.py` (CREATE)
```python
"""CLI shim for ``parrot sdd techwiki check``."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Report a spec's declared documentation pages (never blocking).

    Exit codes:
        0: ok, warning, or skipped
        2: invalid or usage error
    By construction there is no blocking exit code.
    """
    parser = argparse.ArgumentParser(description="Check spec documentation pages")
    parser.add_argument("--spec", type=Path, required=True, help="Path to spec file")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    # No --force argument (AC-7)
    args = parser.parse_args(argv)

    if not args.spec.exists():
        print(f"Spec not found: {args.spec}", file=sys.stderr)
        return 2

    from parrot.sdd.techwiki.check import resolve_docs_policy, evaluate_docs

    policy, pages, api_modules = resolve_docs_policy(args.spec)
    decision = evaluate_docs(policy, pages, api_modules, args.root)

    output = asdict(decision)
    if args.as_json:
        print(json.dumps(output))
    else:
        print(f"Docs: {decision.policy} — {decision.status}")
        if decision.missing:
            print(f"  missing: {', '.join(decision.missing)}")
        if decision.reason_codes:
            print(f"  reasons: {', '.join(decision.reason_codes)}")

    if decision.status == "invalid":
        return 2
    return 0
```
**Why this shape**: No blocking exit code by construction (AC-7). No `--force` argument.

### `.claude/commands/sdd-task.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'Aim for tasks completable in 1–4 hours each.' .claude/commands/sdd-task.md)
# AFTER — insert below `- Aim for tasks completable in 1–4 hours each.` (verified: sdd-task.md:121)

**Documentation task (FEAT-801).** When the spec's `docs.policy` is `required`, emit exactly one
task *Documentation — <pages>* that creates/updates the listed `wiki/` pages from
`sdd/templates/techwiki-page.md`, `depends_on` every task that creates a symbol the pages document
(last in the graph), validation command `parrot sdd techwiki check --spec <spec> --root .`,
`parallel: true`. `none`/absent: no task.
```

### `.agent/workflows/sdd-task.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'Aim for tasks completable in 1–4 hours each.' .agent/workflows/sdd-task.md)
# AFTER — insert the identical text below line 117
# Must be byte-identical to the .claude/commands/ twin's insertion
```

### `.agents/skills/sdd-task/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '5. Plan task decomposition:' .agents/skills/sdd-task/SKILL.md)
# AFTER — insert within item 5 at line 69
# Adapt the documentation-task rule to the codex twin's numbered-list style
```

### `.claude/commands/sdd-done.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '### 4.7. Test Report' .claude/commands/sdd-done.md)
# BEFORE — insert above `### 4.7. Test Report (FEAT-695)` (verified: sdd-done.md:290)

### 4.6b. Documentation Check (FEAT-801)

Run the documentation check. This step never blocks closeout; `--force` has nothing to bypass.

```bash
DOCS_JSON=$(parrot sdd techwiki check --spec "$SPEC_PATH" --root "$WORKTREE_PATH" --json 2>/dev/null) || true
```

Record the result:
- Exit 0 with JSON → `Docs: <policy> — <status>[ (missing: <pages>)]`
- Exit 2 → `Docs: invalid — <reason_codes>` (malformed `docs:` block or usage error) — continue
- Any other failure → `Docs: check failed (exit $?) — see output` — continue

Carry the `Docs:` line into Step 5's report, the PR body Evidence section and Step 12's output.
No exit code of `techwiki check` aborts closeout.
```

### `.agent/workflows/sdd-done.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '### 4.7. Test Report' .agent/workflows/sdd-done.md)
# BEFORE — insert above `### 4.7. Test Report (FEAT-695)` (verified: sdd-done.md:227)
# Insert the same Step 4.6b text (must be byte-identical to the command twin's insertion)
```

### `.agents/skills/sdd-done/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'Closeout hooks' .agents/skills/sdd-done/SKILL.md)
# BEFORE — insert above `4.8. Closeout hooks — pre_pr (FEAT-764), after 4.7's test report and before step 6:` (verified: SKILL.md:128)
# Add the equivalent 4.6b step in codex twin style (numbered list)
```

### FILL IN checklist
- [ ] `check.py::evaluate_docs` — decision table implementation; bounded by AC-7, S6
- [ ] `.agents/skills/sdd-task/SKILL.md` — adapt docs-task rule to codex style; bounded by AC-8
- [ ] `.agents/skills/sdd-done/SKILL.md` — adapt 4.6b step to codex style; bounded by AC-8
- [ ] `_assets/` regeneration — `python scripts/sdd/check_asset_sync.py --write`; bounded by AC-8

---

## Acceptance Criteria

- [ ] `techwiki check` implements the §3 M5 decision table including content rules (AC-7)
- [ ] No blocking exit code; no `--force` argument; test inspects argparse and main (AC-7)
- [ ] Both `/sdd-done` twins state "no exit code of techwiki check aborts closeout" (AC-7)
- [ ] `check` runs without griffe and in a foreign repo (S12)
- [ ] All three `/sdd-task` twins carry the documentation-task rule (AC-8)
- [ ] All three `/sdd-done` twins carry Step 4.6b (AC-8)
- [ ] `scripts/sdd/check_asset_sync.py --check` passes (AC-8)
- [ ] Pre-existing spec without `docs:` → `Docs: unset — skipped` (AC-9)
- [ ] No `requests`/`httpx`/LangChain; `ruff check` passes (AC-14)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`
- `pytest tests/sdd_scripts/test_techwiki_closeout_contract.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_techwiki_check.py
import pytest
from pathlib import Path
from parrot.sdd.techwiki.check import resolve_docs_policy, evaluate_docs, DocsDecision


class TestResolveDocs:
    def test_unset(self, tmp_path):
        """No docs key → unset."""
        spec = tmp_path / "spec.md"
        spec.write_text("---\ntype: feature\n---\n# Spec")
        assert resolve_docs_policy(spec)[0] == "unset"

    def test_required(self, tmp_path):
        """docs.policy: required."""
        spec = tmp_path / "spec.md"
        spec.write_text("---\ntype: feature\ndocs:\n  policy: required\n  pages:\n    - wiki/a/b.md\n---\n")
        policy, pages, _ = resolve_docs_policy(spec)
        assert policy == "required"
        assert pages == ["wiki/a/b.md"]

    def test_invalid_non_dict(self, tmp_path):
        """Non-dict docs → invalid."""
        spec = tmp_path / "spec.md"
        spec.write_text("---\ndocs: true\n---\n")
        assert resolve_docs_policy(spec)[0] == "invalid"


class TestEvaluateDocs:
    def test_check_content_rules(self, tmp_path):
        """Empty page / no title / bad api_modules → warning codes."""
        # FILL IN — bounded by S6

    def test_check_repo_relative_only(self, tmp_path):
        """Path with '..' → invalid (docs_page_outside_root)."""
        # FILL IN — bounded by S12

    def test_check_never_blocking(self):
        """Every policy/status → exit 0 or 2; no allowed=False path."""
        # FILL IN — bounded by AC-7


# tests/sdd_scripts/test_techwiki_closeout_contract.py
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

class TestCloseoutContract:
    def test_sdd_done_twins_call_check(self):
        """Both /sdd-done twins call parrot sdd techwiki check."""
        for twin in [".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md"]:
            text = (REPO_ROOT / twin).read_text()
            assert "parrot sdd techwiki check" in text

    def test_step_46b_between_46_and_47(self):
        """### 4.6b sits between 4.6 and 4.7."""
        text = (REPO_ROOT / ".claude/commands/sdd-done.md").read_text()
        i46b = text.index("### 4.6b")
        i47 = text.index("### 4.7")
        assert i46b < i47

    def test_never_blocks_present(self):
        """The word 'never blocks' or 'never aborts' is present."""
        for twin in [".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md"]:
            text = (REPO_ROOT / twin).read_text()
            assert "never blocks" in text.lower() or "never aborts" in text.lower()

    def test_sdd_task_twins_carry_docs_rule(self):
        """All three sdd-task twins carry the documentation-task rule."""
        for twin in [
            ".claude/commands/sdd-task.md",
            ".agents/skills/sdd-task/SKILL.md",
            ".agent/workflows/sdd-task.md",
        ]:
            text = (REPO_ROOT / twin).read_text()
            assert "Documentation task" in text or "documentation task" in text.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
2. **Check dependencies** — TASK-5166 and TASK-5169 must be `done`
3. **Verify** anchors in all six twin files match the probed line numbers
4. **Implement** check.py and CLI shim, then edit all six twins
5. **Regenerate `_assets/`**: `python scripts/sdd/check_asset_sync.py --write` and `git add -f`
6. **Run tests** including twin parity and asset sync
7. **Commit** only the listed files + regenerated `_assets/`
8. **Close** with `parrot sdd task close TASK-5170 github-wiki-technical-reference verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
