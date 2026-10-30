# TASK-4915: Governance rules chain (parse, resolve, render to a layer)

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4914
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, goal G5, §8 Q4 and Q8. Governance rules are an additive chain org → team → project → expert
(→ stage in phase 4) of `ALWAYS …` / `NEVER …` lines. The org/team/project files live at
`AGENTS_DIR/governance/{org,team,project}.md` (Q4). A bundle's own `rules/governance.md` is **optional** (Q8): a
missing file shortens the chain, it never fails it. Rules are never trimmed by the knowledge budget.

---

## Scope

- Implement `parse_rules(path, *, layer)` with the strict grammar.
- Implement `resolve_chain(workspace, bundle, *, stage_rules=None)` — additive, deduplicated, missing files skipped.
- Implement `rules_to_layer(chain, counter)` → one INLINE `KnowledgeLayer(layer="rules")`, emitted even when empty.
- Write `test_rules.py`.

**NOT in scope**: rendering the `<governance_rules>` XML (TASK-4918), loading `rules/governance.md` from a bundle
directory into `ExpertBundle.rules` (TASK-4925), stage rules (phase 4 — the parameter exists, callers pass `None`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/rules.py` | CREATE | Grammar, chain, layer |
| `packages/ai-parrot/tests/experts/test_rules.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.experts.models import RuleSet, KnowledgeLayer, KnowledgeMode, ExpertBundle, RuleSyntaxError   # created by TASK-4914
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter   # verified: parrot/memory/compaction/tokens.py:30,89
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/compaction/tokens.py
class TokenCounter(Protocol):          # line 30
    def count(self, text: str) -> int  # line 35
def get_default_counter() -> TokenCounter   # line 89
```

### Does NOT Exist
- ~~`.parrot/memory/org.md`~~ — not read (§8 Q4 decided `AGENTS_DIR/governance/`).
- ~~a rules parser anywhere in `parrot/`~~ — no ALWAYS/NEVER parser exists; do not look for one to reuse.
- ~~`parrot.experts.rules.load_bundle_rules`~~ — the bundle loader (TASK-4925) calls `parse_rules` itself.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/rules.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_rules.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/compaction/tokens.py#TokenCounter",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/tokens.py#get_default_counter"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Grammar: a `## Mandated` heading opens a section of lines starting `ALWAYS `; `## Forbidden` opens `NEVER `
  lines. Blank lines and lines starting with `<!--` are ignored. Any other non-empty line → `RuleSyntaxError`
  naming the file and line number. An `ALWAYS` line under `## Forbidden` (or vice versa) is also an error.
- `revision` = hex sha256 of the file bytes.
- Dedupe: an identical line (after `strip()`) seen in a wider layer wins; the narrower copy is dropped.
- `RULE_LAYERS` order is fixed: `("org", "team", "project", "expert", "stage")`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `parse_rules` — *why*: everything else consumes `RuleSet`s.
2. Write `resolve_chain` — *why*: the additive order is the contract the resolver relies on (AC8).
3. Write `rules_to_layer` — *why*: the resolver (TASK-4919) emits it as the first, never-trimmed layer.

### `packages/ai-parrot/src/parrot/experts/rules.py` (CREATE)
```python
"""Governance rules: strict ALWAYS/NEVER grammar and the additive org→team→project→expert chain (FEAT-778 M8)."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Final, Sequence

from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeMode, RuleSet, RuleSyntaxError
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter

GOVERNANCE_DIRNAME: Final[str] = "governance"
RULE_LAYERS: Final[tuple[str, ...]] = ("org", "team", "project", "expert", "stage")
_LOGGER = logging.getLogger(__name__)


def parse_rules(path: Path, *, layer: str) -> RuleSet:
    """Parse one rules file. Raises RuleSyntaxError on any line outside the grammar."""
    data = path.read_bytes()
    mandated: list[str] = []
    forbidden: list[str] = []
    # FILL IN: walk lines with a current-section state ("mandated" | "forbidden" | None); headings switch it;
    # validate prefix per section; raise RuleSyntaxError(f"{path}:{lineno}: …") — bounded by AC8
    return RuleSet(layer=layer, source=path, revision=hashlib.sha256(data).hexdigest(),
                   mandated=mandated, forbidden=forbidden)


def resolve_chain(workspace: Path | None, bundle: ExpertBundle, *, stage_rules: RuleSet | None = None) -> list[RuleSet]:
    """Additive chain in RULE_LAYERS order.

    `workspace` is the AGENTS_DIR root: org/team/project come from `workspace/governance/<layer>.md` when the file
    exists; the expert layer is `bundle.rules` when not None (rules/governance.md is optional, §8 Q8); stage_rules
    is appended last. Exact-duplicate lines keep the widest layer only.
    """
    chain: list[RuleSet] = []
    if workspace is not None:
        for layer in ("org", "team", "project"):
            candidate = workspace / GOVERNANCE_DIRNAME / f"{layer}.md"
            if candidate.is_file():
                chain.append(parse_rules(candidate, layer=layer))
    if bundle.rules is not None:
        chain.append(bundle.rules)
    if stage_rules is not None:
        chain.append(stage_rules)
    # FILL IN: dedupe across the chain keeping the first (widest) occurrence; rebuild RuleSets with model_copy
    return chain


def rules_to_layer(chain: Sequence[RuleSet], counter: TokenCounter | None = None) -> KnowledgeLayer:
    """One INLINE 'rules' layer; content lists Mandated then Forbidden lines per layer; always emitted."""
    counter = counter or get_default_counter()
    # FILL IN: content text (may be '' for an empty chain); revision = sha256 of "|".join(r.revision for r in chain)
    content = ""
    return KnowledgeLayer(layer="rules", source="governance-chain", mode=KnowledgeMode.INLINE,
                          revision=hashlib.sha256("|".join(r.revision for r in chain).encode()).hexdigest(),
                          tokens=counter.count(content), content=content)
```
**Why this shape**: `resolve_chain` reads only fixed paths and skips missing files — that is the Q8 fail-over
contract. `rules_to_layer` always returns a layer so the rendered prompt stays stable when the chain is empty.

### FILL IN checklist
- [ ] `parse_rules` — section state machine and error messages; bounded by AC8.
- [ ] `resolve_chain` — cross-layer dedupe keeping the widest layer; bounded by AC8.
- [ ] `rules_to_layer` — content format (one line per rule, layer label per block).

---

## Acceptance Criteria

- [ ] AC8 (rules part) — chain is additive org → team → project → expert and deduplicated; a prose line raises `RuleSyntaxError`.
- [ ] AC25 (chain part) — `bundle.rules is None` produces a chain with the org/team/project layers only.
- [ ] Missing `AGENTS_DIR/governance/*.md` files are skipped without error.
- [ ] `ruff check` passes on the new files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_rules.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_rules.py — uses governance_dir / expert_bundle from conftest (TASK-4914)
def test_rules_grammar_rejects_prose(tmp_path): ...                 # FILL IN
def test_rules_grammar_rejects_wrong_section(tmp_path): ...         # FILL IN: ALWAYS under ## Forbidden
def test_rules_chain_is_additive_and_deduped(governance_dir): ...   # FILL IN: org rule kept, duplicate once
def test_chain_without_bundle_rules(governance_dir): ...            # FILL IN: bundle.rules=None -> 3 layers
def test_chain_with_no_governance_dir(tmp_path): ...                # FILL IN: empty chain, layer still emitted
def test_revision_is_sha256(tmp_path): ...                          # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4915 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: gpt-5.6-terra (codex) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier gate and chunk merge-tier validation green (80 + 5 passed).

**Deviations from spec**: none
