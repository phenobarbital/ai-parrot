---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Design Research Hardening

**Feature ID**: FEAT-546
**Date**: 2026-09-10
**Author**: Jesus Lara (with Claude Sonnet 5)
**Status**: approved
**Target version**: n/a — SDD tooling (`.claude/commands`, `sdd/templates`); nothing ships in a package
**Origin**: follow-up to FEAT-545 (Collaborative Adversarial Spec Design, PR #1353,
merged to `dev` at `f98a14f26`). FEAT-545's own acceptance dry run (TASK-3099) ran the
new `/sdd-spec` §3b phase against its own accepted proposal and, via its adversarial
`codex` cross-check, surfaced 11 suggestions. 5 were disposed **CONFIRM** (real,
verified, actionable hardening gaps) in
`sdd/specs/collaborative-adversarial-spec-design.spec.md` §9 and
`sdd/state/FEAT-545/design_research/triage.md`, each explicitly landed as "Follow-up
task". This spec is that follow-up. The other 6 suggestions (1 REJECT, 5 ESCALATE) are
explicitly OUT of scope — see Non-Goals.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-545 shipped `/sdd-spec` §3b — an optional, never-blocking phase that hands the
accepted brainstorm/proposal to a `codex` seat and triages its suggestions. Its own
acceptance dry run (TASK-3099) exercised the phase for real and, on top of 3 CRITICAL
bugs that were fixed before merge (missing `SKIP_REASON` guard, unassigned `$REPO_ROOT`,
a brief-rendering bug), the `codex` seat itself surfaced 5 additional, verified
hardening gaps that were correctly triaged as CONFIRM (real, in-scope, actionable) but
explicitly deferred rather than fixed in-line, per FEAT-545's own task scope rule
("NOT in scope: changing command/template text... open a follow-up task"). Those 5
gaps are still open on `dev` today:

1. **Staging is not run-scoped or atomic** (S2). `sdd/state/.design_research/<feature-name>`
   is a deterministic, reusable directory (`mkdir -p`); a rerun or a concurrent
   `/sdd-spec` invocation for the same feature name can mix a stale `suggestions.json`
   into a fresh triage, and §6's promotion (`mv "$DR"/* ...`) has no cleanup-on-failure.
2. **`affected_paths` has no containment check** (S4). The schema types it as a plain
   string and §3b.4's validation is a bare `test -e <path>` — an absolute path or a
   `../` traversal is accepted uncriticized, so a suggestion could point the triage
   step's read at a file outside the repository.
3. **No replayable execution record is persisted** (S6). `codex.log` is raw
   stdout/stderr redirection only; nothing records the exact model, CLI version,
   timeout, or exit status alongside the brief/result, making a past run hard to audit
   or reproduce.
4. **MODIFY blueprint blocks are not disambiguated** (S8). `sdd/templates/task.md`'s
   MODIFY example says "insert below `<anchor>`" with no rule about what happens if the
   anchor text appears more than once in the target file — a non-thinking executor
   could duplicate an insertion.
5. **The probe doesn't validate its own result** (S11). §3b.1 treats a zero exit code
   as success without checking that `probe.txt` actually contains `OK`, or recording
   which model/config was actually honored — a false-positive probe can still lead to
   the full 600s research call running against the wrong configuration.

### Goals

- **G1** — Research staging (`sdd/state/.design_research/<feature-name>/`) is
  per-run-unique and its promotion into `sdd/state/<FEAT-ID>/design_research/` is
  atomic: a partial/failed run never contaminates a subsequent one.
- **G2** — Every `affected_paths` entry is resolved and verified to stay within the
  repository root before a suggestion can be dispositioned; an escape is rejected the
  same way an unverifiable path already is ("REJECT — path not found" /
  "REJECT — path outside repository").
- **G3** — Each §3b run persists a small, structured execution record (model, CLI
  version, timeout, exit code, start/end timestamps) alongside `codex.log`.
- **G4** — A task's Implementation Blueprint MODIFY block must specify how many times
  its anchor occurs and refuses to be ambiguous when it occurs more than once.
- **G5** — §3b.1's probe verifies `probe.txt`'s content (not just the exit code) before
  treating the model as usable.
- **G6** — Twins stay in sync (same discipline as FEAT-545): every edit to
  `.claude/commands/sdd-spec.md` / `sdd-task.md` is mirrored into `.agent/workflows/`,
  checked by the existing `test_command_twin_parity.py`.

### Non-Goals (explicitly out of scope)

- **The 5 ESCALATE items from FEAT-545 §9** (S3 foreground/background contract vs.
  `sdd-planner`'s unattended timeout budget; S5 requiring line/symbol evidence instead
  of bare paths — a schema/contract change; S7 mechanical triage-completeness
  validation infrastructure; S9 linting Implementation Blueprint *substance*, which
  re-opens the FEAT-545 §8 "lint vs. written rule" question at a broader scope; S10
  whether including the exploration doc's "Recommended Option" verbatim in the neutral
  brief constitutes anchoring bias). All 5 remain human decisions, unresolved here.
- **S1 (REJECT in FEAT-545 §9)** — extracting §3b into a Python helper. Still an
  explicit non-goal: the phase stays bash inside `.claude/commands/sdd-spec.md`,
  mirroring the Adversarial Cross-Check pattern, exactly as FEAT-545 decided.
- **Any change to `parrot/flows/dev_loop/**`** — same non-goal FEAT-545 carried; no new
  dispatcher, profile, or `conf.py` key. `packages/ai-parrot/src/parrot/flows/dev_loop/
  dispatchers/codex.py` is read here only as a pattern reference for G3's execution
  record (its `_build_command`/event-log shape), not modified.
- **Changing the `design_research.schema.json` suggestion contract** (adding new
  required fields) — that is S5, explicitly deferred (ESCALATE).
- **A general Implementation Blueprint substance linter** — that is S9, explicitly
  deferred (ESCALATE). G4 only tightens the MODIFY-block *rule text* and its worked
  example; it does not add automated enforcement.

---

## 2. Architectural Design

### Overview

Five narrow, independent hardenings of the `/sdd-spec` §3b phase and the task
Implementation Blueprint convention, each scoped to a single FEAT-545 CONFIRM finding.
All five stay within the same "prose command + bash + template" shape FEAT-545
established — no new Python modules, no dev_loop coupling.

### Component Diagram

```
/sdd-spec §3b.1  ── probe ──► verify probe.txt == "OK" (G5) ──► record {model, cli_version,
                                                                        config} in run.json
             │
             ▼
        DR = sdd/state/.design_research/<feature-name>-<run-id>/   (G1: per-run unique)
             │
             ▼
/sdd-spec §3b.3  ── codex exec ──► suggestions.json + codex.log + run.json (G3: exit/timing)
             │
             ▼
/sdd-spec §3b.4  ── for each affected_path: resolve + must stay under $REPO_ROOT (G2) ──►
                     test -e  ──►  CONFIRM/REJECT/ESCALATE
             │
             ▼
/sdd-spec §6     ── atomic promotion: stage under a temp name, rename() into
                     sdd/state/<FEAT-ID>/design_research/ only on full success (G1)

/sdd-task §3     ── Implementation Blueprint MODIFY block ──► states anchor
                     occurrence count; refuses (FILL IN: disambiguate) when > 1 (G4)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-spec.md` §3b.1/§3b.3/§3b.4/§6 | modifies | run-id staging, probe validation, path containment, execution record, atomic promotion |
| `.claude/commands/sdd-task.md` §3 | modifies | MODIFY-block anchor-occurrence rule |
| `sdd/templates/task.md` | modifies | MODIFY example updated to show the occurrence-count line |
| `sdd/templates/design_research.prompt.md` | unmodified | no schema/prompt contract change (S5 deferred) |
| `.agent/workflows/sdd-spec.md`, `.agent/workflows/sdd-task.md` | mirrors | body must equal the `.claude/commands/` originals (existing parity test, unchanged rules) |
| `tests/sdd_scripts/test_design_research_templates.py` | extends | new assertions for the MODIFY-block occurrence rule |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | pattern reference only | `_build_command` shape informs G3's execution-record fields; file itself untouched (non-goal) |

### Data Models

The execution record persisted by G3 (`sdd/state/<FEAT-ID>/design_research/run.json`,
plain JSON, no schema file needed — it is evidence, not a validated contract like
`suggestions.json`):

```json
{
  "model": "gpt-5.6-luna",
  "codex_cli_version": "0.153.4",
  "reasoning_effort": "high",
  "timeout_s": 600,
  "started_at": "2026-09-10T02:28:12+00:00",
  "ended_at": "2026-09-10T02:32:01+00:00",
  "exit_code": 0,
  "probe_output": "OK"
}
```

### New Public Interfaces

No Python. All changes are prose/bash inside `.claude/commands/sdd-spec.md` /
`sdd-task.md` and the two markdown templates. Interface Skeletons in §3 below are
marked `n/a (bash/markdown; exact text fixed inline)`, the same convention FEAT-545
used for its own non-Python modules.

---

## 3. Module Breakdown

### Module 1: Unique, atomic research staging (S2)
- **Path**: `.claude/commands/sdd-spec.md` (+ twin `.agent/workflows/sdd-spec.md`), `.gitignore`
- **Responsibility**: §3b.1's `DR="sdd/state/.design_research/<feature-name>"` becomes
  `DR="sdd/state/.design_research/<feature-name>-$(date -u +%Y%m%dT%H%M%SZ)-$$"`
  (timestamp + PID — no new dependency, `date`/`$$` are already used elsewhere in the
  command). §6's promotion becomes atomic: stage the final `design_research/` payload
  under a sibling temp name inside `sdd/state/<FEAT-ID>/`, then `mv` it into place in one
  step only after every file has been copied successfully; on any copy failure, leave
  the run-scoped `$DR` untouched under `sdd/state/.design_research/` (still gitignored)
  instead of partially promoting it, and report the run-id in the skip/failure message
  so it can be inspected manually.
- **Depends on**: none
- **Interface Skeleton**: n/a (bash/markdown; exact text fixed inline in Implementation Notes)

### Module 2: Path containment for `affected_paths` (S4)
- **Path**: `.claude/commands/sdd-spec.md` §3b.4 (+ twin)
- **Responsibility**: before the existing `test -e <path>` check, resolve each
  `affected_paths` entry against `$REPO_ROOT` (`python -c "import os,sys;
  p=os.path.realpath(sys.argv[1]); root=os.path.realpath('.'); sys.exit(0 if
  p==root or p.startswith(root+os.sep) else 1)" "<path>"`, or the shell-only
  equivalent using `readlink -f` gated on it being available); reject with
  `REJECT — path outside repository` (not `REJECT — path not found`, so the two
  failure modes stay distinguishable in `triage.md`/§9) any path that resolves outside
  the repo root or is absolute-and-outside, before ever running `test -e` on it.
- **Depends on**: none
- **Interface Skeleton**: n/a (bash; exact text fixed inline in Implementation Notes)

### Module 3: Persist a replayable execution record (S6)
- **Path**: `.claude/commands/sdd-spec.md` §3b.1/§3b.3/§6 (+ twin)
- **Responsibility**: write `$DR/run.json` (shape in §2 Data Models) — populated
  incrementally: model/config at §3b.1 (also recording the probe's actual output per
  Module 5), `codex --version` output and the main run's start/end timestamps + exit
  code at §3b.3. §6's promotion moves `run.json` alongside `brief.md`/`suggestions.json`/
  `triage.md`/`codex.log` into `sdd/state/<FEAT-ID>/design_research/` — no new commit
  step, it rides the existing `git add "sdd/state/<FEAT-ID>/design_research/"` line.
- **Depends on**: Module 1 (writes into the same `$DR`), Module 5 (probe_output field)
- **Interface Skeleton**: n/a (bash/JSON; exact text fixed inline in Implementation Notes)

### Module 4: Disambiguate MODIFY blueprint blocks (S8)
- **Path**: `sdd/templates/task.md`, `.claude/commands/sdd-task.md` (+ twin)
- **Responsibility**: `task.md`'s MODIFY example gains a required line —
  `# occurrences: <N> (verified: grep -c '<anchor>' path/to/existing.py)` — directly
  under the `# AFTER — insert below ...` header, and a new bullet in `sdd-task.md`'s
  "CRITICAL — Implementation Blueprint per Task" block: "MODIFY blocks MUST state the
  anchor's occurrence count (`grep -c`); if it is > 1, the block is `# FILL IN:
  disambiguate — quote enough surrounding context (2–3 lines) to make the anchor
  unique` instead of a bare one-line anchor." No enforcement lint (that would be S9,
  deferred) — a written rule + updated template example, same bar as the rest of
  FEAT-545's blueprint rules.
- **Depends on**: none
- **Interface Skeleton**: n/a (markdown; exact text fixed inline in Implementation Notes)

### Module 5: Validate the probe's actual result (S11)
- **Path**: `.claude/commands/sdd-spec.md` §3b.1 (+ twin)
- **Responsibility**: after the existing `codex exec ... -o "$DR/probe.txt" "Reply with
  exactly the single word OK."` call, add
  `[ "$(cat "$DR/probe.txt" 2>/dev/null)" = "OK" ] || SKIP_REASON="model probe returned
  unexpected output for $MODEL"` so a zero exit code with wrong/empty output is no
  longer treated as success. Record the raw `probe.txt` content into `run.json`'s
  `probe_output` field (Module 3).
- **Depends on**: Module 3 (writes into `run.json`)
- **Interface Skeleton**: n/a (bash; exact text fixed inline in Implementation Notes)

### Module 6: Tests, twin parity, and acceptance dry run
- **Path**: `tests/sdd_scripts/test_design_research_templates.py` (extends), no new test file
- **Responsibility**: add `test_task_template_modify_block_states_occurrence_count()`
  (asserts `# occurrences:` appears in `task.md`'s MODIFY example, per Module 4); rely
  on the EXISTING `test_command_twin_parity.py` (unchanged, no new tolerated-delta
  lines are introduced by any module above) to catch twin drift for Modules 1/2/3/5.
  Also owns AC-9's acceptance dry run: a lightweight functional rehearsal (not a full
  `codex` design-research pass — this spec's own §9 is `skipped`, see §8) confirming
  the 5 edits actually compose: exercise §3b.1's staging/probe-validation, one
  intentionally out-of-repo `affected_paths` string against §3b.4's containment
  check, and (if `codex` is available) one real or simulated §3b.3 run producing a
  `run.json`; record the run-id, `run.json` contents, and the out-of-repo test
  outcome in this task's Completion Note (or the skip-path outcome, per AC-9's own
  "or the skip path is exercised and recorded" wording, if `codex` is unavailable).
- **Depends on**: Modules 1–5
- **Interface Skeleton**:
  ```python
  # tests/sdd_scripts/test_design_research_templates.py  (extends existing file)
  def test_task_template_modify_block_states_occurrence_count() -> None:
      """`sdd/templates/task.md`'s MODIFY example states an anchor occurrence count."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_task_template_modify_block_states_occurrence_count` | 6 | `sdd/templates/task.md` MODIFY example contains `# occurrences:` |
| `test_command_twin_parity[sdd-spec]` (existing) | 1,2,3,5 | twin still matches after all §3b edits |
| `test_command_twin_parity[sdd-task]` (existing) | 4 | twin still matches after the MODIFY-rule edit |

### Integration Tests
| Test | Description |
|---|---|
| Manual dry run (evidenced in Completion Note) | Re-run `/sdd-spec` §3b against an accepted exploration doc (this spec's own acceptance path, see §5 AC-7); confirm a fresh `run.json` is written, a rerun does not corrupt a concurrent run's staging, and an intentionally-crafted `../`-style suggestion path is REJECTed as "outside repository" rather than "not found" |

### Test Data / Fixtures
```python
# tests/sdd_scripts/test_design_research_templates.py (addition only)
def test_task_template_modify_block_states_occurrence_count() -> None:
    text = (_TPL / "task.md").read_text(encoding="utf-8")
    assert "# occurrences:" in text
```

---

## 5. Acceptance Criteria

- [ ] **AC-1** `pytest tests/sdd_scripts/test_command_twin_parity.py tests/sdd_scripts/test_design_research_templates.py -v` passes (9 tests: the existing 8 + the new one).
- [ ] **AC-2** §3b.1's `DR=` assignment includes a per-run component (timestamp and/or PID); two concurrent invocations for the same feature name produce different `$DR` values.
- [ ] **AC-3** §6's promotion into `sdd/state/<FEAT-ID>/design_research/` is atomic: a script fault injected mid-copy leaves the destination directory absent (not partially populated) and the run-scoped source untouched under `sdd/state/.design_research/`.
- [ ] **AC-4** §3b.4 rejects an `affected_paths` entry containing `../../etc/passwd` (or any path resolving outside `$REPO_ROOT`) with reason text containing "outside repository", distinct from the existing "path not found" reason.
- [ ] **AC-5** `sdd/state/<FEAT-ID>/design_research/run.json` exists after a completed run and contains `model`, `codex_cli_version`, `timeout_s`, `started_at`, `ended_at`, `exit_code`, `probe_output`.
- [ ] **AC-6** §3b.1 sets `SKIP_REASON` when `probe.txt` does not contain exactly `OK`, even if `codex exec`'s exit code is 0.
- [ ] **AC-7** `sdd/templates/task.md`'s MODIFY example states an anchor occurrence count (`# occurrences: <N>`), and `.claude/commands/sdd-task.md` §3 documents the disambiguation rule for `> 1`.
- [ ] **AC-8** `.agent/workflows/sdd-spec.md` and `.agent/workflows/sdd-task.md` still mirror their `.claude/commands/` originals — AC-1's existing parity tests are the check; no new tolerated-delta line is introduced.
- [ ] **AC-9** Acceptance dry run: this spec's own PR/merge process constitutes the required exploration doc; `/sdd-spec` §3b is re-run manually against it (or the skip path is exercised and recorded) and the Completion Note records the run-id, `run.json` contents, and the outcome of one intentionally out-of-repo `affected_paths` test case.
- [ ] **AC-10** No file under `packages/ai-parrot/src/parrot/flows/dev_loop/` is modified (non-goal); `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` still passes.
- [ ] **AC-11** No breaking change to `design_research.schema.json`'s existing contract (S5 deferred) — `sdd/state/FEAT-545/design_research/suggestions.json` (already committed) still validates against the unmodified schema.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All anchors verified on `dev` at `967be1a8a` (2026-09-10), i.e. AFTER FEAT-545 merged
> (PR #1353, merge commit `f98a14f26`). Re-grep heading text, not line numbers, before
> editing — FEAT-545's own spec §7 already flagged this ("Line anchors shift").

### Verified Imports
```python
import json                                              # stdlib — used for run.json
from pathlib import Path                                 # stdlib — test precedent
import pytest                                             # tests/sdd_scripts/ convention
```
No new third-party imports. `jsonschema` (already a dependency,
`packages/ai-parrot/pyproject.toml:80`) is NOT needed for `run.json` — it is
unvalidated evidence, not a schema-checked contract (see §2 Data Models note).

### Existing File Anchors (markdown/bash targets — line numbers are edit anchors on `dev@967be1a8a`)
```text
# .claude/commands/sdd-spec.md  (574 lines)
:209-236 ### 3b. Collaborative Design Research (rules + preconditions)
:238-250 #### 3b.1 Detect and probe
  :239   REPO_ROOT="$(pwd)"
  :240   MODEL="${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}"
  :241   DR="sdd/state/.design_research/<feature-name>"      ← Module 1 edits this line
  :245-249 codex exec ... -o "$DR/probe.txt" "Reply with exactly the single word OK."  ← Module 5 adds validation after this
:253-290 #### 3b.2 Render the neutral brief (guarded by `if [ -z "$SKIP_REASON" ]`)  — UNCHANGED by this spec
:291-307 #### 3b.3 Run codex (capped, synchronous)
  :293-299 the `timeout 600 codex exec ...` call and its rc handling            ← Module 3 adds run.json writes around this
:308-324 #### 3b.4 Validate and triage
  :309-317 python -c jsonschema validation block
  :318-322 "For each suggestion (when not skipped): verify every `affected_paths`
           entry (`test -e <path>`) ..."                                        ← Module 2 inserts containment check before `test -e`
:325-336 #### 3b.5 Fold and record
  :333   "§6 moves `$DR` to `sdd/state/<FEAT-ID>/design_research/` and commits it"
:487-518 ### 6. Commit the Spec
  :503-508 the `if [ -d "sdd/state/.design_research/<feature-name>" ]; then ... fi`
           promotion block (mkdir -p / mv * / rmdir / git add)                  ← Module 1 makes this atomic; Module 3's run.json rides along

# .claude/commands/sdd-task.md  (328 lines)
:96-144  "CRITICAL — Implementation Blueprint per Task (Executor Readiness, FEAT-545)"
  :103-105 rule 1: "MODIFY blocks quote the verified anchor line they attach to
           (`# AFTER — insert below \`<anchor>\` (verified: path:NN)`)"          ← Module 4 adds the occurrence-count sub-rule here

# sdd/templates/task.md  (220 lines)
:130-135 ### `parrot/path/to/existing.py` (MODIFY) example block                 ← Module 4 edits this block
  :132   "# AFTER — insert below `<verbatim anchor line>` (verified: parrot/path/to/existing.py:NN)"

# .agent/workflows/sdd-spec.md (578 lines) / .agent/workflows/sdd-task.md (332 lines)
Twin-parity contract UNCHANGED from FEAT-545: frontmatter (4 lines) + exactly one
substitution line each (`- Worktree policy:` for sdd-spec; the "sub-features extend a
parent feature branch" line for sdd-task) — verified via
`tests/sdd_scripts/test_command_twin_parity.py` (existing, untouched by this spec).

# sdd/templates/design_research.schema.json (31 lines) — READ ONLY, not modified (S5 deferred)
:24 "affected_paths": { "type": "array", "items": { "type": "string" }, ... }

# tests/sdd_scripts/test_design_research_templates.py (existing file, extended)
:1-14 imports + _TPL/_SCHEMA/_PROMPT module constants — reuse `_TPL` for the new test

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py — PATTERN REFERENCE ONLY, not modified
:43   class CodexCodeDispatcher:   ← informs G3's run.json field naming only
```

### Does NOT Exist (Anti-Hallucination)
- ~~`sdd/state/<FEAT-ID>/design_research/run.json`~~ — created by Module 3
- ~~`# occurrences:`~~ in `sdd/templates/task.md` or `.claude/commands/sdd-task.md` — new text added by Module 4
- ~~A run-id / timestamp component in `$DR`~~ — added by Module 1; today `$DR` is a bare `sdd/state/.design_research/<feature-name>` with no suffix
- ~~Path containment logic in §3b.4~~ — today's check is a bare `test -e <path>`; added by Module 2
- ~~`design_research.schema.json` schema changes~~ — explicitly NOT created (S5 deferred, non-goal)
- ~~`scripts/sdd/design_research_hardening.py`~~ or any new Python helper module — non-goal, same as FEAT-545's S1 rejection
- ~~Changes to `parrot/flows/dev_loop/dispatchers/codex.py`~~ — read-only pattern reference, non-goal

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Anchored code** (FEAT-545 precedent, `sdd/templates/spec.md:81-88`): every skeleton/
  blueprint line referencing existing code carries `# verified: path:NN`.
- **Never abort `/sdd-spec`** — every new failure branch (containment rejection, probe
  validation) sets `SKIP_REASON`/a per-suggestion `REJECT`, never `exit`.
- **Twin edits**: change `.claude/commands/<name>.md` first, then regenerate
  `.agent/workflows/<name>.md` via `head -n 4 <twin> > tmp; cat .claude/commands/<name>.md
  >> tmp; mv tmp <twin>` (the exact recipe FEAT-545 used, verified working for both
  `sdd-spec.md` and `sdd-task.md`); confirm with the existing parity test.
- **Commit discipline** (FEAT-545 precedent): `git reset HEAD`, stage explicit paths
  only, verify with `git diff --cached --name-only`.

### Known Risks / Gotchas
- **`$$` (PID) reuse across container restarts** is a theoretical staging-uniqueness
  edge case; combined with a UTC timestamp (Module 1) the composite key is
  practically unique for this repo's usage pattern (one `/sdd-spec` call per feature,
  rarely concurrent). Not hardened further — out of scope to add a UUID dependency.
- **`readlink -f` portability**: prefer the `python -c` containment check (already a
  precedent in FEAT-545's own §3b.4 validation step) over `readlink -f`, which is not
  available in all minimal shells (e.g. macOS's built-in `readlink`).
- **`run.json` is NOT schema-validated** — it is evidence, like `codex.log`, not a
  contract like `suggestions.json`. Do not add a `jsonschema` dependency for it.
- **Global `*.log` and `templates/` gitignore rules**: `codex.log` already required
  `git add -f` in FEAT-545 (`.gitignore:346`); `run.json` does NOT hit that rule (it's
  `.json`, not `.log`) but IS inside `sdd/state/<FEAT-ID>/design_research/`, which is
  tracked as a normal directory once promoted — no force-add needed for `run.json`
  itself. Re-verify with `git check-ignore` before assuming either way.

### External Dependencies
None new. `date`, `python3` (stdlib only), `codex` CLI — all already required by
FEAT-545.

---

## 8. Open Questions

- [x] **Does this spec need its own `/sdd-spec` §3b design-research pass?** — *Resolved*:
  no. The requirements are already the output of FEAT-545's own §3b pass (this spec's
  entire motivation IS that pass's CONFIRMed findings) — running §3b again over this
  spec's own (nonexistent) "exploration doc" would have nothing new to review. §9 below
  is marked `skipped (requirements pre-sourced from FEAT-545's own dry run)`.
- [ ] **Should Module 1's run-id also appear in the committed `sdd/state/<FEAT-ID>/
  design_research/` path**, or only in the transient staging path? — *Owner: Jesus
  Lara* — default: only in staging; the committed path stays
  `sdd/state/<FEAT-ID>/design_research/` (unkeyed) since FEAT-545's own AC-10 and every
  existing reference (spec §9's Transcript pointer, TASK-3099's evidence) assume that
  fixed, unkeyed path — changing it would be a breaking rename for zero benefit.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted exploration doc.
> Model: n/a · **Status: skipped (requirements pre-sourced from FEAT-545's own §3b dry
> run — see Origin note above; this spec's five modules ARE the follow-up tasks that
> FEAT-545's own adversarial cross-check already recommended, so a second pass would
> review a pass reviewing itself)** · Transcript: n/a

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | *(skipped — see Status above)* | | | |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all 6 tasks run sequentially in one worktree
  (`feat-FEAT-546-design-research-hardening`).
- **Ordering**: Modules 1, 2, 4, 5 are independent and touch disjoint line ranges of
  the same two command files — sequential in one worktree is simpler than coordinating
  parallel edits to `sdd-spec.md`; Module 3 depends on Modules 1 (same `$DR`) and 5
  (`probe_output` field); Module 6 (tests) last, after all template/command edits land.
- **Cross-feature dependencies**: builds directly on FEAT-545 (merged, `dev@f98a14f26`).
  No other feature is known to be editing `.claude/commands/sdd-spec.md` concurrently as
  of this spec's authoring — reconcile with plain merge, never rebase, if that changes.
- **Runtime dependency**: AC-9's dry run needs the `codex` binary; if unavailable, the
  skip path is exercised and recorded per AC-9's own wording ("or the skip path is
  exercised and recorded").

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-10 | Jesus Lara (with Claude Sonnet 5) | Initial draft — follow-up to FEAT-545's 5 CONFIRMed hardening findings (S2, S4, S6, S8, S11) |
| 0.2 | 2026-09-10 | Jesus Lara | Status → approved |
