# TASK-4735: G5 — Biscuit issue → attenuate → refuse spike

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4737
**Assigned-to**: unassigned

---

## Context

Spec §3 gate **G5 — S5 Biscuit attenuation** (Q7, §8 Q4). Capability tokens are Biscuits issued and attenuated by navigator-auth (external deliverable); Squawk only verifies (M10). G5 proves with `biscuit-python` that a root token scoped to `hr.reports.*` can be attenuated for a sub-agent and that the attenuated token is accepted on `hr.reports.*` and refused on `hr.people.*`; it also documents the navigator-auth issuance gap as a written change request. Its amendment fixes M10's authorizer facts and policies.

---

## Scope

- `spike.py`: generate a root keypair; mint a token with facts `capability_glob("hr.reports.*")`, `caller("external-agent")`, expiry; attenuate with a block adding `check if capability($c), capability_glob($g), $c.matches($g)` narrowed to `hr.reports.headcount_by_dept`; build an authorizer that asserts `capability("<cap_id>")` and verify the three cases (root on reports: allow; attenuated on headcount: allow; attenuated on `hr.people.lookup`: deny; attempt to *widen* fails by construction).
- `report.md`: results, the exact Datalog facts/checks/policies (these become M10's `BiscuitVerifier.authorize` contract), the `biscuit-python` version, and the navigator-auth change request text (root key management, lifetime, attenuation endpoint).
- `packages/ai-parrot-squawk/tests/spikes/test_g5_biscuit_attenuation.py`: opt-in `PARROT_SPIKE=1`, `importorskip("biscuit_auth")`, asserts the three cases.

**NOT in scope**: `BiscuitVerifier` (M10, gated on this spike), any navigator-auth code (outside this repo), mTLS.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/spike.py` | CREATE | Issue / attenuate / authorize demo |
| `sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/report.md` | CREATE | Gate report + Datalog contract + navigator-auth change request |
| `packages/ai-parrot-squawk/tests/spikes/test_g5_biscuit_attenuation.py` | CREATE | Opt-in regression |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from biscuit_auth import KeyPair, BiscuitBuilder, BlockBuilder, Authorizer, Biscuit, PublicKey   # biscuit-python>=0.4.0 — module name is `biscuit_auth`; declared by TASK-4737; verify names against `python -c "import biscuit_auth; print(dir(biscuit_auth))"` and record them in the report
```

### Existing Signatures to Use
None in this repo — the spike is self-contained. Record the `biscuit_auth` API actually used (builders, `authorize()`, error type) in `report.md`; M10's contract is written from that record.

### Does NOT Exist
- ~~Biscuit / macaroon support in `navigator_auth`~~ — verified absent (grep empty, navigator-auth 0.28.7); the change request is the deliverable, not code here.
- ~~`parrot.squawk.security.biscuit`~~ — M10, gated on this spike.
- ~~`biscuit_auth` in the shared venv~~ — comes with the satellite's dependencies after the operator syncs; never install from the worktree.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/spike.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/report.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/spikes/test_g5_biscuit_attenuation.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Token facts must be capability-shaped, never user-shaped: `capability_glob`, `caller`, `expires` — the serving side maps the peer identity (mTLS) to `caller` and refuses a token whose `caller` differs (record this as an M10 rule).
- Glob matching in Datalog: use the `$c.matches($g)` string operation when the installed version supports it; otherwise encode categories as `category("hr.reports")` facts and check prefix membership — report which one works.
- Keys are generated per run and never written to disk.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/token_exchange.py:1-63` — the only navigator-auth token integration today (OAuth2 exchange), cited in the change request as the place an issuer would sit beside.

---

## Implementation Blueprint

### Steps (in order)
1. `issue_root(kp) -> bytes` with the three facts — *why*: the root scope is the category.
2. `attenuate(token, cap_id) -> bytes` adding a narrowing check block — *why*: delegation must only narrow.
3. `authorize(token, public_key, cap_id, caller) -> bool` — *why*: this is the exact logic M10 will ship.
4. Run the four cases; write the report and the navigator-auth change request — *why*: G5's outputs are M10's contract and §8 Q4's request text.

### `sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/spike.py` (CREATE)
```python
"""G5 — Biscuit issue → attenuate → authorize for Squawk capability scopes (FEAT-746)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import biscuit_auth as ba

ROOT_GLOB = "hr.reports.*"


def issue_root(kp: ba.KeyPair, *, caller: str, ttl_h: int = 24) -> ba.Biscuit:
    """Root token: capability_glob, caller, expires."""
    exp = int((datetime.now(timezone.utc) + timedelta(hours=ttl_h)).timestamp())
    builder = ba.BiscuitBuilder(f'capability_glob("{ROOT_GLOB}"); caller("{caller}"); expires({exp});')
    return builder.build(kp.private_key)


def attenuate(token: ba.Biscuit, cap_id: str) -> ba.Biscuit:
    """Narrow to one capability; widening is impossible because checks only add constraints."""
    block = ba.BlockBuilder(f'check if capability("{cap_id}");')
    return token.append(block)


def authorize(token_bytes: bytes, public_key: ba.PublicKey, *, cap_id: str, caller: str, now: int) -> bool:
    """The rule M10 will ship: facts from the call, checks from the token, one allow policy."""
    token = ba.Biscuit.from_bytes(token_bytes, public_key)
    authz = ba.Authorizer(
        f'capability("{cap_id}"); peer("{caller}"); time({now});'
        'check if caller($c), peer($c);'
        'check if expires($e), time($t), $t < $e;'
        'check if capability($c), capability_glob($g), $c.matches($g);'
        'allow if true;'
    )
    authz.add_token(token)
    try:
        authz.authorize()
        return True
    except ba.AuthorizationError:  # FILL IN: confirm the exception class name for the installed version
        return False


def main() -> int:
    kp = ba.KeyPair()
    now = int(datetime.now(timezone.utc).timestamp())
    root = issue_root(kp, caller="external-agent")
    sub = attenuate(root, "hr.reports.headcount_by_dept")
    cases = {
        "root_on_reports": authorize(root.to_bytes(), kp.public_key, cap_id="hr.reports.manager_of", caller="external-agent", now=now),
        "sub_on_headcount": authorize(sub.to_bytes(), kp.public_key, cap_id="hr.reports.headcount_by_dept", caller="external-agent", now=now),
        "sub_on_people": authorize(sub.to_bytes(), kp.public_key, cap_id="hr.people.lookup", caller="external-agent", now=now),
        "root_wrong_caller": authorize(root.to_bytes(), kp.public_key, cap_id="hr.reports.manager_of", caller="other", now=now),
    }
    print(json.dumps(cases, indent=2))
    expected = {"root_on_reports": True, "sub_on_headcount": True, "sub_on_people": False, "root_wrong_caller": False}
    return 0 if cases == expected else 1


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: the three facts + three checks are the minimum M10 needs (spec §3 M10 `authorize` facts: `capability`, `category`, `caller`); `$c.matches($g)` is the glob rule Q7 asks for. If the installed version lacks `.matches`, the FILL IN replaces it with explicit category facts and the report says so.

### `packages/ai-parrot-squawk/tests/spikes/test_g5_biscuit_attenuation.py` (CREATE)
```python
"""G5 regression — attenuated token allowed on hr.reports.*, refused on hr.people.* (opt-in)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PARROT_SPIKE") != "1", reason="spike: set PARROT_SPIKE=1")
pytest.importorskip("biscuit_auth")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/spike.py"


def test_issue_attenuate_refuse():
    spec = importlib.util.spec_from_file_location("g5_spike", SPIKE)
    g5 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g5)
    assert g5.main() == 0
```

### FILL IN checklist
- [ ] `spike.py::authorize` — exception class and `.matches` availability; bounded by the installed `biscuit-python` API (record it)
- [ ] `report.md` — Datalog contract for M10; navigator-auth change request (issuer, root key config, lifetime, attenuation endpoint)

---

## Acceptance Criteria

- [ ] All four cases match the expected table (spec G5 pass criterion: delegated token calls `hr.reports.*`, is refused on `hr.people.*`)
- [ ] `report.md` records the `biscuit-python` version, the exact API and Datalog used, and the navigator-auth change request text (§8 Q4)
- [ ] `PARROT_SPIKE=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g5_biscuit_attenuation.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/spikes/test_g5_biscuit_attenuation.py -q`

---

## Test Specification

See blueprint test.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 G5/M10, §7 risk "Biscuit issuance lives in navigator-auth", §8 Q4
3. **Check dependencies** — TASK-4737 `"done"`; `python -c "import biscuit_auth"` works (operator syncs otherwise)
4. **Verify the Codebase Contract**
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement** from the blueprint
7. **Verify** — Validation Commands with `PARROT_SPIKE=1`
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4735 inter-agent-protocol verified`
10. **Completion Note** — quote the Datalog contract and the change request

---

## Completion Note

**Completed by**: sdd-worker (cherry-pick of minimax.minimax-m2.5 attempt 2, `643a6c228`; commit `8b8ae2760`)
**Date**: 2026-10-27
**Notes**: Closed `forced`. The pool delivery was rejected by the fidelity gate twice: `sdd/ledger/events.jsonl` (ledger hook output, 79/84 lines, not coder-authored) and, on the second run, nine uncommitted scratch `test_biscuit*.py` files. With explicit user approval the three declared files were cherry-picked without them. Review recorded as `coder-review:24d69f106ebd0639c3f357ce` (no fix commits). Merge-tier validation reported `outcome=failed` with exit_code 0: the opt-in spike test is skipped without `PARROT_SPIKE=1`. The user accepted the manual run (`PARROT_SPIKE=1 pytest ... -> 1 passed`) as evidence; `finalize_task` was not used because no review EvidenceRef artifact exists.
**Review edits (docs only)**: report date corrected to 2026-10-27; limitation added — `spike.py` hardcodes `starts_with("hr.reports.")` rather than deriving it from the token's `capability_glob` fact, so M10 must derive the prefix from the verified fact and add a second-glob regression.

**Deviations from spec**: none in file set; see limitation above.
