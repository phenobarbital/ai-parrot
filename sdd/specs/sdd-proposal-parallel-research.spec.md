---
type: feature
base_branch: dev
projects:
  - sdd-tooling
tags:
  - sdd
  - proposal
  - brainstorm
  - parallel
  - research
  - sub-agent
  - performance
  - contract-validation
---

# Feature Specification: sdd-proposal-parallel-research

**Feature ID**: FEAT-708
**Date**: 2026-10-20
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.31.0

---

## 1. Motivation & Business Requirements

### Problem Statement

The `/sdd-proposal` research phase (Phase 2) runs as a sequential loop: each
query in the research plan executes one at a time, checking budget limits after
each step. For the `loose` budget profile (100 files, 60 greps, 20 git calls,
depth 3), this can take up to 15 minutes of wall-clock time — most of it
blocked waiting for tool responses.

The three dominant query types (codebase exploration, git history, wiki queries)
are independent: a `grep` for symbol references does not depend on a `git log`
for authorship, and neither depends on a `wikitoolkit query` for architectural
context. Running them in parallel would cut wall-clock time roughly by a factor
of 3, limited only by the slowest lane.

### Goals

- Reduce `default` and `loose` research wall-clock time by ~3x via parallel
  fork dispatch.
- Preserve all existing `--budget` profiles with no breaking changes.
- Maintain the finding file format and Phase 3 synthesis input contract
  unchanged.
- Automatic single-agent fallback for environments without the Agent tool
  (Codex, non-Claude-Code hosts).
- Bound token cost increase to ~1.8x of sequential cost (prompt cache sharing
  between forks).
- Preserve full audit trail of lane-level findings.
- Offload mechanical codebase contract verification (import resolution, file
  existence, signature matching) to inline Haiku-class forks in
  `/sdd-brainstorm` and `/sdd-proposal`, freeing the thinking model for
  creative/analytical work.

### Non-Goals (explicitly out of scope)

- Cross-lane recursive follow-ups (a codebase finding spawning a git query) —
  recorded as notes for synthesis, not acted on. May be revisited in a future
  iteration.
- Custom per-lane budget overrides (`--lane-budget codebase:files_read=80`) —
  the `custom` budget profile always runs sequential (S11).
- Changing the finding file format (`sdd/templates/finding.md`).
- Modifying Phase 3 synthesis or Phase 1 plan generation.
- Contract validation in `/sdd-spec` or `/sdd-task` — those commands already
  have their own verification steps; M7 targets only the upstream exploration
  commands (`/sdd-brainstorm`, `/sdd-proposal`).

---

## 2. Architectural Design

### Overview

Phase 2 gains a **dispatch layer** that wraps the existing sequential iteration
loop. For `default` and `loose` budget profiles (and when the Agent tool is
available), the approved research plan is partitioned into 3 independent query
lanes, each run as a Claude Code fork (`subagent_type: "fork"`). The main agent
remains the **sole state writer** (S1): forks write only finding files to the
shared `${STATE_DIR}/findings/` directory using lane-prefixed IDs; the main
agent aggregates counters, transitions phases, and writes `state.json`.

**Dispatch flow:**

1. **Partition** the approved research plan by query type into 3 lane-local
   query lists, preserving intra-lane dependencies (S4: wiki chains
   `wiki_query` → `wiki_page` by ID stay together).
2. **Allocate** per-lane budgets as fractions of the profile limits, reserving
   ~15% of `max_wall_seconds` for the merge + checkpoint phase (S3).
3. **Probe and dispatch** 3 forks in a single Agent tool call (S7: try-dispatch
   + catch unavailability → sequential fallback).
4. **Collect** fork completion notifications; on partial failure, retry the
   failed lane sequentially.
5. **Merge** lane findings via citation-identity dedup (S6: `(path, symbol,
   line_range)` tuples, not file path alone), producing canonical `F001`+
   findings. Lane originals move to `findings/.audit/` (S5).
6. **Checkpoint** `state.json` with aggregated counters and `research.parallel`
   metadata (S2: per-lane status, query IDs, merge receipt).

**Fallback conditions** (any triggers sequential):
- `--budget=tight` (overhead not justified for 15 files / 120s)
- `--budget=custom` (S11: avoids new per-lane custom semantics)
- `--no-parallel` flag
- Agent tool unavailable (auto-detected via try-dispatch, S7)
- Fork fails to launch (recorded in `state.json`, sequential retry)

**Fork prompt security** (S10): each fork receives a minimal immutable lane
brief containing only the query list, lane budget limits, and the
`${STATE_DIR}` path. Raw source content (Jira, user text) is NOT passed in
fork prompts — forks access `source.md` on disk via the inherited context.

### Component Diagram

```
Phase 1 (plan) ──→ Partition ──→ Fork codebase-lane ──┐
                       │                                │
                       ├──→ Fork git-lane ──────────────┤
                       │                                │
                       └──→ Fork wiki-lane ─────────────┤
                                                        │
                                     Collect ◄──────────┘
                                        │
                                     Merge (dedup)
                                        │
                                     Phase 3 (synthesis)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-proposal.md` §4 | modifies | Phase 2 dispatch logic wraps iteration loop |
| `.agents/skills/sdd-proposal/SKILL.md` | modifies | Twin update — abbreviated dispatch note |
| `.agent/workflows/sdd-proposal.md` | modifies | Legacy workflow twin (S8) |
| `sdd/templates/state.schema.json` | extends | Optional `research.parallel` in research record |
| `sdd/templates/finding.md` | unchanged | Finding format preserved |
| `sdd/templates/synthesis.prompt.md` | unchanged | Reads canonical `F001`+ findings |
| `sdd/templates/research_plan.prompt.md` | extends | Partitioning metadata for plan queries |
| Claude Code Agent tool | uses | `subagent_type: "fork"` for parallel dispatch |
| `.claude/commands/sdd-brainstorm.md` §4 | modifies | Inline Haiku fork for Code Context verification |
| `.claude/commands/sdd-brainstorm.md` §10 | modifies | Collect fork results before commit |

### Data Models

```python
# Per-lane budget allocation (computed by the dispatch layer)
# Not a Pydantic model — computed inline in the skill command text
lane_budget = {
    "codebase": {"files_read": int(0.6 * max_files), "grep_calls": int(0.8 * max_greps), "git_calls": 0, "depth": max_depth},
    "git":      {"files_read": int(0.2 * max_files), "grep_calls": 0, "git_calls": max_git, "depth": 1},
    "wiki":     {"files_read": int(0.2 * max_files), "grep_calls": int(0.2 * max_greps), "git_calls": 0, "depth": max_depth},
}
# Wall-clock per lane: int(0.85 * max_wall_seconds)
# Reserved merge window: max_wall_seconds - max(lane_wall_seconds)
```

```json
// state.json extension — research.parallel (optional, new)
{
  "parallel": {
    "enabled": true,
    "fallback_reason": null,
    "lanes": {
      "codebase": {
        "status": "completed",
        "started_at": "2026-10-20T12:00:00Z",
        "completed_at": "2026-10-20T12:00:45Z",
        "duration_seconds": 45,
        "findings_count": 12,
        "queries_executed": 18,
        "queries_skipped": 0,
        "error": null
      },
      "git": { "...": "same shape" },
      "wiki": { "...": "same shape" }
    },
    "merge": {
      "started_at": "2026-10-20T12:00:50Z",
      "completed_at": "2026-10-20T12:00:55Z",
      "input_count": 25,
      "output_count": 18,
      "merged_count": 7,
      "audit_dir": "findings/.audit"
    }
  }
}
```

### New Public Interfaces

No new public Python interfaces. Changes are confined to SDD skill command
files (Markdown) and the state schema (JSON Schema). The dispatch and merge
logic live entirely within the skill command text as agent instructions.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Dispatch Logic | yes | Query partitioning rules, fork prompt template, fallback conditions — all decided | — |
| M2: Budget Allocation | yes | Per-lane fraction table, rounding rules, reserved merge window — all decided | — |
| M3: Finding Merge | yes | Citation-identity dedup algorithm, canonical renumbering, audit directory — all decided | — |
| M4: State Schema Extension | yes | Optional `parallel` object shape — schema defined above | — |
| M5: Twin-File Sync | yes | Update `.agents/skills/` + `.agent/workflows/` twins — mechanical | — |
| M6: Tests | yes | Test invariants enumerated in §4 | — |
| M7: Contract Validation Forks | yes | Haiku fork template, claim extraction, report schema — all decided | — |

### Module 1: Dispatch Logic (M1)
- **Path**: `.claude/commands/sdd-proposal.md` (§4, lines 199–240)
- **Responsibility**: Replace the sequential iteration loop with a dispatch
  layer that partitions the research plan, launches 3 forks, collects results,
  and handles fallback.
- **Depends on**: M2 (budget allocation), M4 (state schema)
- **Interface Skeleton**:
  The dispatch layer is procedural Markdown instructions, not a Python class.
  Key decision points:
  - Partition: group plan queries by `type` field into `codebase_queries`
    (`grep`, `glob`, `read`, `tree`), `git_queries` (`git_log`), and
    `wiki_queries` (`wiki_query`, `wiki_page`, `wiki_related`). Preserve
    `parent_id` chains within each lane (S4).
  - Probe: attempt Agent tool dispatch; on error, fall back to sequential
    with `fallback_reason` recorded.
  - Fork prompt: minimal lane brief — query list (as JSON), lane budget
    limits, `${STATE_DIR}` path, lane prefix (`FC`/`FG`/`FW`). No raw
    source text (S10).
  - Collect: wait for all 3 fork notifications. On partial failure: preserve
    completed lanes' findings, retry failed lane's queries sequentially.
  - Cross-lane follow-ups: when a fork's finding suggests a query type
    belonging to another lane, record it as a `## Notes` entry in the finding
    with `[cross-lane: type=<type>, intent=<text>]`. The synthesis agent can
    surface these as unknowns.

### Module 2: Budget Allocation (M2)
- **Path**: `.claude/commands/sdd-proposal.md` (§1, near line 96–102)
- **Responsibility**: Compute per-lane budget fractions from the profile
  limits and add `--no-parallel` flag documentation.
- **Depends on**: none
- **Interface Skeleton**:
  - Per-lane allocation table (from brainstorm, refined by S3):
    | Lane | files_read | grep_calls | git_calls | depth | wall_seconds |
    |------|--------:|--------:|------:|------:|--------:|
    | codebase | `floor(0.60 * profile)` | `floor(0.80 * profile)` | 0 | profile | `floor(0.85 * profile)` |
    | git | `floor(0.20 * profile)` | 0 | `1.00 * profile` | 1 | `floor(0.85 * profile)` |
    | wiki | `floor(0.20 * profile)` | `floor(0.20 * profile)` | 0 | profile | `floor(0.85 * profile)` |
  - Rounding: `floor()` for all fractions — never exceed the profile limit.
  - Merge window: `max_wall_seconds - floor(0.85 * max_wall_seconds)` = 15%
    of profile deadline, reserved for join + dedup + checkpoint.
  - Unused lane quota is NOT reclaimable (S3) — keeps accounting simple.
  - `custom` profile always runs sequential (S11).

### Module 3: Finding Merge (M3)
- **Path**: `.claude/commands/sdd-proposal.md` (new subsection after §4b)
- **Responsibility**: Deduplicate lane findings into canonical `F001`+ findings
  for Phase 3, preserving distinct symbols.
- **Depends on**: M1 (dispatch collects findings)
- **Interface Skeleton**:
  - Dedup by citation identity (S6): group findings by `(path, symbol,
    line_range)` tuples from their `## Citations` sections.
  - When two findings share the same `(path, symbol)` with overlapping line
    ranges: merge their citations (union of ranges), concatenate summaries,
    keep the deeper `depth` value, combine `## Notes`.
  - When two findings reference the same file but different symbols: keep
    both as separate canonical findings.
  - Renumber merged findings sequentially: `F001`, `F002`, ...
  - Move lane originals (`FC-*`, `FG-*`, `FW-*`) to `findings/.audit/`.
  - Validate: no duplicate `(path, symbol)` in canonical set; canonical IDs
    are sequential with no gaps.
  - Report: `input_count`, `output_count`, `merged_count` in `state.json`.

### Module 4: State Schema Extension (M4)
- **Path**: `sdd/templates/state.schema.json` (inside `research` properties, line 108)
- **Responsibility**: Add optional `parallel` object to the research
  phase_record for audit and resume.
- **Depends on**: none
- **Interface Skeleton**:
  ```json
  "parallel": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "enabled": {"type": "boolean"},
      "fallback_reason": {"type": ["string", "null"]},
      "lanes": {
        "type": "object",
        "properties": {
          "codebase": {"$ref": "#/$defs/lane_record"},
          "git":      {"$ref": "#/$defs/lane_record"},
          "wiki":     {"$ref": "#/$defs/lane_record"}
        }
      },
      "merge": {
        "type": "object",
        "properties": {
          "started_at": {"type": "string", "format": "date-time"},
          "completed_at": {"type": "string", "format": "date-time"},
          "input_count": {"type": "integer", "minimum": 0},
          "output_count": {"type": "integer", "minimum": 0},
          "merged_count": {"type": "integer", "minimum": 0},
          "audit_dir": {"type": "string"}
        }
      }
    }
  }
  ```
  New `$defs/lane_record`:
  ```json
  "lane_record": {
    "type": "object",
    "properties": {
      "status": {"enum": ["pending", "running", "completed", "failed"]},
      "started_at": {"type": ["string", "null"], "format": "date-time"},
      "completed_at": {"type": ["string", "null"], "format": "date-time"},
      "duration_seconds": {"type": ["number", "null"], "minimum": 0},
      "findings_count": {"type": "integer", "minimum": 0},
      "queries_executed": {"type": "integer", "minimum": 0},
      "queries_skipped": {"type": "integer", "minimum": 0},
      "error": {"type": ["string", "null"]}
    }
  }
  ```

### Module 5: Twin-File Sync (M5)
- **Path**: `.agents/skills/sdd-proposal/SKILL.md`, `.agent/workflows/sdd-proposal.md`
- **Responsibility**: Update the two twin files to reflect the new dispatch
  logic, `--no-parallel` flag, and per-lane budget note.
- **Depends on**: M1, M2 (content to sync)
- **Interface Skeleton**:
  - `.agents/skills/sdd-proposal/SKILL.md`: add `--no-parallel` to the
    invocation line (line 20), add one-line parallel dispatch note under
    `5. Execute research:` (line 88), add per-lane allocation note under
    the budget table (line 59).
  - `.agent/workflows/sdd-proposal.md`: mirror the same changes as the
    `.agents/skills/` twin, adapted to the workflow format.

### Module 6: Tests (M6)
- **Path**: `tests/sdd_scripts/` (new file + existing twin parity)
- **Responsibility**: Test orchestration invariants (S9) and extend twin
  parity coverage (S8).
- **Depends on**: M1, M2, M3, M4, M7
- **Interface Skeleton**:
  - New `tests/sdd_scripts/test_proposal_parallel.py` — unit tests for:
    query partitioning (type-based split preserves intra-lane parent_id chains),
    budget allocation (floor rounding, merge window, custom=sequential),
    dedup logic (citation identity, distinct symbols preserved, canonical
    renumbering), state schema validation (parallel object optional,
    lane_record shape).
  - New `tests/sdd_scripts/test_contract_validation.py` — unit tests for
    M7's claim extraction and report merging.
  - Extend `tests/sdd_scripts/test_command_twin_parity.py` to include
    `sdd-proposal` in the parity check (S8).

### Module 7: Contract Validation Forks (M7)
- **Path**: `.claude/commands/sdd-brainstorm.md` (§4, line 121),
  `.claude/commands/sdd-proposal.md` (between §4b and §5, line ~240)
- **Responsibility**: Offload mechanical codebase contract verification to
  inline Haiku-class forks in `/sdd-brainstorm` and `/sdd-proposal`.
  The fork runs `grep -n`, `test -e`, and targeted `read` to verify every
  claim (import path, file path, class signature, method name) the main
  agent intends to include in Code Context or findings citations. Returns
  a structured JSON report so the main agent can mark references as
  `verified` / `stale` / `missing` without burning thinking-model tokens
  on mechanical checks.
- **Depends on**: none (independent of M1–M6; touches different sections of
  `sdd-proposal.md` and a different command file entirely)
- **Interface Skeleton**:

  **Claim types** (what the fork verifies):
  | Claim | Verification | Tool |
  |---|---|---|
  | Import path (`from parrot.X import Y`) | `grep -rn "class Y\|def Y\|Y =" packages/*/src/` + `test -e` on module path | Bash |
  | File path (`parrot/tools/base.py:42`) | `test -e` + `wc -l` (line exists) | Bash |
  | Class/method signature (`class Foo(Bar)`) | `grep -n "class Foo" <path>` → read surrounding lines | Bash + Read |
  | "Does NOT exist" claim | `grep -rn "<symbol>" packages/*/src/` returns empty | Bash |

  **Fork dispatch pattern** (same for both commands):
  ```
  Agent({
    subagent_type: "fork",
    model: "haiku",
    name: "contract-validator",
    description: "Verify codebase claims",
    prompt: "<claim-list as JSON> + verification instructions"
  })
  ```
  The fork receives a JSON array of claims:
  ```json
  [
    {"type": "import", "statement": "from parrot.tools import AbstractTool", "expected_at": "packages/ai-parrot/src/parrot/tools/__init__.py"},
    {"type": "file", "path": "packages/ai-parrot/src/parrot/tools/base.py", "line": 42},
    {"type": "signature", "path": "packages/ai-parrot/src/parrot/bots/agent.py", "symbol": "Agent", "expected": "class Agent(AbstractBot):"},
    {"type": "absent", "symbol": "parrot.tools.NonExistent", "search_root": "packages/ai-parrot/src/"}
  ]
  ```
  The fork returns a JSON report:
  ```json
  {
    "verified": [{"claim_index": 0, "evidence": "parrot/tools/__init__.py:15"}],
    "stale": [{"claim_index": 2, "evidence": "agent.py:88 — actual: class Agent(AbstractBot, ToolMixin):"}],
    "missing": [{"claim_index": 1, "evidence": "file exists but has only 38 lines"}]
  }
  ```

  **In `/sdd-brainstorm` (Step 4 → Step 5 boundary):**
  1. Main agent scans the codebase, builds a candidate reference list.
  2. Fork the Haiku validator with the claim list.
  3. Main agent proceeds to Step 5 (Generate Options) — creative work that
     does not depend on verification results.
  4. Before Step 10 (Save and Commit), collect fork results.
  5. Update Code Context: mark verified references with line numbers from
     the fork's evidence; drop `missing` references; flag `stale` with
     corrected signatures.

  **In `/sdd-proposal` (Phase 2 → Phase 3 boundary):**
  1. After Phase 2 research completes (all findings collected), extract
     all `## Citations` from `${STATE_DIR}/findings/*.md`.
  2. Fork the Haiku validator with the citation claim list.
  3. Main agent begins Phase 3 synthesis input assembly (Step 5a) — can
     proceed in parallel since the synthesis prompt is being constructed.
  4. Before Step 5b (Run synthesis prompt), collect fork results.
  5. Annotate findings whose citations are stale/missing: add a
     `[citation-check: stale|missing]` tag in the finding's `## Notes`
     so the synthesis agent can weigh evidence accordingly.

  **Fallback**: if Agent tool is unavailable or fork fails, the main agent
  runs the verification inline (current behavior — no regression).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_partition_by_type` | M1 | Queries split by type into 3 lanes |
| `test_partition_preserves_parent_chains` | M1 | wiki_query → wiki_page chains stay in wiki lane |
| `test_partition_cross_lane_followup_recorded` | M1 | Cross-lane follow-up noted, not dispatched |
| `test_budget_allocation_floor_rounding` | M2 | Fractions use floor(), never exceed profile |
| `test_budget_merge_window_reserved` | M2 | 15% of wall_seconds reserved for merge |
| `test_budget_custom_forces_sequential` | M2 | custom profile → sequential execution |
| `test_budget_tight_forces_sequential` | M2 | tight profile → sequential execution |
| `test_dedup_same_symbol_merged` | M3 | Same (path, symbol) with overlapping ranges → one finding |
| `test_dedup_different_symbols_preserved` | M3 | Same path, different symbols → separate findings |
| `test_dedup_canonical_renumbering` | M3 | Output IDs are F001..F<N> sequential |
| `test_dedup_audit_directory` | M3 | Lane originals moved to findings/.audit/ |
| `test_state_parallel_optional` | M4 | state.json valid with and without parallel field |
| `test_state_lane_record_shape` | M4 | lane_record schema validates correctly |
| `test_twin_parity_sdd_proposal` | M5 | sdd-proposal included in twin parity check |
| `test_claim_extraction_imports` | M7 | Import claims extracted from Code Context references |
| `test_claim_extraction_signatures` | M7 | Signature claims extracted with expected patterns |
| `test_claim_extraction_absent` | M7 | "Does NOT exist" entries produce absent-type claims |
| `test_report_merge_verified` | M7 | Verified claims update references with evidence lines |
| `test_report_merge_stale_corrected` | M7 | Stale claims update signatures in Code Context |
| `test_report_merge_missing_dropped` | M7 | Missing claims remove references from output |
| `test_fallback_inline_verification` | M7 | Fork unavailable → main agent verifies inline |

### Integration Tests
| Test | Description |
|---|---|
| `test_sequential_fallback_no_agent` | Full Phase 2 runs sequentially when Agent unavailable |
| `test_parallel_default_profile` | Dispatch + merge produces canonical findings for default budget |
| `test_contract_fork_brainstorm_flow` | Haiku fork verifies Code Context claims before commit |
| `test_contract_fork_proposal_flow` | Haiku fork verifies finding citations before synthesis |

### Validation Contract

tests:
- tests/sdd_scripts/test_proposal_parallel.py
- tests/sdd_scripts/test_contract_validation.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def sample_research_plan():
    """Research plan with mixed query types for partitioning tests."""
    return {
        "queries": [
            {"id": "Q001", "type": "grep", "intent": "find tool references", "priority": 1},
            {"id": "Q002", "type": "wiki_query", "intent": "architecture overview", "priority": 2},
            {"id": "Q003", "type": "wiki_page", "parent_id": "Q002", "intent": "drill into page", "priority": 3},
            {"id": "Q004", "type": "git_log", "intent": "recent changes", "priority": 4},
            {"id": "Q005", "type": "read", "intent": "read module", "priority": 5},
        ]
    }

@pytest.fixture
def sample_lane_findings(tmp_path):
    """Lane-prefixed finding files for merge tests."""
    # Creates FC-001, FC-002, FG-001, FW-001 finding files
    ...

@pytest.fixture
def sample_budget_profile():
    return {"profile": "default", "max_files_read": 40, "max_grep_calls": 25,
            "max_git_calls": 10, "max_depth": 2, "max_wall_seconds": 300}

@pytest.fixture
def sample_contract_claims():
    """Claim list for contract validation fork tests."""
    return [
        {"type": "import", "statement": "from parrot.tools import AbstractTool",
         "expected_at": "packages/ai-parrot/src/parrot/tools/__init__.py"},
        {"type": "file", "path": "packages/ai-parrot/src/parrot/tools/base.py", "line": 42},
        {"type": "signature", "path": "packages/ai-parrot/src/parrot/bots/agent.py",
         "symbol": "Agent", "expected": "class Agent(AbstractBot):"},
        {"type": "absent", "symbol": "parrot.tools.NonExistent",
         "search_root": "packages/ai-parrot/src/"},
    ]

@pytest.fixture
def sample_validation_report():
    """Fork output report for merge tests."""
    return {
        "verified": [{"claim_index": 0, "evidence": "parrot/tools/__init__.py:15"}],
        "stale": [{"claim_index": 2, "evidence": "agent.py:88 — actual: class Agent(AbstractBot, ToolMixin):"}],
        "missing": [{"claim_index": 1, "evidence": "file exists but has only 38 lines"}],
    }
```

---

## 5. Acceptance Criteria

- [x] Existing budget profiles (tight/default/loose) work unchanged — *Resolved in brainstorm*: tight stays sequential, default/loose parallelize
- [ ] `default` and `loose` research wall-clock time reduced by ≥2x vs sequential baseline
- [ ] `tight` profile runs sequentially (no fork overhead)
- [ ] `custom` profile runs sequentially (S11)
- [ ] `--no-parallel` flag forces sequential execution
- [ ] Automatic fallback to sequential when Agent tool is unavailable
- [ ] Finding file format (`sdd/templates/finding.md`) unchanged
- [ ] Phase 3 synthesis receives only canonical `F001`+ findings
- [ ] Lane-prefixed originals preserved in `findings/.audit/`
- [ ] `state.json` schema validates with and without `research.parallel`
- [ ] Cross-lane follow-ups recorded as notes, not dropped
- [ ] Fork prompts contain no raw source text (S10)
- [ ] All 3 twin files updated consistently (S8)
- [ ] Twin parity test includes `sdd-proposal` (S8)
- [ ] All unit tests pass
- [ ] Resume after partial-lane failure produces correct results (S2)
- [ ] Dedup preserves distinct symbols from same file (S6)
- [ ] `/sdd-brainstorm` Step 4 dispatches a Haiku fork for Code Context verification
- [ ] `/sdd-proposal` dispatches a Haiku fork for citation verification between Phase 2 and Phase 3
- [ ] Contract fork returns structured JSON report (verified/stale/missing)
- [ ] Stale signatures are corrected in Code Context before commit
- [ ] Missing references are dropped (brainstorm) or tagged (proposal)
- [ ] Fork fallback to inline verification when Agent tool unavailable

---

## 6. Codebase Contract

> Verified against commit: `HEAD` of dev as of 2026-10-20.

### Verified Imports

```python
# No Python imports — this feature modifies only Markdown/JSON skill files
```

### Existing Class Signatures

```python
# No Python classes modified — changes are in SDD skill command files
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Dispatch logic | Phase 2 iteration loop | Wraps existing sequential loop | `.claude/commands/sdd-proposal.md:199` |
| Per-lane budget | Budget table | Adds allocation note | `.claude/commands/sdd-proposal.md:98` |
| Parallel state | Research phase_record | Extends with optional `parallel` | `sdd/templates/state.schema.json:103` |
| Twin sync | Skill twin | Mirrors dispatch changes | `.agents/skills/sdd-proposal/SKILL.md:88` |
| Twin sync | Workflow twin | Mirrors dispatch changes | `.agent/workflows/sdd-proposal.md` |

### Does NOT Exist (Anti-Hallucination)

- ~~`merge_findings()` function~~ — no existing merge/dedup logic in any SDD skill
- ~~`subagent_type: "fork"` in any SDD skill~~ — this is the first skill to use forks
- ~~`research.parallel` in `state.schema.json`~~ — does not exist; must be added
- ~~`sdd/templates/lane.md`~~ — no lane template; lanes use `finding.md`
- ~~`findings/.audit/` directory~~ — does not exist; created by the merge step
- ~~"Phase 2" text in SKILL.md~~ — the twin uses "5. Execute research:" (line 88), not "Phase 2"
- ~~contract validation in any SDD skill~~ — no existing SDD skill dispatches a verification fork; all contract checks are inline today
- ~~`model: "haiku"` in any Agent fork call~~ — no existing skill overrides the fork model

### Edit Sites (Blueprint Anchors)

Verified against: `HEAD` of dev, 2026-10-20.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `.claude/commands/sdd-proposal.md` | MODIFY | `### 4. Phase 2 — Execute Research` | `:199` | 1 |
| `.claude/commands/sdd-proposal.md` | MODIFY | `#### 4a. Iteration loop` | `:201` | 1 |
| `.claude/commands/sdd-proposal.md` | MODIFY | `For each query in the approved plan, in priority order:` | `:203` | 1 |
| `.claude/commands/sdd-proposal.md` | MODIFY | `#### 4b. Stop conditions` | `:232` | 1 |
| `.claude/commands/sdd-proposal.md` | MODIFY | `` \| `--budget`  \| files_read \| grep_calls \| `` | `:98` | 1 |
| `.claude/commands/sdd-proposal.md` | MODIFY | `- \`budget\`: per \`--budget\` profile (see table below)` | `:96` | 1 |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | `$sdd-proposal <source> [--mode=...] [--budget=...]` | `:20` | 1 |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | `5. Execute research:` | `:88` | 1 |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | `` \| Profile \| Files \| Greps \| Git \| Depth \| Seconds \| `` | `:59` | 1 |
| `.agent/workflows/sdd-proposal.md` | MODIFY | (verify at task time — not researched in this spec) | — | — |
| `sdd/templates/state.schema.json` | MODIFY | `"research": {` | `:103` | 1 |
| `tests/sdd_scripts/test_command_twin_parity.py` | MODIFY | (verify at task time — add sdd-proposal to parity list) | — | — |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | `### 4. Research the Codebase & Build Code Context` | `:121` | 1 |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | `### 5. Generate Options` | `:142` | 1 |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | `### 10. Save and Commit` | `:180` | 1 |
| `tests/sdd_scripts/test_proposal_parallel.py` | CREATE | — | — | — |
| `tests/sdd_scripts/test_contract_validation.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Parent is sole state writer** (S1): forks write only finding files. The
  parent reads fork completion outputs, aggregates `consumed` counters from
  the query counts each fork reports, and writes all `state.json` transitions.
- **Capability probe via try-dispatch** (S7): attempt the Agent tool call
  first; catch the error response and fall back to sequential. Do not probe
  with a separate test call.
- **Minimal fork prompts** (S10): the fork prompt carries the query list (as
  compact JSON), lane budget limits, `${STATE_DIR}` path, and lane ID prefix.
  It does NOT include raw source text, Jira content, or the synthesis prompt.
  Forks access `source.md` and `research_plan.json` on disk via inherited
  context.
- **Idempotent resume** (S2): on resume, check which lane-prefixed findings
  exist on disk. A lane with findings but no `completed_at` in `state.json`
  is treated as potentially incomplete — re-dispatch it. A lane with both
  findings and `completed_at` is skipped.

### Known Risks / Gotchas

- **Token cost**: 3 forks × full context = ~3x input tokens. Mitigated by
  Claude Code's prompt cache sharing (forks share the parent's cache), but
  the actual cost depends on cache hit rate. Measure empirically on first
  runs. Expected: ~1.8x effective cost.
- **Cross-lane follow-ups lost**: a codebase finding that suggests a git query
  is recorded as a note but never acted on. The synthesis agent may flag this
  as an unknown — this is acceptable for v1.
- **Concurrent filesystem writes**: 3 forks write to the same `findings/`
  directory. File naming (lane-prefixed: `FC-*`, `FG-*`, `FW-*`) prevents
  collisions. No lock needed — each fork writes only its own prefix.
- **Fork failure modes**: a fork can timeout, crash, or produce malformed
  findings. The dispatch logic retries the failed lane sequentially. If the
  retry also fails, mark the lane as failed and proceed with available
  findings (degraded but not blocked).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| Claude Code Agent tool | built-in | `subagent_type: "fork"` for parallel dispatch |

No new Python packages.

---

## 8. Open Questions

- [ ] Should cross-lane recursive follow-ups be supported in a future iteration? (e.g. codebase finding spawns a git query) — *Owner: Jesus*
- [ ] Should the dedup merge preserve both findings verbatim when the file-path match has different symbols (same file, different functions)? — *Owner: Jesus*
  - Note: S6 recommends citation-identity dedup `(path, symbol, line_range)` — the spec adopts this, which inherently preserves distinct symbols. This question is resolved by the design research.
- [ ] Should `--budget=custom` support user-specified per-lane limits (e.g. `--lane-budget codebase:files_read=80`)? — *Owner: Jesus*
  - Note: S11 recommends keeping custom sequential for now. Adopted.
- [ ] What is the measured prompt-cache hit rate for forks of `/sdd-proposal`? Need empirical data to validate the 1.8x cost estimate. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted
> brainstorm**. Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-708/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Parent sole state writer (architecture) | CONFIRM | Forks write only findings; parent aggregates counters — prevents concurrent state.json corruption | §2 Overview, §7 Patterns |
| S2 | Explicit lane state + idempotent resume (risk) | CONFIRM | Per-lane status with query IDs needed for safe partial-lane retry | §2 Data Models, §3 M4 |
| S3 | Global deadline + quota semantics (architecture) | CONFIRM | Floor rounding, 15% merge window, no reclaimable quota | §2 Overview, §3 M2 |
| S4 | Partition dependency-safe queries (architecture) | CONFIRM | Wiki chains (query→page) stay in wiki lane; cross-lane follow-ups recorded as notes | §2 Overview, §3 M1 |
| S5 | Lane findings out of Phase 3 input (api) | CONFIRM | Lane originals to findings/.audit/; canonical F001+ only | §2 Overview, §3 M3 |
| S6 | Dedup by citation identity not file path (alternative) | CONFIRM | Upgrades file-path-only to (path, symbol, line_range) — preserves distinct symbols | §2 Overview, §3 M3 |
| S7 | Capability probe via try-dispatch (risk) | CONFIRM | Attempt Agent dispatch + catch error → sequential fallback | §3 M1, §7 Patterns |
| S8 | Update .agent/workflows twin (risk) | CONFIRM | .agent/workflows/sdd-proposal.md verified — must stay in sync | §3 M5 |
| S9 | Test orchestration invariants (testing) | CONFIRM | Tests for partitioning, quota, resume, dedup | §4 Tests |
| S10 | Minimal lane brief, no raw source (risk) | CONFIRM | Fork prompt = query list + budget; no user/Jira content | §7 Patterns, §7 Risks |
| S11 | Keep custom budget sequential (api) | CONFIRM | Avoids new per-lane custom semantics | §3 M2 |

Summary: **11** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: per-spec — one feature worktree for FEAT-708. All modules
  modify a small set of Markdown/JSON files; no Python compilation needed.
- **Module dependency graph**: M4 (schema) has no deps → M2 (budget) has no
  deps → M7 (contract forks) has no deps → M1 (dispatch) depends on M2, M4
  → M3 (merge) depends on M1 → M5 (twins) depends on M1, M2 →
  M6 (tests) depends on M1, M2, M3, M4, M7. M4, M2, and M7 can all run
  concurrently. M1 requires M2 and M4. M5 is independent of M3 and M7.
- **Shared files**: `.claude/commands/sdd-proposal.md` is modified by M1, M2,
  and M7 (M7 touches §4b→§5 boundary, M1/M2 touch §4a; serialized via
  dependency edge for M1/M2, M7 is independent — different section).
  `.claude/commands/sdd-brainstorm.md` is modified only by M7.
- **Exclusive resources**: none — no migrations, no lockfiles.
- **Cross-feature dependencies**: none — no in-flight features modify these files.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-20 | Jesus Lara | Initial draft from brainstorm + codex design research (11/11 confirmed) |
| 0.2 | 2026-10-20 | Jesus Lara | Add M7 — Contract Validation Forks (inline Haiku forks in sdd-brainstorm/sdd-proposal) |
