# TASK-5012: Subsystem taxonomy + nine seed architecture rules (M10b)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4999, TASK-5000, TASK-5002
**Assigned-to**: unassigned

---

## Context

Spec G6, §3 Module 10 (taxonomy + seed), AC16/AC20. The governing dossier is only useful from day one
if the plane already holds the repository's architecture rules and a curated subsystem axis. This task
commits:

- `sdd/taxonomy/subsystems.yaml` — the initial 14 subsystems (memory, clients, bots, tools, flows,
  skills, knowledge-wiki, knowledge-graphindex, server, integrations, config, auth, sdd-tooling,
  dev-loop), each mapped to `KNOWN_PROJECTS` values;
- nine ADR Markdown files under `docs/decisions/`, one per owner-corrected seed rule (spec M10), each
  with flat frontmatter, Context / Decision / Consequences sections and a `## Decision Metadata` fenced
  YAML block in the `SpecDecisionsBlock` grammar of TASK-4999.

The approval entry for these files is recorded by TASK-5013 *after* this task's commit (its sha is the
approving commit — PLAN decision 7). Creating `sdd/taxonomy/subsystems.yaml` also makes this
repository "configured" for the decision audit (spec §2 portability principle).

---

## Scope

- Create `sdd/taxonomy/subsystems.yaml` with the 14 subsystems (`id`, `title`, `description`, `parent`,
  `projects`), in the exact file shape `Taxonomy.load` (TASK-5000) accepts.
- Create the nine seed files listed below with frontmatter `id: ADR-SEED-000N`, `title`, `status: accepted`
  (flat `key: value` lines only — `parse_frontmatter` rejects non-flat lines, parser.py:132/180).
- Each seed's `## Decision Metadata` block: `schema_version: 1`, `document_id: seed-<rule-slug>`, entries
  with the relation, `about` (taxonomy ids) and `targets` from the table below.
- Rule 3's rationale MUST state that `httpx` is excluded for **stack consistency, not because it blocks**
  (it supports async); the project standardizes on aiohttp + asyncio + uvloop (AC20).
- Create `T/test_seed_rules.py` (T = `packages/ai-parrot/tests/knowledge/wiki/decisions`): taxonomy loads;
  every seed parses via `parse_spec_decisions` on the `## Decision Metadata` heading with zero diagnostics;
  every `about` id is in the taxonomy; every target is a syntactically valid `sym:`/`file:`/`dir:` id whose
  path exists on disk (AC20 "resolve their targets on dev"); rule 3 rationale contains "stack consistency".

**NOT in scope**: `sdd/decisions/approvals.jsonl` and the docs page (TASK-5013); publishing the batch
into the plane (TASK-5007 / run by the maintainer after merge); changing the ruff TID251 ban list or
`codebase-conventions.md` wording (spec M10 says follow-up); legacy-discovery exclusion of seed files
(TASK-5007, PLAN decision 6).

### Seed rules (spec M10, owner-corrected 2026-10-31)

| # | File | relation(s) | about | targets |
|---|---|---|---|---|
| 1 | `docs/decisions/clients-memoryless.md` | forbids | clients, memory | `dir:packages/ai-parrot/src/parrot/clients` |
| 2 | `docs/decisions/history-single-writer.md` | requires | memory, bots | `file:packages/ai-parrot/src/parrot/bots/abstract.py` |
| 3 | `docs/decisions/non-blocking-async-stack.md` | forbids | server, integrations, tools, clients (see FILL IN below) | `dir:packages` |
| 4 | `docs/decisions/http-stack-aiohttp.md` | entry `requires-aiohttp` (requires) + entry `forbids-asgi` (forbids) | server, integrations | `dir:packages` |
| 5 | `docs/decisions/config-core-navconfig.md` | requires | config | `dir:packages` |
| 6 | `docs/decisions/auth-platform-navigator-auth.md` | requires | auth, server | `dir:packages/ai-parrot-server` |
| 7 | `docs/decisions/tools-live-in-parrot-tools.md` | requires | tools | `dir:packages/ai-parrot-tools/src/parrot_tools` |
| 8 | `docs/decisions/no-langchain.md` | forbids | clients, bots, flows, tools | `dir:packages` |
| 9 | `docs/decisions/clients-base-protected.md` | constrains | clients | `file:packages/ai-parrot/src/parrot/clients/base.py` |

Rule 3 `about`: FILL IN the final list — bounded by "every listed id exists in the taxonomy"; the
suggested set is `[server, integrations, tools, clients]` (blocking I/O matters wherever I/O happens).
Rule 4 has two entries because one entry carries exactly one `relation` (spec M2 grammar).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/taxonomy/subsystems.yaml` | CREATE | Initial 14-subsystem taxonomy |
| `docs/decisions/clients-memoryless.md` | CREATE | Seed rule 1 |
| `docs/decisions/history-single-writer.md` | CREATE | Seed rule 2 |
| `docs/decisions/non-blocking-async-stack.md` | CREATE | Seed rule 3 |
| `docs/decisions/http-stack-aiohttp.md` | CREATE | Seed rule 4 |
| `docs/decisions/config-core-navconfig.md` | CREATE | Seed rule 5 |
| `docs/decisions/auth-platform-navigator-auth.md` | CREATE | Seed rule 6 |
| `docs/decisions/tools-live-in-parrot-tools.md` | CREATE | Seed rule 7 |
| `docs/decisions/no-langchain.md` | CREATE | Seed rule 8 |
| `docs/decisions/clients-base-protected.md` | CREATE | Seed rule 9 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py` | CREATE | Seed + taxonomy validity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.parser import parse_frontmatter, FRONTMATTER_KEYS   # verified: parser.py:132, :28
from parrot.knowledge.wiki.ledger.sdd_meta import KNOWN_PROJECTS                        # verified: sdd_meta.py:45
from parrot.knowledge.wiki.decisions.spec_entries import SEED_HEADING, parse_spec_decisions  # created by TASK-4999
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy                            # created by TASK-5000
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py
FRONTMATTER_KEYS = ("id", "title", "status", "supersedes")                 # line 28
def parse_frontmatter(lines) -> tuple[dict[str, str], int, list[DecisionDiagnostic]]   # line 132 — non-flat line ⇒ ADR_PARSE_FAILED (180)
def parse_adr(rel_path: str, text: str, known_prefixes: frozenset[str] | None = None
              ) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]  # line 252

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class DecisionConfig(_Strict):                                             # line 63
    adr_globs: list[str]  # default includes "docs/decisions/**/*.md"      # lines 67-68

# KNOWN_PROJECTS (sdd_meta.py:45) includes: "ai-parrot", "ai-parrot-server", "ai-parrot-tools",
# "ai-parrot-integrations", "ai-parrot-embeddings", "sdd-tooling", "dev-loop", "docs", ...

# Contracts from earlier tasks (spec §3 skeletons)
# spec_entries.py (TASK-4999)
SEED_HEADING = "## Decision Metadata"
def parse_spec_decisions(text: str, *, source_path: str, heading: str = DECISIONS_HEADING
    ) -> tuple[SpecDecisionsBlock | None, list[ConflictWaiver], list[DecisionDiagnostic]]   # seeds: heading=SEED_HEADING
# taxonomy.py (TASK-5000)
class Taxonomy:
    @classmethod
    def load(cls, path: Path) -> "Taxonomy"     # raises DecisionError(TAXONOMY_INVALID)
    def ids(self) -> frozenset[str]
```

Structural pages for every seed target exist in the current plane (verified 2026-10-31 with
`wikitoolkit page <id>`): `dir:packages`, `dir:packages/ai-parrot-server`,
`dir:packages/ai-parrot-tools/src/parrot_tools`, `dir:packages/ai-parrot/src/parrot/clients`,
`file:packages/ai-parrot/src/parrot/clients/base.py`, `file:packages/ai-parrot/src/parrot/bots/abstract.py`.
`AbstractBot.save_conversation_turn` is at `packages/ai-parrot/src/parrot/bots/abstract.py:2606`.

### Does NOT Exist
- ~~`docs/decisions/`, `sdd/taxonomy/`~~ — created here.
- ~~`targets:` / `about:` frontmatter keys~~ — `FRONTMATTER_KEYS` is only `id/title/status/supersedes`; a YAML list in frontmatter is a non-flat `ADR_PARSE_FAILED`. Metadata goes in the `## Decision Metadata` block.
- ~~`parrot.knowledge.ontology.concept_catalog` as the taxonomy~~ — FEAT-159 tenant ontology, not reused.
- ~~an `allows` relation~~ — only `constrains | forbids | requires` (spec Non-Goals).
- ~~`sdd/decisions/approvals.jsonl`~~ — TASK-5013.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/taxonomy/subsystems.yaml", "action": "CREATE"},
    {"path": "docs/decisions/clients-memoryless.md", "action": "CREATE"},
    {"path": "docs/decisions/history-single-writer.md", "action": "CREATE"},
    {"path": "docs/decisions/non-blocking-async-stack.md", "action": "CREATE"},
    {"path": "docs/decisions/http-stack-aiohttp.md", "action": "CREATE"},
    {"path": "docs/decisions/config-core-navconfig.md", "action": "CREATE"},
    {"path": "docs/decisions/auth-platform-navigator-auth.md", "action": "CREATE"},
    {"path": "docs/decisions/tools-live-in-parrot-tools.md", "action": "CREATE"},
    {"path": "docs/decisions/no-langchain.md", "action": "CREATE"},
    {"path": "docs/decisions/clients-base-protected.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#parse_frontmatter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#KNOWN_PROJECTS"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Transcribe, do not invent.** Context/Decision/Consequences text comes from `CLAUDE.md`,
  `.agent/CONTEXT.md` and `.claude/rules/codebase-conventions.md` (sections "Conversation memory",
  "What NOT to Do", "Forbidden — and what to use instead", "Tool-Centric Architecture"). Cite the source
  file in each Context section.
- `docs/decisions/` is inside the default `adr_globs`; the legacy-ingest exclusion of files with a
  `## Decision Metadata` block is TASK-5007's job (PLAN decision 6) — do not add workarounds here.
- `entry_id` / `document_id` charset is `[a-z0-9_-]+` (spec M1 `spec_decision_id`); slugs above comply.
- Every `projects` value in the taxonomy must be a `KNOWN_PROJECTS` member (`Taxonomy.load` rejects
  unknown projects).
- The spec §8 open question on taxonomy granularity: start with the 14 subsystems the spec lists (M10);
  growth is by PR. Record this in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read TASK-5000's `taxonomy.py`: the file shape is `schema_version: 1` + `subsystems:` list + optional `mapping:` (tag → subsystem id) — *why*: the file must load with zero errors.
2. Write `subsystems.yaml` — *why*: seeds reference its ids in `about`.
3. Write the nine seed files from the shared shape below — *why*: one file per rule, approved as one batch (spec §8 seed packaging).
4. Write and run `test_seed_rules.py` — *why*: AC16/AC20 evidence.
5. Commit these 11 files in ONE commit — *why*: TASK-5013 records that commit's sha as the seed batch's approving commit.

### `sdd/taxonomy/subsystems.yaml` (CREATE)
```yaml
# Curated subsystem taxonomy for the decision audit (FEAT-784). Curated by the repo owner via PRs to dev.
# Format fixed by TASK-5000 (schema_version + subsystems + optional mapping: tag -> subsystem id).
schema_version: 1
subsystems:
  - id: memory
    title: Conversation memory
    description: Conversation history storage, rendering and compaction (parrot/memory).
    parent: null
    projects: [ai-parrot]
  - id: clients
    title: LLM clients
    description: AbstractClient and provider wrappers (parrot/clients).
    parent: null
    projects: [ai-parrot]
  # FILL IN: bots, tools, flows, skills, knowledge-wiki, knowledge-graphindex, server, integrations,
  #   config, auth, sdd-tooling, dev-loop — same fields; projects from KNOWN_PROJECTS
  #   (tools → ai-parrot, ai-parrot-tools; server → ai-parrot-server; integrations → ai-parrot-integrations;
  #   sdd-tooling → sdd-tooling; dev-loop → dev-loop; knowledge-* → ai-parrot); parent null unless a
  #   real hierarchy exists (e.g. knowledge-graphindex has no parent subsystem "knowledge" — keep null)
mapping:
  # FILL IN: frontmatter tag -> subsystem id for the common spec tags (e.g. memory: memory, mcp: server,
  #   wiki: knowledge-wiki, sdd: sdd-tooling, dev-loop: dev-loop); every value must be a subsystem id above
  #   — bounded by TASK-5000 validation ("mapping to unknown id" rejected)
  memory: memory
```
**Why**: ids are the `about` axis (spec S7: independent from free-form SDD tags).

### `docs/decisions/<rule-slug>.md` (CREATE ×9 — shared shape; example = rule 1)
````markdown
---
id: ADR-SEED-0001
title: Clients are memory-less
status: accepted
---

## Context

Source: `.agent/CONTEXT.md` § AbstractClient ("Memory-less (FEAT-524)") and § Conversation memory.

## Decision

`AbstractClient` subclasses neither load nor persist conversation history; they receive an already
rendered `history` per call.

## Consequences

`AbstractBot` is the sole owner of history. A client that reads or writes a memory backend violates
this rule.

## Decision Metadata

```yaml
schema_version: 1
document_id: seed-clients-memoryless
entries:
  - id: rule
    statement: AbstractClient subclasses neither load nor persist conversation history.
    relation: forbids
    about: [clients, memory]
    targets: [dir:packages/ai-parrot/src/parrot/clients]
    rationale: FEAT-524 made AbstractBot the single owner of conversation history.
```
````
FILL IN: rules 2–9 with `id: ADR-SEED-0002` … `ADR-SEED-0009`, `document_id: seed-<rule-slug>`, the
relation/about/targets from the Seed rules table, text transcribed from the cited source files — bounded
by AC20 (rule 3 rationale: httpx excluded for stack consistency, not for blocking; aiohttp + asyncio +
uvloop is the standard) and spec M10 rule wording.

**Why**: flat frontmatter keeps `parse_adr`/`parse_frontmatter` happy; the fenced block is the only place
structured metadata may live (spec §6 Does NOT Exist).

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py` (CREATE)
```python
"""FEAT-784 M10: the committed taxonomy and seed rules are valid (AC16, AC20)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.parser import parse_frontmatter
from parrot.knowledge.wiki.decisions.spec_entries import SEED_HEADING, parse_spec_decisions
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy

_REPO_ROOT = Path(__file__).resolve().parents[6]
SEEDS = sorted((_REPO_ROOT / "docs/decisions").glob("*.md"))
EXPECTED = {
    "clients-memoryless", "history-single-writer", "non-blocking-async-stack", "http-stack-aiohttp",
    "config-core-navconfig", "auth-platform-navigator-auth", "tools-live-in-parrot-tools", "no-langchain",
    "clients-base-protected",
}


def test_taxonomy_loads() -> None:
    taxonomy = Taxonomy.load(_REPO_ROOT / "sdd/taxonomy/subsystems.yaml")
    assert len(taxonomy.ids()) == 14


def test_all_nine_seeds_present() -> None:
    assert {p.stem for p in SEEDS} >= EXPECTED


@pytest.mark.parametrize("path", SEEDS, ids=lambda p: p.stem)
def test_seed_parses_and_resolves(path: Path) -> None:
    # FILL IN: parse_frontmatter(text.splitlines()) has no diagnostics and status == "accepted";
    #   parse_spec_decisions(text, source_path=..., heading=SEED_HEADING) yields a block with zero diagnostics and document_id == f"seed-{path.stem}";
    #   every about id ∈ taxonomy.ids(); every target has a sym:/file:/dir: prefix and its path exists
    #   under _REPO_ROOT — bounded by AC20
    raise NotImplementedError


def test_rule3_rationale_states_stack_consistency() -> None:
    text = (_REPO_ROOT / "docs/decisions/non-blocking-async-stack.md").read_text(encoding="utf-8")
    assert "stack consistency" in text and "httpx" in text
```
**Why**: verifies AC20 statically (path existence) so the test runs without a built plane; plane-level
resolution through `TargetResolver` is exercised end-to-end by TASK-5015. `parents[6]` is the repo
root (decisions → wiki → knowledge → tests → ai-parrot → packages → root).

### FILL IN checklist
- [ ] Taxonomy `mapping:` entries (values are subsystem ids)
- [ ] 12 remaining subsystems with KNOWN_PROJECTS mappings
- [ ] Seed files 2–9 transcribed from source docs, rule 3 rationale per AC20
- [ ] `test_seed_parses_and_resolves` body

---

## Acceptance Criteria

- [ ] `sdd/taxonomy/subsystems.yaml` loads through `Taxonomy.load` with 14 subsystems (AC16).
- [ ] Nine seed files parse with zero diagnostics; frontmatter flat; status accepted (AC20).
- [ ] Every seed target path exists on disk and every `about` id is in the taxonomy (AC20).
- [ ] Rule 3 rationale states httpx is excluded for stack consistency, not for blocking (AC20).
- [ ] All 11 files land in one commit (sha recorded by TASK-5013).
- [ ] `ruff check packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_seed_rules.py -q`

---

## Test Specification

See blueprint: `test_taxonomy_loads`, `test_all_nine_seeds_present`, `test_seed_parses_and_resolves`
(one param per seed), `test_rule3_rationale_states_stack_consistency`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Confirm TASK-4999, TASK-5000, TASK-5002 are `done`; read `spec_entries.py` and `taxonomy.py` to confirm the names above.
3. Mark in-progress, write the files, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit the 11 files in a single commit and **push it** (its sha must be reachable for TASK-5013).
5. Close with `scripts/sdd/close_task.sh TASK-5012 sdd-decision-audit verified`; put the seed commit sha in the Completion Note.

---

## Completion Note

*(Agent fills this in when done — include the seed commit sha.)*
