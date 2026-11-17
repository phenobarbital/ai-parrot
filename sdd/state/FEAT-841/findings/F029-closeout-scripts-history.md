---
id: F029
query_id: Q045
type: git_log
intent: "History of the closeout hooks / e2e closeout scripts (FEAT-703) — precedent and recency of the code-enforced gate."
executed_at: 2026-11-07T01:19:11Z
duration_ms: 1200
parent_id: null
depth: 0
merged_from: [FG-004]
---

# F029 — closeout scripts: born 2026-10-28 under scripts/sdd/, moved into parrot.sdd.scripts by FEAT-633 on 2026-11-02

## Summary

At their current paths the three scripts show only one commit (the FEAT-633 move, `3850087e56`, 2026-11-02). `git log --follow` on `run_closeout_hooks.py` reveals the pre-move history: created by `fde39a8294` (TASK-4869, FEAT sdd-done-closeout-hooks, 2026-10-28), lint `38d141d868`, review fix `5d71ed16f1` ("malformed agent prompt fails its hook, not the event"), Python hardening `744c163179` (TASK-4874). So the generic hook runner is ~10 days old, already hardened once, and relocated once — the extension point for a verdict gate is stable at `packages/ai-parrot/src/parrot/sdd/scripts/`.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  symbol: `fde39a8294`
  excerpt: |
    fde39a8294 2026-10-28 Jesus feat(sdd-done-closeout-hooks): TASK-4869 — engine-committed coder deliverable
    38d141d868 2026-10-28 Jesus style(sdd-done-closeout-hooks): TASK-4869 — engine lint autofix
    5d71ed16f1 2026-10-28 Jesus fix(sdd-done-closeout-hooks): review fix — malformed agent prompt fails its hook, not the event
    744c163179 2026-10-28 Jesus feat(fixgroup-5a875150e625): TASK-4874 — closeout hooks Python hardening
- path: `packages/ai-parrot/src/parrot/sdd/scripts/run_closeout_hooks.py`
  symbol: `3850087e56`
  excerpt: |
    3850087e56 2026-11-02 Juanfran feat(parrot-installer): FEAT-633 — parrot sdd installer + C30 noun-grouped CLI (TASK-5095..5099) (#1823)
    (same single commit at the current path for check_e2e_closeout.py and closeout_builtins.py)

## Notes

- `check_e2e_closeout.py` predates the hook runner (FEAT-703, TASK-4462 on 2026-10-19 per FG-001) but its own pre-move history was not followed (git budget). [cross-lane: type=read, intent=read closeout_builtins.py to see how built-in hooks register and whether a verdict hook can be a built-in]
