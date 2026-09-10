# TASK-3102: Persist a replayable Codex execution record

**Feature**: FEAT-546 — Design Research Hardening
**Spec**: `sdd/specs/design-research-hardening.spec.md` (§3 Module 3, §2 Data Models)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3100, TASK-3104
**Assigned-to**: unassigned

---

## Context

FEAT-545's own acceptance dry run found (S6, CONFIRM) that `codex.log` is raw
stdout/stderr redirection only — nothing records the exact model, CLI version,
timeout, or exit status alongside the brief/result, making a past run hard to audit or
reproduce. This task writes a small, structured `run.json` evidence file (NOT a
schema-validated contract — see spec §7 Known Risks) alongside the existing
`brief.md`/`suggestions.json`/`triage.md`/`codex.log`.

This task depends on TASK-3100 (the `$DR`/`RUN_ID` staging path it writes into) and
TASK-3104 (the probe-validation logic whose actual `probe.txt` content this task also
records into `run.json`).

---

## Scope

- `.claude/commands/sdd-spec.md` §3b.1: after the probe, write the first half of
  `$DR/run.json` (model, codex CLI version, reasoning effort, probe output).
- `.claude/commands/sdd-spec.md` §3b.3: capture start/end timestamps and the exit code
  around the main `codex exec` call, and merge them into `$DR/run.json`.
- Mirror both edits into `.agent/workflows/sdd-spec.md`.

**NOT in scope**: a JSON Schema for `run.json` (it is evidence, like `codex.log`, not a
validated contract — spec §7); staging uniqueness itself (TASK-3100, a dependency);
probe output validation logic itself (TASK-3104, a dependency); path containment
(TASK-3101); MODIFY-block disambiguation (TASK-3103); tests (TASK-3105).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | §3b.1 (write first half of `run.json`); §3b.3 (merge in start/end/exit code) |
| `.agent/workflows/sdd-spec.md` | MODIFY | Same 2 edits (body parity) |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` at `416c7bc64` (2026-09-10), AFTER TASK-3100 and TASK-3104 have
> landed (this task's dependencies) — re-grep both `#### 3b.1` and `#### 3b.3` for the
> ACTUAL current text before editing; their exact line content will already include
> the `RUN_ID`/`DR` change (TASK-3100) and the probe-validation line (TASK-3104).

### Anchors in `.claude/commands/sdd-spec.md` (574 lines, pre-TASK-3100/3104 baseline shown — re-grep after those land)
```text
:238-250 #### 3b.1 Detect and probe
  :239   REPO_ROOT="$(pwd)"
  :240   MODEL="${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}"
  :245-249 codex exec ... -o "$DR/probe.txt" "Reply with exactly the single word OK." \
             || SKIP_REASON="model probe failed for $MODEL (rc=$?)"
           fi                                                    ← run.json's FIRST write goes after this closing `fi`
:291-301 #### 3b.3 Run codex (capped, synchronous — NOT a background job)
  :293-299 timeout 600 codex exec --ephemeral --sandbox read-only --cd "$REPO_ROOT" \
             -m "$MODEL" -c model_reasoning_effort=high --ignore-user-config \
             --output-schema sdd/templates/design_research.schema.json \
             -o "$DR/suggestions.json" - < "$DR/brief.md" > "$DR/codex.log" 2>&1
           rc=$?
           [ "$rc" -eq 124 ] && SKIP_REASON="codex timed out after 600s"
           [ "$rc" -ne 0 ] && [ -z "$SKIP_REASON" ] && SKIP_REASON="codex exited $rc (see $DR/codex.log)"
           fi                                                    ← run.json's SECOND write (merge) goes after this closing `fi`
```
### Twin `.agent/workflows/sdd-spec.md` (578 lines)
```text
Same twin-parity contract as TASK-3100/3101 — 4-line frontmatter + one
`- Worktree policy:` substitution line are the ONLY tolerated deltas
(`diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6`).
```
### Spec §2 Data Models (the exact `run.json` shape this task produces)
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

### Does NOT Exist
- ~~`$DR/run.json`~~ — created by this task
- ~~a `run_schema.json` / `jsonschema` validation for `run.json`~~ — explicitly NOT
  created (spec §7: "run.json is NOT schema-validated — it is evidence, like
  codex.log, not a contract like suggestions.json")
- ~~`codex --version` capture~~ anywhere in `sdd-spec.md` today — this task adds it

---

## Implementation Notes

### Pattern to Follow
Use a small `python -c` one-liner to write/merge JSON (consistent with the existing
schema-validation `python -c` block in §3b.4, and TASK-3101's containment check) —
do not add a `jq`-based approach or a new Python module.

### Key Constraints
- `run.json` must be writable even when `SKIP_REASON` is already set at 3b.3 (i.e.
  still record whatever fields are known — model, probe output — even on an early
  skip), so a skipped run's `run.json` is still useful evidence. Guard the 3b.3 merge
  write with `if [ -f "$DR/run.json" ]` (created at 3b.1) rather than
  `if [ -z "$SKIP_REASON" ]`, so it always attempts to record what happened.
- `codex --version` prints `codex-cli X.Y.Z` (verified format, FEAT-545 spec §6 Codex
  CLI Contract) — capture just the version token, not the full line, for the JSON
  field.

---

## Implementation Blueprint

### Steps (in order)
1. After 3b.1's probe `if`-block closes, write the first half of `run.json` — *why*:
   model/reasoning-effort/probe-output are all known by this point (spec AC-5).
2. After 3b.3's `codex exec` call and its `rc` handling, merge in
   `started_at`/`ended_at`/`exit_code` — *why*: these are only known once the main run
   has actually happened (spec AC-5).

### `.claude/commands/sdd-spec.md` (MODIFY — §3b.1, insert after the probe `if`-block's closing `fi`)
```bash
# AFTER the existing 3b.1 fenced block's closing `fi` (verified: end of the probe if-block)
CODEX_VERSION="$(codex --version 2>/dev/null | awk '{print $2}')"
PROBE_OUTPUT="$(cat "$DR/probe.txt" 2>/dev/null || echo "")"
python -c "
import json, sys
json.dump({
    'model': sys.argv[1],
    'codex_cli_version': sys.argv[2],
    'reasoning_effort': 'high',
    'timeout_s': 600,
    'probe_output': sys.argv[3],
}, open(sys.argv[4], 'w'), indent=2)
" "$MODEL" "$CODEX_VERSION" "$PROBE_OUTPUT" "$DR/run.json"
```
**Why this shape**: captures the three fields knowable right after the probe
(model/version/probe-output) into a first-draft `run.json`, written unconditionally
(even when `SKIP_REASON` ends up set) so a skipped run still leaves useful evidence —
this is what makes the record "replayable" even for a failed attempt (spec G3).

### `.claude/commands/sdd-spec.md` (MODIFY — §3b.3, insert after the existing `rc` handling, still inside the `if [ -z "$SKIP_REASON" ]` block from TASK-3100/current text)
```bash
# AFTER the existing rc/SKIP_REASON lines, still inside the same `if` (verified: 3b.3's closing fi)
STARTED_AT="${STARTED_AT:-$(date -u +%Y-%m-%dT%H:%M:%S+00:00)}"   # set just before the `timeout 600 codex exec` line
ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
if [ -f "$DR/run.json" ]; then
  python -c "
import json, sys
d = json.load(open(sys.argv[1]))
d['started_at'] = sys.argv[2]
d['ended_at'] = sys.argv[3]
d['exit_code'] = int(sys.argv[4])
json.dump(d, open(sys.argv[1], 'w'), indent=2)
" "$DR/run.json" "$STARTED_AT" "$ENDED_AT" "$rc"
fi
```
**Why**: merges the timing/exit-code fields into the SAME `run.json` written at 3b.1,
producing the single evidence file spec §2's Data Models shape describes; guarding on
`-f "$DR/run.json"` (not `-z "$SKIP_REASON"`) means this still runs even if a LATER
step sets `SKIP_REASON`, so the record captures what actually happened rather than
being skipped itself.

### FILL IN checklist
- [ ] `STARTED_AT` must be set immediately BEFORE the `timeout 600 codex exec ...`
  line (not shown as a separate blueprint block above to avoid re-quoting the whole
  3b.3 command verbatim) — bounded by: it must be the actual wall-clock time the main
  call started, not the time this merge step runs.

---

## Acceptance Criteria

- [ ] `grep -n "run.json" .claude/commands/sdd-spec.md` → at least 2 matches (3b.1 write, 3b.3 merge)
- [ ] After a real or simulated run, `sdd/state/<FEAT-ID>/design_research/run.json`
  contains all of `model`, `codex_cli_version`, `reasoning_effort`, `timeout_s`,
  `started_at`, `ended_at`, `exit_code`, `probe_output` (spec AC-5)
- [ ] `python -c "import json; json.load(open('run.json'))"` on a produced `run.json`
  succeeds (valid JSON, no schema needed)
- [ ] `diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6`
- [ ] No other file changed

---

## Test Specification

Manual (evidence-only artifact, no schema/test infra per spec §7):
```bash
grep -n "run.json" .claude/commands/sdd-spec.md
diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'   # expect 6
```

---

## Agent Instructions

1. Read spec §3 Module 3 and §2 Data Models.
2. Dependencies: TASK-3100 and TASK-3104 must be in `sdd/tasks/completed/` — re-grep
   §3b.1/§3b.3 for their ACTUAL current text (this task's blueprint quotes the
   pre-dependency baseline; the real anchors will already include the `RUN_ID`/`DR`
   suffix and the probe-validation line).
3. Implement from the blueprint; verify; commit both files.
4. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Implemented exactly per blueprint. §3b.1 now writes the first
half of `$DR/run.json` (model, codex_cli_version, reasoning_effort,
timeout_s, probe_output) right after the probe-content check (TASK-3104)
closes. §3b.3 sets `STARTED_AT` immediately before the main `timeout 600
codex exec` call and, guarded on `-f "$DR/run.json"` (not
`-z "$SKIP_REASON"`, per the task's Key Constraints, so a later skip still
gets a record), merges in `started_at`/`ended_at`/`exit_code`. Simulated
both writes end-to-end in a scratch directory (not the real `$DR`, no
`codex` binary invoked): the resulting JSON contains all 8 fields
(`model`, `codex_cli_version`, `reasoning_effort`, `timeout_s`,
`probe_output`, `started_at`, `ended_at`, `exit_code`) and parses with
`json.load`. §6's promotion (already atomic per TASK-3100, `cp -a "$DR"/.`)
carries `run.json` along automatically — no additional §6 edit needed.
Twin regenerated; `diff | grep -c '^[<>]'` → `6`.
**Deviations from spec**: none

**Post-review addendum (2026-09-10)**: the adversarial code-reviewer found
the §3b.1 `run.json` first-write ran unconditionally, even when `codex` is
not installed at all (`SKIP_REASON="codex CLI not installed"` set at the
very top) — in that case `codex --version` and `probe.txt` are both empty,
so a near-empty `run.json` was still written every time, permanently
orphaning a mostly-useless `$DR` directory (gitignored, harmless to git,
but unbounded local clutter and contrary to "evidence of a completed
run"). Fixed in a follow-up commit by gating the write behind
`command -v codex`, while keeping the intentional "write even on probe
failure" behavior for the case where codex IS present but the probe fails.
The §3b.3 merge step's own `-f "$DR/run.json"` guard needed no change.
