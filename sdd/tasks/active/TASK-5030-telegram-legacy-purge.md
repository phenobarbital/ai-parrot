# TASK-5030: Telegram legacy-key purge (`legacy_audit --purge --channel telegram`)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Cutover", §3 Module 10, AC-13 (G7). FEAT-773's `legacy_audit` counts legacy keys read-only. This task adds
a guarded, dry-run-by-default purge of the Telegram Redis legacy keys after `OAUTH2_LEGACY_KEYS_UNTIL`. Redis only —
vault secrets `oauth2_{p}_telegram_{u}` are excluded (docs, TASK-5031, say residual vault cleanup is separate).
The Telegram comment cleanup the spec lists under M10 (wrapper.py:1284-1294) is done by TASK-5020 to avoid another
`wrapper.py` edit. Open question §8 Q2 (encrypted backup before deletion) is **not** decided — do not add a backup.

---

## Scope

- `purge_legacy_keys(redis, *, channel, providers, dry_run=True, force=False, now=None) -> Dict[str, int]`.
- Patterns: `jira:oauth:{channel}:*` (when `"jira"` in providers) and `oauth2:{p}:{channel}:*` per provider; `SCAN`
  (`scan_iter(match=...)`) never `KEYS`; batch `UNLINK`; returns `{pattern: count}`; deletes only when not `dry_run`.
- Date gate: refuse (`PermissionError`) while `_legacy_window_open(now)` is True unless `force`. A **missing or
  malformed** cutoff refuses destructive execution unless forced — `_legacy_window_open` returns `False` for a malformed
  value, which must never be read as permission (check `OAUTH2_LEGACY_KEYS_UNTIL` parse explicitly).
- CLI: existing flags + `--purge --channel <c> [--confirm] [--force]`; counts only; exit code 2 when the gate refuses.
- Tests `test_purge_dry_run_and_date_gate`, `test_purge_deletes_only_channel_keys`.

**NOT in scope**: removing the generic dual-read code; vault cleanup; a backup/rollback path (§8 Q2 open).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` | MODIFY | purge + CLI |
| `packages/ai-parrot/tests/unit/auth/test_legacy_audit_purge.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.legacy_audit import audit_legacy_keys, main             # verified: legacy_audit.py:46, :79
from parrot.auth.oauth2_base import _legacy_window_open                         # verified: oauth2_base.py:79
from parrot.conf import OAUTH2_LEGACY_KEYS_UNTIL                                # verified: used by oauth2_base.py:81
```

### Existing Signatures to Use
```python
# legacy_audit.py (106 lines)
async def _count_keys(resolver, keys, *, prefix) -> Dict[str, Dict[str, int]]   # :17
async def audit_legacy_keys(redis, resolver, *, providers) -> Dict[...]         # :46 ; uses redis.scan_iter(match=...)
def main(argv: Optional[Sequence[str]] = None) -> int                           # :79 ; argparse --provider (append) ; default providers ["jira", "o365"]
#   redis_client = redis.asyncio.from_url(OAUTH2_REDIS_URL) ; asyncio.run(...) ; sys.stdout.write(table)

# oauth2_base.py
def _legacy_window_open(now: Optional[datetime] = None) -> bool                 # :79
#   empty cutoff → True ; malformed → False (logs once) ; else `return current <= parsed` (:97 — window open AT the cutoff instant; purge allowed only strictly after it)
```

### Does NOT Exist
- ~~`purge_legacy_keys`~~ — created here.
- ~~A vault purge~~ — out of scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/auth/test_legacy_audit_purge.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py#main",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py#audit_legacy_keys",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#_legacy_window_open"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `_purge_allowed(now, force)` and `purge_legacy_keys` above `main`.
2. Extend `main` with the purge flags (keep audit behaviour when `--purge` is absent).
3. Tests with an in-memory Redis double supporting `scan_iter(match=)` and `unlink(*keys)` (pattern: `tests/integration/oauth2/test_connections_isolation_matrix.py::MemRedis`).

### `legacy_audit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def main(argv: Optional\[Sequence\[str\]\] = None) -> int:' packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py)
# INSERT ABOVE `def main(` (verified: legacy_audit.py:79):
_UNLINK_BATCH = 500


def _purge_allowed(now: Optional[datetime], force: bool) -> bool:
    """True only after a valid OAUTH2_LEGACY_KEYS_UNTIL has passed (or when forced)."""
    if force:
        return True
    # FILL IN: missing/blank or unparsable OAUTH2_LEGACY_KEYS_UNTIL → False; else `not _legacy_window_open(now)`
    raise NotImplementedError


async def purge_legacy_keys(redis: Any, *, channel: str, providers: Sequence[str], dry_run: bool = True,
                            force: bool = False, now: Optional[datetime] = None) -> Dict[str, int]:
    """Count (and, unless ``dry_run``, UNLINK) legacy keys for one channel. Never reads values.

    Raises:
        PermissionError: before the cutoff (or with a missing/invalid cutoff) unless ``force``.
    """
    if not dry_run and not _purge_allowed(now, force):
        raise PermissionError("legacy key purge refused before OAUTH2_LEGACY_KEYS_UNTIL (use --force to override)")
    # FILL IN: patterns per provider; scan_iter(match=pattern); batch unlink when not dry_run; {pattern: count}
    raise NotImplementedError
# imports: datetime (from datetime import datetime), OAUTH2_LEGACY_KEYS_UNTIL, _legacy_window_open
```
**Why**: the spec says dry runs are always allowed (counts only); only destructive runs pass the gate. FILL IN: if you read
the spec as gating dry runs too, stop and record it — do not guess.

```python
# main(): add parser arguments --purge (store_true), --channel, --confirm (store_true), --force (store_true);
# FILL IN: when --purge: require --channel; dry_run = not args.confirm; PermissionError → stderr message, return 2;
# print "pattern\tcount" lines only.
```

### `tests/unit/auth/test_legacy_audit_purge.py` (CREATE)
```python
"""FEAT-776 M10 purge tests."""
import pytest

@pytest.mark.asyncio
async def test_purge_dry_run_and_date_gate() -> None: ...       # dry run deletes nothing; refused before date unless force; malformed cutoff refused
@pytest.mark.asyncio
async def test_purge_deletes_only_channel_keys() -> None: ...   # telegram keys gone; …:web:*, …:msteams:* untouched
```

### FILL IN checklist
- [ ] `_purge_allowed`, `purge_legacy_keys`, CLI branch
- [ ] Two tests (+ CLI exit code 2 test); monkeypatch `OAUTH2_LEGACY_KEYS_UNTIL` in the module namespace

---

## Acceptance Criteria

- [ ] AC-13; existing `test_legacy_audit.py` passes; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_legacy_audit_purge.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_legacy_audit.py -q`

---

## Test Specification

Blueprint test file; names fixed by spec §4 (M10 rows).

---

## Agent Instructions

1. Work in the feature worktree; verify the Codebase Contract
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5030 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
