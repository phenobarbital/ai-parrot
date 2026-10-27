# TASK-4717: Inter-agent grant — GrantPolicy, attenuation, GrantDenied (M4)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4715
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4**: the caller-side deterministic gate. An agent is granted inter-agent
communication by configuration with a capability-pattern scope (`hr.*`, `*`); the grant is enforced by the
harness and never visible to the model (spec G5, AC-12). Contract Net awards attenuate: the awardee may use only
scopes covered by the requester's (AC-14). The serving side still runs `PBACToolCallGuardrail` — nothing here
replaces it.

---

## Scope

- Create `parrot/roost/grant.py` with `GrantDenied`, `GrantPolicy.allows/attenuate/filter_matches`.
- Write `tests/roost/test_grant.py`.

**NOT in scope**: registry lookup (TASK-4716); Biscuit token attenuation (FEAT-746 M10; resolved Q3 keeps v0 as a scope intersection)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/grant.py` | CREATE | Grant evaluation |
| `packages/ai-parrot/tests/roost/test_grant.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
import fnmatch
from parrot.roost.directory import CapabilityMatch, InterAgentGrant, RoostAgentConfig  # TASK-4715
```

### Existing Signatures to Use
```python
# parrot/roost/directory.py (TASK-4715)
class InterAgentGrant(BaseModel): scopes: list[str]
class RoostAgentConfig(BaseModel): ... grant: Optional[InterAgentGrant]
class CapabilityMatch(BaseModel): agent_name; cap_id; locality; cost; kind; backing; score; category_hash
```

### Does NOT Exist
- ~~`allowed_agents`, `can_call`, `inter_agent` grant config anywhere — 0 hits (the `inter_agent` hits are `MatrixCollaborativeSession.handle_inter_agent_message`, unrelated)~~
- ~~a model-visible grant parameter — forbidden by spec G5~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/grant.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_grant.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `allows`: `config is None or config.grant is None or not scopes` ⇒ False (fail-closed); else any `fnmatch.fnmatchcase(cap_id, scope)`.
- `attenuate(requester, awardee)`: keep each awardee scope `s` for which some requester scope `r` covers it (`fnmatchcase(s.rstrip('*').rstrip('.') or s, r)` or `r == '*'`); requester None ⇒ empty grant.
- `default_deny=False` is only for tests; production always passes True.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- spec §3 Module 4 skeleton

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write `grant.py`.
2. Write tests incl. `*`, `hr.*`, None grant, attenuation intersection.

### `packages/ai-parrot/src/parrot/roost/grant.py` (CREATE)
```python
"""Caller-side inter-agent grant (FEAT-747 M4). Configuration, never model-visible."""
from __future__ import annotations

import fnmatch
import logging
from typing import Iterable, Optional

from .directory import CapabilityMatch, InterAgentGrant, RoostAgentConfig

logger = logging.getLogger(__name__)


class GrantDenied(Exception):
    """A lookup, mount or send targeted a capability outside the caller's grant."""


class GrantPolicy:
    """Deterministic scope check over ``RoostAgentConfig.grant``."""

    def __init__(self, *, default_deny: bool = True) -> None:
        self.default_deny = default_deny

    def allows(self, config: Optional[RoostAgentConfig], cap_id: str) -> bool:
        """True iff a scope of ``config.grant`` fnmatch-es *cap_id*; False when config/grant is missing."""
        raise NotImplementedError  # FILL IN — Key Constraints bullet 1

    def attenuate(self, requester: Optional[InterAgentGrant], awardee: Optional[InterAgentGrant]) -> InterAgentGrant:
        """Scopes the awardee may use for an awarded task (intersection, AC-14)."""
        raise NotImplementedError  # FILL IN — Key Constraints bullet 2

    def filter_matches(self, config: Optional[RoostAgentConfig],
                       matches: Iterable[CapabilityMatch]) -> list[CapabilityMatch]:
        """Keep only matches the caller may call; order preserved."""
        return [m for m in matches if self.allows(config, m.cap_id)]
```
**Why**: Signatures are the spec skeleton verbatim; `filter_matches` is complete because it is a one-liner over `allows`.

### FILL IN checklist
- [ ] `allows` — AC-12
- [ ] `attenuate` — AC-14
- [ ] tests

---

## Acceptance Criteria

- [ ] `hr.*` allows `hr.people.salary` and denies `fin.x`
- [ ] No grant ⇒ denied
- [ ] `attenuate(['hr.*'], ['hr.people.*', 'fin.*']) == ['hr.people.*']`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/grant.py packages/ai-parrot/tests/roost/test_grant.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_grant.py -q`

---

## Test Specification

```python
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.grant import GrantPolicy


def test_allows():
    gp = GrantPolicy()
    cfg = RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"]))
    assert gp.allows(cfg, "hr.people.salary") and not gp.allows(cfg, "fin.x")
    assert not gp.allows(RoostAgentConfig(), "hr.people.salary") and not gp.allows(None, "x")


def test_attenuate():
    g = GrantPolicy().attenuate(InterAgentGrant(scopes=["hr.*"]), InterAgentGrant(scopes=["hr.people.*", "fin.*"]))
    assert g.scopes == ["hr.people.*"]
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4717 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

