---
id: F005
query_id: Q008
type: grep
intent: "confirm artifacts/logs/e2e/<run_id>/<target_id>.log convention and distinguish it from sdd/state/e2e/<run_id>/ (private run_dir)"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — Two distinct per-run directories exist; the screencast belongs in the *logs* one, not the *state* one

## Summary

`parrot.e2e.state.run_dir(run_id, worktree)` returns a **private, mode-0700**
directory at `<worktree>/sdd/state/e2e/<run_id>/`, used for control sockets
and private target profiles (e.g. the `browser` target's own
`obscura-profile` storage dir) — not logs. The actual per-run, per-target
**log** directory is a separate helper, `E2ESupervisor._log_path()`, which
returns `<worktree>/artifacts/logs/e2e/<run_id>/<target_id>.log`. This is
the convention the spec itself names ("Logs go to
`artifacts/logs/e2e/<run-id>/`") and the one `e2e-ui-tester`'s own example
`evidence_refs` path already follows (F002).

## Citations

- path: `packages/ai-parrot-server/src/parrot/e2e/state.py`
  lines: 216-219
  symbol: `run_dir`
  excerpt: |
    def run_dir(run_id: str, *, worktree: Path) -> Path:
        """Return (creating if needed) this run's private, mode-0700 directory.
        Used for control sockets and private target profiles (spec §2), never for
        the state file itself

- path: `packages/ai-parrot-server/src/parrot/e2e/supervisor.py`
  lines: 889-903
  symbol: `E2ESupervisor._log_path`
  excerpt: |
    def _log_path(self, run_id: str, target_id: str) -> Path:
        """... Spec §2: "Logs go to `artifacts/logs/e2e/<run-id>/`." ...
        Returns: `<worktree>/artifacts/logs/e2e/<run_id>/<target_id>.log`.
        """
        log_dir = self._worktree / "artifacts" / "logs" / "e2e" / run_id

## Notes

The exploration agent's existing screenshot already lands under this exact
directory (per F002's example path), so the natural placement for a
screencast is a sibling file in the same `artifacts/logs/e2e/<run_id>/`
directory — e.g. `<target_id>.webm` or `screencast.webm` — never inside the
private `sdd/state/e2e/<run_id>/` run directory.
