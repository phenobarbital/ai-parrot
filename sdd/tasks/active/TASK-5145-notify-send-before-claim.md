# TASK-5145: Resolve notify-send before claiming the delivery attempt

**Feature**: FEAT-793 — tmux worker completion notifications
**Spec**: `sdd/specs/tmux-notify-worker.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (<1h)
**Depends-on**: TASK-5122
**Assigned-to**: unassigned
**Discovered-from**: `issue:0c3d7d50744b`

## Context

Review finding on TASK-5122: `handle_stop` in
`packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` takes the
one-shot `notify-attempted` claim before resolving `notify-send`, so a host
without `notify-send` silently consumes the single allowed attempt.

## Scope

- Resolve `notify-send` from the captured desktop `PATH` **before** `_claim_attempt()`;
  a missing binary returns without creating `notify-attempted`.
- Replace `assert isinstance(desktop, dict)` with an explicit guard (asserts vanish under
  `python -O`, and `AssertionError` was not caught).
- Log one concise warning when `notify-send` exits non-zero.
- Compute the worktree Git top-level once per Stop invocation: `_receipt()` reuses the
  root already validated by `_context()` instead of running `git rev-parse --show-toplevel` again.

**NOT in scope**: changing timeouts, the context/receipt schema, or the launch wiring.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worker_notification.py` | MODIFY |
| `packages/ai-parrot/tests/sdd/test_worker_notification.py` | MODIFY |

## Codebase Contract

### Existing Signatures
- `handle_stop(payload: Mapping[str, object], *, cache: Path) -> None`
- `_receipt(cache: Path, context: Mapping[str, object]) -> bool`
- `_claim_attempt(cache: Path) -> bool`
- `_context(cache: Path) -> dict[str, object] | None` — already validates `worktree` equals the Git top-level.

## Acceptance Criteria

- [ ] A Stop with a valid receipt and no `notify-send` on the desktop `PATH` leaves no `notify-attempted` marker; a later Stop with `notify-send` available still delivers.
- [ ] No `assert` remains in `handle_stop`.
- [ ] A non-zero `notify-send` exit logs a warning.
- [ ] `git rev-parse --show-toplevel` runs once per `handle_stop` call.
- [ ] Existing tests in `test_worker_notification.py` and `test_worker_notification_protocol.py` still pass.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_worker_notification.py packages/ai-parrot/tests/sdd/test_worker_notification_protocol.py -q
```

## Completion Note

(pending)
