# TASK-3104: Validate the probe's actual result

**Feature**: FEAT-546 — Design Research Hardening
**Spec**: `sdd/specs/design-research-hardening.spec.md` (§3 Module 5)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-545's own acceptance dry run found (S11, CONFIRM) that `/sdd-spec` §3b.1's model
probe treats a zero exit code from `codex exec` as success without ever checking that
`probe.txt` actually contains `OK` — a false-positive probe (e.g. codex prints an
empty file, a warning, or unrelated text but still exits 0) can still lead to the full
600s research call running against effectively-unverified configuration. This task
adds the missing content check.

---

## Scope

- `.claude/commands/sdd-spec.md` §3b.1: after the existing probe call, verify
  `probe.txt`'s content is exactly `OK`; set `SKIP_REASON` if not.
- Mirror into `.agent/workflows/sdd-spec.md`.

**NOT in scope**: recording the probe output into `run.json` (that's TASK-3102, which
depends on this task); staging uniqueness (TASK-3100); path containment (TASK-3101);
MODIFY-block disambiguation (TASK-3103); tests (TASK-3105).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | §3b.1, add a post-probe content check |
| `.agent/workflows/sdd-spec.md` | MODIFY | Same edit (body parity) |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` at `416c7bc64` (2026-09-10), BEFORE TASK-3100 lands (this task has
> no dependency on it, so its `DR=` anchor below is the un-suffixed baseline — if
> TASK-3100 already landed by the time this task is implemented, `$DR` will carry a
> `RUN_ID` suffix; the probe-check logic below is unaffected either way since it only
> reads/writes files under `$DR`, whatever that path currently resolves to).

### Anchors in `.claude/commands/sdd-spec.md` (574 lines)
```text
:238-250 #### 3b.1 Detect and probe
  :245-249  if [ -z "$SKIP_REASON" ]; then
              timeout 120 codex exec --ephemeral --sandbox read-only -m "$MODEL" \
                -c model_reasoning_effort=high --ignore-user-config \
                -o "$DR/probe.txt" "Reply with exactly the single word OK." >/dev/null 2>&1 \
                || SKIP_REASON="model probe failed for $MODEL (rc=$?)"
            fi                                                     ← insert the content check AFTER this closing `fi`, still inside §3b.1
```
### Twin `.agent/workflows/sdd-spec.md` (578 lines)
```text
Same twin-parity contract as TASK-3100/3101/3102 — 4-line frontmatter + one
`- Worktree policy:` substitution line are the ONLY tolerated deltas
(`diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6`).
```

### Does NOT Exist
- ~~a `probe.txt` content check~~ — today the probe only checks `codex exec`'s exit
  code (`|| SKIP_REASON="model probe failed..."`); this task adds the content check
- ~~writing `probe_output` into `run.json`~~ — that is TASK-3102's job (a dependent
  task), not this one; this task only sets `SKIP_REASON` when appropriate

---

## Implementation Notes

### Pattern to Follow
Simple `[ "$(cat ...)" = "OK" ] || SKIP_REASON=...` shell idiom — no new dependency,
consistent with the rest of §3b.1's style (plain POSIX test expressions).

### Key Constraints
- Must run inside the SAME `if [ -z "$SKIP_REASON" ]; then ... fi` guard as the probe
  call itself (or immediately after it, re-checking `-z "$SKIP_REASON"` first) — if the
  probe already failed (codex missing, non-zero exit), do NOT overwrite that
  `SKIP_REASON` with a different, less-accurate message.
- `cat "$DR/probe.txt" 2>/dev/null` must tolerate a missing file (probe never ran, or
  wrote nothing) without erroring the shell — redirect stderr, don't `set -e`.

---

## Implementation Blueprint

### Steps (in order)
1. After the probe call's existing `|| SKIP_REASON=...` line, add a content check that
   only runs when `SKIP_REASON` is still unset — *why*: don't clobber a genuine
   probe-failure reason with a less specific one (spec AC-6).
2. Compare `probe.txt`'s trimmed content to the literal string `OK` — *why*: this is
   exactly what the probe prompt asked for ("Reply with exactly the single word OK."),
   so the check is a straightforward literal match, not a regex.

### `.claude/commands/sdd-spec.md` (MODIFY — §3b.1, insert immediately after the probe `if`-block's closing `fi`)
```bash
# BEFORE (verified — the probe if-block, ending in its own `fi`)
if [ -z "$SKIP_REASON" ]; then
  timeout 120 codex exec --ephemeral --sandbox read-only -m "$MODEL" \
    -c model_reasoning_effort=high --ignore-user-config \
    -o "$DR/probe.txt" "Reply with exactly the single word OK." >/dev/null 2>&1 \
    || SKIP_REASON="model probe failed for $MODEL (rc=$?)"
fi
# AFTER — insert this block immediately below the fi above
if [ -z "$SKIP_REASON" ]; then
  PROBE_TEXT="$(cat "$DR/probe.txt" 2>/dev/null | tr -d '[:space:]')"
  [ "$PROBE_TEXT" = "OK" ] || SKIP_REASON="model probe returned unexpected output for $MODEL"
fi
```
**Why this shape**: a zero exit code alone does not prove the model actually replied
correctly — `codex exec` can exit 0 while writing an empty, truncated, or unrelated
`probe.txt` (e.g. a degraded model silently ignoring the instruction). Trimming
whitespace before comparing tolerates a trailing newline without weakening the check;
the new `if` only evaluates when `SKIP_REASON` is still empty, so a genuine
probe-invocation failure (already recorded by the existing `|| SKIP_REASON=...`) is
never overwritten by this stricter, but secondary, content check (spec AC-6).

### FILL IN checklist
- [ ] none — the edit is fully specified; no judgement calls left open

---

## Acceptance Criteria

- [ ] `grep -n "model probe returned unexpected output" .claude/commands/sdd-spec.md` → one match in §3b.1
- [ ] The new check is inside its OWN `if [ -z "$SKIP_REASON" ]; then ... fi` block,
  separate from (and after) the existing probe-invocation `if`-block (verify by
  reading the section)
- [ ] Manually simulate: write `echo "not ok" > /tmp/fake_probe.txt`, run
  `PROBE_TEXT="$(cat /tmp/fake_probe.txt | tr -d '[:space:]')"; [ "$PROBE_TEXT" = "OK" ]
  || echo "correctly rejected"` → prints "correctly rejected"
- [ ] `diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'` → `6`
- [ ] No other file changed

---

## Test Specification

Manual (no dedicated Python test for this bash section):
```bash
grep -n "model probe returned unexpected output" .claude/commands/sdd-spec.md
diff .agent/workflows/sdd-spec.md .claude/commands/sdd-spec.md | grep -c '^[<>]'   # expect 6
PROBE_TEXT="$(echo 'garbage' | tr -d '[:space:]')"; [ "$PROBE_TEXT" = "OK" ] && echo BUG || echo OK-rejected
```

---

## Agent Instructions

1. Read spec §3 Module 5.
2. Dependencies: none (parallel-safe with TASK-3100/3101/3103, but all touch
   `sdd-spec.md` — spec's Worktree Strategy recommends sequential in one worktree).
3. Re-grep the anchor; implement from the blueprint; verify; commit both files.
4. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Implemented exactly per blueprint. §3b.1 now has a second
`if [ -z "$SKIP_REASON" ]; then ... fi` block right after the probe
invocation's own `fi`; it trims `probe.txt` and compares to the literal
`OK`, setting `SKIP_REASON="model probe returned unexpected output for
$MODEL"` on mismatch without ever clobbering a genuine probe-invocation
failure (guarded by the same `-z "$SKIP_REASON"` check). Twin regenerated;
`diff | grep -c '^[<>]'` → `6`.
**Deviations from spec**: none
