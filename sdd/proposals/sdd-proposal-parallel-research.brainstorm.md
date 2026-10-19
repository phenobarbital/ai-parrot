---
type: feature
base_branch: dev
projects:
  - sdd-tooling
tags:
  - sdd
  - proposal
  - parallel
  - research
  - sub-agent
---

# Brainstorm: sdd-proposal-parallel-research

**Date**: 2026-10-20
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The `/sdd-proposal` research phase (Phase 2) runs as a sequential loop: each
query in the research plan executes one at a time, checking budget limits after
each step. For the `loose` budget profile (100 files, 60 greps, 20 git calls,
depth 3), this can take up to 15 minutes of wall-clock time — most of it
blocked waiting for tool responses.

The three dominant query types (codebase exploration, git history, wiki
queries) are **independent**: a `grep` for symbol references does not depend on
a `git log` for authorship, and neither depends on a `wikitoolkit query` for
architectural context. Running them in parallel would cut wall-clock time
roughly by a factor of 3, limited only by the slowest lane.

This affects developers waiting for research output before they can proceed to
`/sdd-spec`, especially on large or unfamiliar codebases where `loose` is the
appropriate budget.

## Constraints & Requirements

- Must preserve the existing budget profiles (`tight`, `default`, `loose`) —
  no breaking changes to the `--budget` flag semantics.
- `tight` profile (15 files, 120s) stays sequential — fork overhead is not
  justified at this scale.
- The twin-file structure (`.claude/commands/sdd-proposal.md` +
  `.agents/skills/sdd-proposal/SKILL.md`) must be updated consistently.
- The finding file format (`sdd/templates/finding.md`) is unchanged.
- State schema (`sdd/templates/state.schema.json`) additions must be
  backwards-compatible (new optional fields only).
- Single-agent fallback must work automatically when the `Agent` tool is
  unavailable (Codex, non-Claude-Code hosts).
- Wiki queries remain budget-free (they don't count against any limit).
- Token cost increase should be bounded — per-lane budget at ~60% of profile
  limits, not full duplication.
- Merged findings must feed the existing Phase 3 synthesis input format
  (`<finding id="F00N">` tags) unchanged.

---

## Options Explored

### Option A: Fork-per-Lane with Shared Findings Directory

Each of the 3 research lanes runs as a Claude Code fork (`subagent_type:
"fork"`). Forks inherit the full conversation context (including the resolved
source and approved research plan). Each fork writes findings to the existing
`${STATE_DIR}/findings/` directory using lane-prefixed IDs:

- **Codebase lane**: `FC-001`, `FC-002`, ... — handles `grep`, `glob`, `read`,
  `tree` queries.
- **Git lane**: `FG-001`, `FG-002`, ... — handles `git_log` queries.
- **Wiki lane**: `FW-001`, `FW-002`, ... — handles `wiki_query`, `wiki_page`,
  `wiki_related` queries.

The main agent waits for all 3 forks to complete, then runs a **dedup pass**:
scans all findings, groups by file path, and merges overlapping citations into
consolidated `F001`...`F<NNN>` findings for synthesis. The fork findings are
kept as-is for audit.

The research plan (Phase 1 output) is partitioned by query type — each fork
receives only its slice of the plan.

**Dispatch logic** (in the main agent, replacing the sequential loop at
sdd-proposal.md line 199):

```
if budget.profile == "tight" OR Agent tool unavailable:
    run_sequential(plan)           # existing behavior
else:
    codebase_queries = [q for q in plan if q.type in {grep, glob, read, tree}]
    git_queries      = [q for q in plan if q.type in {git_log}]
    wiki_queries     = [q for q in plan if q.type in {wiki_query, wiki_page, wiki_related}]

    # Launch 3 forks in ONE message (parallel execution)
    fork("codebase-lane", queries=codebase_queries, budget=lane_budget(budget, "codebase"))
    fork("git-lane",      queries=git_queries,      budget=lane_budget(budget, "git"))
    fork("wiki-lane",     queries=wiki_queries,      budget=lane_budget(budget, "wiki"))

    # Wait for all 3, then merge
    dedup_findings_by_path(STATE_DIR / "findings/")
```

**Per-lane budget allocation** (`lane_budget()`):

| Lane | files_read | grep_calls | git_calls | depth |
|------|--------:|--------:|------:|------:|
| codebase | 60% of profile | 80% of profile | 0 | profile depth |
| git | 20% of profile | 0 | 100% of profile | 1 |
| wiki | 20% of profile | 20% of profile | 0 | profile depth |

Wall-clock limit per lane: `0.7 * profile.wall_seconds` (lanes run in parallel
so the total wall-clock is max(lane_times), not sum).

**Dedup algorithm** (file-path based):
1. Scan all `F[CGW]-<NNN>-*.md` files in `findings/`.
2. Build a map: `{file_path: [finding_id, ...]}`.
3. For each file path with multiple findings: merge their citations (union of
   line ranges), concatenate summaries, keep the deepest depth.
4. Write canonical `F001`...`F<NNN>` findings (renumbered sequentially).
5. Move lane-prefixed originals to `findings/.audit/` for traceability.

State tracking: `state.json` gains an optional `research.parallel` object:
```json
{
  "parallel": {
    "enabled": true,
    "lanes": {
      "codebase": {"status": "completed", "findings_count": 12, "duration_seconds": 45},
      "git":      {"status": "completed", "findings_count": 5,  "duration_seconds": 30},
      "wiki":     {"status": "completed", "findings_count": 8,  "duration_seconds": 20}
    },
    "dedup": {"input_count": 25, "output_count": 18, "merged_count": 7}
  }
}
```

Pros:
- Simplest architecture: forks write to the same directory, dedup is a
  post-processing step.
- Forks inherit the full context (source, plan, conversation) for free.
- The finding format is unchanged — synthesis sees canonical `F001`+ files.
- Audit trail: original lane findings preserved in `findings/.audit/`.
- Clean fallback: `tight` or no-Agent just runs the existing sequential code.
- No new dependencies or infrastructure.

Cons:
- 3 forks = ~3x token input cost (each loads the full conversation context).
  Mitigated by prompt cache sharing (forks share the parent's cache).
- Dedup is heuristic (file-path based) — two findings about the same file
  from different angles might lose nuance when merged.
- Recursive follow-ups within a fork can't cross lanes (a codebase finding
  can't spawn a git query).
- First-ever fork usage in an SDD skill — no precedent to follow.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| Claude Code `Agent` tool | Fork dispatch | Built-in, `subagent_type: "fork"` |
| `sdd/templates/finding.md` | Finding file format | Existing, unchanged |
| `sdd/templates/state.schema.json` | State persistence | Extended with optional `parallel` field |

Existing Code to Reuse:
- `.claude/commands/sdd-proposal.md:199-240` — Phase 2 iteration loop (each fork runs this same loop on its query slice)
- `.claude/commands/sdd-proposal.md:244-250` — Phase 3 finding concatenation (unchanged, reads canonical `F001`+ files)
- `.claude/commands/sdd-proposal.md:432-453` — Resume logic (extended to handle mid-fork interruption)
- `sdd/templates/finding.md` — Finding file format (unchanged)
- `sdd/templates/state.schema.json` — State schema (extended)

---

### Option B: Fork-per-Lane with Lane-Local Subdirectories

Same fork dispatch as Option A, but each lane writes to its own subdirectory:
`findings/codebase/`, `findings/git/`, `findings/wiki/`. A separate merge step
reads all three and produces the canonical findings in `findings/`.

Pros:
- No file naming collisions — each lane owns its own namespace.
- Cleaner separation for debugging (check one lane at a time).
- Merge step can apply more sophisticated dedup (e.g. semantic similarity).

Cons:
- Phase 3 synthesis input must be updated to read from `findings/` (the
  merged output) rather than scanning `findings/*.md` directly — minor
  but a change to the existing contract.
- More directory management — mkdir, cleanup, potential orphan subdirs.
- The merge step is more complex (reads 3 dirs, writes 1).
- Recursive follow-ups still can't cross lanes.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| Claude Code `Agent` tool | Fork dispatch | Built-in |

Existing Code to Reuse:
- `.claude/commands/sdd-proposal.md:199-240` — Phase 2 iteration loop
- `.claude/commands/sdd-proposal.md:244-250` — Phase 3 concatenation (needs path update)

---

### Option C: Parallel Tool Calls within Single Agent

Instead of forks, issue multiple tool calls in the same response within the
existing single-agent loop. Claude Code already supports parallel tool calls
for independent operations. Group the research plan's queries by independence
and fire them in batches.

Pros:
- Zero token overhead — no extra context loading.
- No new dispatch mechanism — the agent just calls tools in parallel.
- Simpler mental model (no forks, no merge step).

Cons:
- Limited parallelism: Claude Code batches tool calls within one response
  turn, but the agent still has to process results and decide next steps
  sequentially. Real parallelism is per-response, not per-query.
- No true wall-clock improvement for long-running queries (git log on large
  repos, deep file reads) — the agent still blocks on each response.
- Cannot do cross-query reasoning within a batch (e.g. "finding X suggests I
  should also grep for Y") — that requires the sequential depth loop.
- Budget accounting becomes complex with batched execution.

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| (none) | Uses existing tool parallelism | No new dependencies |

Existing Code to Reuse:
- `.claude/commands/sdd-proposal.md:199-240` — Phase 2 iteration loop (modified to batch)

---

## Recommendation

**Option A** is recommended because it delivers the primary goal (3x
wall-clock reduction for `default` and `loose` profiles) with the simplest
architecture. The fork mechanism (`subagent_type: "fork"`) is a built-in
Claude Code primitive that handles context sharing and parallel execution
natively — no new infrastructure needed.

The per-lane budget allocation (60/80/100% splits) bounds token cost at
roughly 1.8x the sequential cost while delivering ~3x speedup. Prompt cache
sharing between forks further reduces the actual cost. The file-path dedup is
straightforward and preserves the finding format that Phase 3 synthesis
already consumes.

Option B's subdirectory isolation is cleaner but adds directory management
complexity without meaningful benefit — the lane-prefixed IDs in Option A
already prevent collisions. Option C's parallel tool calls don't achieve true
parallelism because the agent still blocks on each response turn.

The tradeoff is clear: ~1.8x token cost for ~3x wall-clock reduction, with
automatic fallback to sequential for `tight` budgets or non-fork environments.

---

## Feature Description

### User-Facing Behavior

Users invoke `/sdd-proposal` exactly as before. The `--budget` flag and
profiles are unchanged. Two new observable behaviors:

1. For `default` and `loose` budgets, the research phase prints lane dispatch
   status:
   ```
   Phase 2 — Parallel research (3 lanes)
     codebase-lane: 18 queries dispatched
     git-lane:       7 queries dispatched
     wiki-lane:      9 queries dispatched
   Waiting for lanes...
     wiki-lane: done (8 findings, 20s)
     git-lane: done (5 findings, 30s)
     codebase-lane: done (12 findings, 45s)
   Merging: 25 lane findings → 18 canonical findings (7 merged by path)
   ```

2. `state.json` gains a `research.parallel` section for audit.

3. `--no-parallel` flag forces sequential execution regardless of budget.

For `tight` budget, behavior is identical to today (sequential).

### Internal Behavior

**Phase 1 (plan generation)** is unchanged — it still produces a flat list of
queries with types and priorities.

**Phase 2 (research execution)** gains a dispatch layer:

1. **Partition**: the approved plan is split into 3 query lists by type.
2. **Budget split**: each lane receives its fraction of the profile limits.
3. **Dispatch**: 3 forks launched in a single Agent tool call (parallel).
   Each fork:
   - Receives its query slice and lane budget as the prompt.
   - Runs the existing iteration loop (budget check → execute → persist
     finding → recurse if depth allows).
   - Writes findings with lane-prefixed IDs (`FC-*`, `FG-*`, `FW-*`).
   - Reports summary stats in its completion output.
4. **Collect**: main agent waits for all 3 fork notifications.
5. **Merge**: dedup pass groups findings by file path, merges overlapping
   citations, renumbers to canonical `F001`+. Originals moved to
   `findings/.audit/`.
6. **State update**: `research.parallel` section written; `consumed` totals
   summed from all lanes; `phase: "research_complete"`.

**Phase 3 (synthesis)** is unchanged — it reads `findings/F*.md`.

**Resume (Step R)**: if interrupted during parallel research:
- If no forks completed: restart Phase 2 from scratch.
- If some forks completed: their findings exist on disk. Re-dispatch only the
  incomplete lanes (check which `FC-*`/`FG-*`/`FW-*` files exist).

### Edge Cases & Error Handling

- **Agent tool unavailable**: auto-detected at dispatch time. Falls back to
  sequential with a one-line note: `Agent tool not available — running
  sequential research`.
- **One fork fails**: the other two's findings are preserved. The failed
  lane's queries are retried sequentially by the main agent (best effort).
  `state.json` records the failure in `research.parallel.lanes.<name>.status`.
- **All forks fail**: treated as a full Phase 2 failure. `phase: "failed"`,
  `resume_hint` points to Phase 2.
- **Finding ID collisions**: impossible — lane prefixes (`FC-`, `FG-`, `FW-`)
  and canonical renumbering (`F001`+) are disjoint namespaces.
- **Recursive follow-ups cross lanes**: not supported. A codebase finding
  that suggests a git query is recorded as a note in the finding but not
  acted on. The synthesis agent can flag this as an unknown.
- **Budget exceeded in one lane**: that lane stops; other lanes continue.
  `truncated: true` is set only if the overall budget is exceeded.
- **`--no-parallel` flag**: forces sequential even for `default`/`loose`.

---

## Capabilities

### New Capabilities
- `sdd-proposal-parallel-research`: parallel fork dispatch for Phase 2 research
- `sdd-proposal-finding-merge`: file-path-based deduplication of lane findings

### Modified Capabilities
- `sdd-proposal` — Phase 2 iteration loop replaced with dispatch + merge
- `sdd-proposal-state` — state schema extended with `research.parallel`

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `.claude/commands/sdd-proposal.md` | modifies | Phase 2 dispatch logic, new `--no-parallel` flag |
| `.agents/skills/sdd-proposal/SKILL.md` | modifies | Twin update — same changes |
| `sdd/templates/state.schema.json` | extends | Optional `research.parallel` object |
| `sdd/templates/finding.md` | unchanged | Finding format stays the same |
| Phase 3 synthesis | unchanged | Reads canonical `F001`+ findings |
| Resume logic (Step R) | extends | Handles mid-fork interruption |

---

## Code Context

### Verified Codebase References

#### Phase 2 — Sequential Iteration Loop
```python
# From .claude/commands/sdd-proposal.md:199-240
# This is the existing sequential loop that will be wrapped with dispatch logic.
# For each query in the approved plan, in priority order:
# 1. Budget check — consumed vs budget limits
# 2. Execute — wiki_query / grep / glob / read / git_log / tree
# 3. Persist finding at ${STATE_DIR}/findings/F<NNN>-<slug>.md
# 4. Recurse if depth_reached < max_depth
# 5. Update state.json consumed counters
```

#### Phase 3 — Synthesis Input Construction
```python
# From .claude/commands/sdd-proposal.md:244-250
# Concatenates, in order:
# - ${STATE_DIR}/source.md content
# - ${STATE_DIR}/research_plan.json content
# - All ${STATE_DIR}/findings/*.md digests, wrapped in <finding id="F00N"> tags
# - A <budget_status> block
# - A <mode> block
```

#### Budget Table
```python
# From .claude/commands/sdd-proposal.md:98-102
# | tight   |  15 |  10 |  5 | 1 |  120 |
# | default |  40 |  25 | 10 | 2 |  300 |
# | loose   | 100 |  60 | 20 | 3 |  900 |
```

#### State Schema — Budget & Consumed
```json
// From sdd/templates/state.schema.json:172-203
// budget: { profile, max_files_read, max_grep_calls, max_git_calls, max_depth, max_wall_seconds }
// consumed: { files_read, grep_calls, git_calls, wall_seconds }
```

#### Resume Logic
```python
# From .claude/commands/sdd-proposal.md:432-453
# Reads state.json, inspects phase and resume_hint.next_phase,
# re-enters the corresponding step. If a phase is "running" (orphaned
# from a crash), restarts that phase from scratch.
```

### Does NOT Exist (Anti-Hallucination)
- ~~`sdd/templates/lane.md`~~ — no lane template exists; lanes use the same `finding.md` format
- ~~`merge_findings()` function~~ — no existing merge/dedup logic in any SDD skill
- ~~`subagent_type: "fork"` usage in any SDD skill~~ — this is the first skill to use forks
- ~~`.claude/commands/sdd-proposal.md` parallel dispatch~~ — no parallel code exists today
- ~~`research.parallel` in `state.schema.json`~~ — does not exist yet; must be added

---

## Parallelism Assessment

- **Internal parallelism**: High — the 3 lanes are independent by design
  (codebase queries, git queries, wiki queries touch different tool surfaces).
  Tasks will likely be: (1) dispatch logic, (2) per-lane budget allocation,
  (3) dedup/merge step, (4) state schema extension, (5) resume handling,
  (6) twin-file sync. Tasks 1-3 are sequential (core logic); 4-6 can run
  in parallel.
- **Cross-feature independence**: Touches only SDD tooling files. No conflict
  with in-flight features unless another feature modifies
  `.claude/commands/sdd-proposal.md` concurrently.
- **Recommended isolation**: per-spec
- **Rationale**: All changes are in 2-3 files (the twin command files + the
  state schema). No code files to compile or test. Sequential within the
  single worktree is appropriate.

---

## Open Questions

- [ ] Should cross-lane recursive follow-ups be supported in a future iteration? (e.g. codebase finding spawns a git query) — *Owner: Jesus*
- [ ] Should the dedup merge preserve both findings verbatim when the file-path match has different symbols (same file, different functions)? — *Owner: Jesus*
- [ ] Should `--budget=custom` support user-specified per-lane limits (e.g. `--lane-budget codebase:files_read=80`)? — *Owner: Jesus*
- [ ] What is the measured prompt-cache hit rate for forks of `/sdd-proposal`? Need empirical data to validate the 1.8x cost estimate. — *Owner: Jesus*
