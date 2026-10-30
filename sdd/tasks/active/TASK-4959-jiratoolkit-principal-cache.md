# TASK-4959: JiraToolkit declares credential_provider and keys its client cache by principal

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4944
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (G2, AC-3). `JiraToolkit._pre_execute` caches clients under `"{channel}:{user_id}"`, so the same
person on two channels builds two clients against one grant. The cache must be keyed by the principal, and the
toolkit declares `credential_provider = "jira"` (the existing broker-seam declaration; no `requires_auth`).

---

## Scope

- `credential_provider = "jira"` class attribute.
- In the non-local branch: `principal = await resolve_principal(channel, user_id)`; `None` → `AuthorizationRequired`
  (auth_url from `credential_resolver.get_auth_url`, which raises the link instruction for unbound users); cache key =
  `principal.user_id`; resolution via `credential_resolver.resolve(channel, user_id)` (already principal-first).
- Keep the local single-user branch (`cli`/`local`) unchanged.
- Test `test_jiratoolkit_cache_keyed_by_principal`.

**NOT in scope**: the AgentTalk hot-swap placeholder (S-3a); Jira API calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | credential_provider + principal cache key |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py` | MODIFY | cache test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import resolve_principal       # TASK-4937
from parrot.auth.exceptions import AuthorizationRequired  # verified: exceptions.py:12 (already used in jiratoolkit)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                                          # :773
            # Per-user JIRA client cache: {"{channel}:{user_id}": (client, token_hash)}   # :1060 anchor
            self._client_cache: Dict[str, tuple] = {}                        # :1061
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:      # :1316 anchor
        # non-local branch: user_key = f"{channel}:{user_id}" (~:1371); token_set = await self.credential_resolver.resolve(channel, user_id)
        # token_hash = access_token[:16] + [-8:]; LRU eviction by _CLIENT_CACHE_MAX_SIZE
# packages/ai-parrot/src/parrot/tools/toolkit.py: credential_provider: str | None = None (:331); propagation to tools (:717-718)
# packages/ai-parrot/src/parrot/tools/abstract.py: broker seam in execute (:1013-1049) — active only when a `_broker` kwarg is present
```

### Does NOT Exist
- ~~`requires_auth`~~ — not a thing; `credential_provider` is the declaration.
- ~~`PermissionContext.principal_id`~~ — resolve the principal from `(channel, user_id)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit._pre_execute",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit"
  ]
}
```

---

## Implementation Notes

- FILL IN before declaring `credential_provider`: read abstract.py:1013-1049 and confirm that with a broker attached the
  seam will not double-resolve or raise for Jira; if the broker has no "jira" provider config, confirm it no-ops.
  Record the finding in the Completion Note.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Class attribute + cache comment (block) — *why*: AC-3 declare-once.
2. Principal-keyed cache in `_pre_execute` — *why*: one client per principal.
3. Test.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# In class JiraToolkit body (near other class attributes):
    credential_provider = "jira"
# occurrences: 1 (verified: grep -c '            # Per-user JIRA client cache: {"{channel}:{user_id}": (client, token_hash)}' → :1060)
            # Per-principal JIRA client cache: {principal.user_id: (client, token_hash)}
# In _pre_execute non-local branch, REPLACE `user_key = f"{channel}:{user_id}"` WITH:
            principal = await resolve_principal(channel, str(user_id))
            if principal is None:
                # FILL IN: auth_url = await self.credential_resolver.get_auth_url(channel, user_id) inside try
                #          (AuthorizationRequired from it → re-raise with tool_name); raise AuthorizationRequired(...)
                raise NotImplementedError
            user_key = principal.user_id
```

### FILL IN checklist
- [ ] broker-seam check (notes)
- [ ] unbound branch
- [ ] `test_jiratoolkit_cache_keyed_by_principal`

---

## Acceptance Criteria

- [ ] Two channels resolving to one principal share one cached client; a token change builds a new client
- [ ] `JiraToolkit.credential_provider == 'jira'`

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py (add)
@pytest.mark.asyncio
async def test_jiratoolkit_cache_keyed_by_principal(monkeypatch): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
