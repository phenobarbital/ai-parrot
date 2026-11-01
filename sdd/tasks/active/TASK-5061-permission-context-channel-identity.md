# TASK-5061: `PermissionContext.channel_user_id` + `credential_channel_user_id()` helper

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Principal (M1)", §3 Module 1, §8 Q1, AC-13. A Teams turn's `PermissionContext` carries the
**Navigator** id in `session.user_id` (PBAC is evaluated against it), but Jira/O365 OAuth lookup must use the
**AAD oid** — the channel identity FEAT-773's resolver maps to the Navigator principal. This task adds the
explicit, trusted channel-identity field and the one helper every OAuth toolkit uses to pick the lookup id.

---

## Scope

- Add `channel_user_id: Optional[str] = None` to the `PermissionContext` dataclass (additive; default keeps
  every existing caller unchanged). Document it: populated only by trusted channel code, never from tool
  arguments or card data.
- Add `credential_channel_user_id(context) -> Optional[str]` in `auth/credentials.py`:
  `channel == "msteams"` → the nonempty `context.channel_user_id` or `None`; every other channel → the existing
  `context.user_id` (string) behavior.
- Unit tests in `test_credential_channel_identity.py`.

**NOT in scope**: changing `OAuthCredentialResolver` (no heuristic there), the toolkits (TASK-5062), building
the Teams context (TASK-5066).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/permission.py` | MODIFY | additive dataclass field + docstring line |
| `packages/ai-parrot/src/parrot/auth/credentials.py` | MODIFY | `credential_channel_user_id` helper |
| `packages/ai-parrot/tests/auth/test_credential_channel_identity.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.permission import PermissionContext, UserSession   # verified: auth/permission.py:81, :21
```
`auth/credentials.py` must import `PermissionContext` only under `TYPE_CHECKING` (it already has a
`TYPE_CHECKING` block at credentials.py:36) — a runtime import risks a cycle.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen=True)
class UserSession:  user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict   # :21, fields :46-49
@dataclass
class PermissionContext:                                                         # :81
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    trace_context: "Optional[TraceContext]" = None                               # :125
    extra: dict[str, Any] = field(default_factory=dict)                          # :126
    @property user_id -> str  (session.user_id)
def build_principal_context(principal, *, channel, tenant_id=None, roles=None) -> PermissionContext   # :166
def to_eval_context(context) -> EvalContext                                      # :209

# packages/ai-parrot/src/parrot/auth/credentials.py
class OAuthCredentialResolver(CredentialResolver):                               # :214
```

### Does NOT Exist
- ~~`PermissionContext.channel_user_id`~~ — added here.
- ~~`credential_channel_user_id`~~ — added here.
- ~~`PermissionContext.principal`~~ — no such field; do not add one.
- ~~numeric-string inference of a Navigator id from `user_id`~~ — forbidden by the spec (§2 M1).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/permission.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/credentials.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_credential_channel_identity.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext",
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#OAuthCredentialResolver"
  ]
}
```

---

## Implementation Notes

- Put the new field **after** `extra` — dataclass fields with defaults may be appended; inserting before
  `extra` would shift positional constructor calls (search: `PermissionContext(` with positional args).
- The helper is pure: no I/O, no resolver call. A missing Teams identity returns `None`; callers turn that into
  needs-auth without calling the resolver.

---

## Implementation Blueprint

### Steps (in order)
1. Add the field after `extra` — *why*: additive and positional-safe.
2. Add one docstring `Attributes:` line for it — *why*: the docstring is the contract for trusted population.
3. Add the helper above `OAuthCredentialResolver` — *why*: the spec's edit-site row anchors there.
4. Tests; Validation Commands.

### `packages/ai-parrot/src/parrot/auth/permission.py` (MODIFY)
```python
# AFTER — insert below `    extra: dict[str, Any] = field(default_factory=dict)` (verified: permission.py:126)
# occurrences: 1 (verified: grep -cxF '    extra: dict[str, Any] = field(default_factory=dict)' permission.py)
    channel_user_id: Optional[str] = None
```
Add to the class docstring `Attributes:` list (after `extra`):
```
        channel_user_id: Trusted raw identity on ``channel`` (e.g. the Teams AAD oid). Set only by channel
            code from a validated session; never from tool arguments or card data. ``None`` by default.
```
**Why**: spec §6 "Additive contracts owned by this feature".

### `packages/ai-parrot/src/parrot/auth/credentials.py` (MODIFY)
```python
# BEFORE — insert above `class OAuthCredentialResolver(CredentialResolver):` (verified: credentials.py:214)
# occurrences: 1 (verified: grep -cxF 'class OAuthCredentialResolver(CredentialResolver):' credentials.py)
_EXPLICIT_CHANNEL_IDENTITY = frozenset({"msteams"})


def credential_channel_user_id(context: "PermissionContext") -> Optional[str]:
    """Return the channel identity an OAuth toolkit must use for credential lookup.

    Teams requires the explicit, trusted ``context.channel_user_id`` (the AAD oid); every other channel
    keeps the existing behaviour of using ``context.user_id``.

    Args:
        context: The caller's permission context.

    Returns:
        The lookup identity, or ``None`` when a Teams context carries no channel identity (fail closed).
    """
    channel = getattr(context, "channel", None)
    if channel in _EXPLICIT_CHANNEL_IDENTITY:
        # FILL IN: return the stripped channel_user_id when nonempty, else None — bounded by AC-13 (no fallback
        # to context.user_id, no numeric inference)
        ...
    user_id = getattr(context, "user_id", None)
    return str(user_id) if user_id else None
```
Add `from .permission import PermissionContext` inside the existing `if TYPE_CHECKING:` block (credentials.py:36).
**Why**: one helper, so Jira and O365 cannot drift; Teams gets no implicit fallback.

### `packages/ai-parrot/tests/auth/test_credential_channel_identity.py` (CREATE)
```python
"""FEAT-775 M1: explicit channel identity on PermissionContext."""
from parrot.auth.credentials import credential_channel_user_id
from parrot.auth.permission import PermissionContext, UserSession


def _ctx(channel, user_id="42", channel_user_id=None):
    return PermissionContext(
        session=UserSession(user_id=user_id, tenant_id="t-1", roles=frozenset()),
        channel=channel,
        channel_user_id=channel_user_id,
    )


def test_teams_uses_explicit_channel_identity():
    assert credential_channel_user_id(_ctx("msteams", channel_user_id="aad-1")) == "aad-1"


def test_teams_missing_identity_fails_closed():
    # FILL IN: None and "" channel_user_id both → None, even though user_id="42" — bounded by AC-13
    ...


def test_other_channels_keep_user_id():
    # FILL IN: telegram / web / None channel → "42"; channel_user_id ignored — bounded by AC-13 (preserve non-Teams)
    ...


def test_field_defaults_to_none_and_is_positional_safe():
    # FILL IN: PermissionContext(session, "req", "web") still works; channel_user_id is None
    ...
```

### FILL IN checklist
- [ ] Teams branch in the helper
- [ ] three test bodies

---

## Acceptance Criteria

- [ ] `PermissionContext(...)` without the new keyword behaves exactly as before.
- [ ] Teams: helper returns only the explicit identity; missing → `None` (AC-13).
- [ ] Non-Teams: helper returns `context.user_id` (AC-13).
- [ ] `ruff check` clean on touched files.

## Validation Commands
- `pytest packages/ai-parrot/tests/auth/test_credential_channel_identity.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_teams_uses_explicit_channel_identity` | oid returned |
| `test_teams_missing_identity_fails_closed` | `None` for missing/empty |
| `test_other_channels_keep_user_id` | unchanged behavior |
| `test_field_defaults_to_none_and_is_positional_safe` | backward compatibility |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

