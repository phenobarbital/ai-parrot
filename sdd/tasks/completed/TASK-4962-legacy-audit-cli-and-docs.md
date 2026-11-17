# TASK-4962: legacy_audit CLI + connections docs + Identity-Vault ownership doc

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4941, TASK-4954, TASK-4955
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 (AC-13, AC-15), §8 (cutover = deploy + 30 days, no unbound gate). Before the cutover ops runs
`python -m parrot.auth.oauth2.legacy_audit`, which prints per provider and channel how many legacy keys have and do
not have a resolvable principal (read-only, never prints token values). Docs: `docs/auth/connections.md` (provider
onboarding via descriptor + secrets, channel adapter guide, key layout, migration window, sample PDP policy for
`integration:connect`/`disconnect`) and the ownership doc now states the Identity Vault owns every 3LO provider.

---

## Scope

- `oauth2/legacy_audit.py`: `audit_legacy_keys(redis, resolver, *, providers) -> Dict[str, Dict[str, Dict[str, int]]]`
  over `oauth2:{p}:{c}:{u}` and `jira:oauth:{c}:{u}` (SCAN, never KEYS); `main(argv)` builds Redis from
  `OAUTH2_REDIS_URL` and the resolver from `get_principal_resolver()`; prints a table; exit 0.
- `docs/auth/connections.md` (new) and `docs/auth/jira-credential-ownership.md` (update the title/intro + "every 3LO provider").
- Tests `test_legacy_audit_counts` + a docs assertion (AC-15).

**NOT in scope**: the re-encryption job (TASK-4963).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` | CREATE | audit + CLI |
| `docs/auth/connections.md` | CREATE | connections guide |
| `docs/auth/jira-credential-ownership.md` | MODIFY | Identity Vault owns every 3LO provider |
| `packages/ai-parrot/tests/unit/auth/test_legacy_audit.py` | CREATE | unit tests + docs check |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import PrincipalResolver, get_principal_resolver   # TASK-4937
from parrot.conf import OAUTH2_REDIS_URL                                      # verified: conf.py:626
```

### Existing Signatures to Use
```python
# Key layouts to scan (legacy, read-only):
#   oauth2:{provider}:{channel}:{user_id}   (_LEGACY_TOKEN_KEY_TEMPLATE, TASK-4941) — exclude principal keys oauth2:{p}:{user_id}
#   and nonce keys oauth2:{p}:nonce:{nonce}
#   jira:oauth:{channel}:{user_id}          (jira_oauth._TOKEN_KEY_PREFIX)
# docs/auth/jira-credential-ownership.md:1  "# Who owns the Jira credential" (anchor)
```

### Does NOT Exist
- ~~`redis.keys(...)`~~ — do not use; SCAN with `scan_iter(match=...)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py",
      "action": "CREATE"
    },
    {
      "path": "docs/auth/connections.md",
      "action": "CREATE"
    },
    {
      "path": "docs/auth/jira-credential-ownership.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_legacy_audit.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Distinguish 4-segment legacy keys from 3-segment principal keys and `nonce` keys when parsing.
- Output never includes user ids either — counts only.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Write the audit module (block) — *why*: the U3 cutover metric.
2. Write the docs — *why*: AC-15.
3. Tests with `_oauth2_fakes.MemRedis` and a fake resolver.

### `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` (CREATE)
```python
"""Read-only audit of legacy channel-scoped OAuth2 keys (FEAT-773 M10, U3 cutover metric)."""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any, Dict, Optional, Sequence

from parrot.auth.principal import PrincipalResolver, get_principal_resolver

logger = logging.getLogger(__name__)


async def audit_legacy_keys(redis: Any, resolver: PrincipalResolver, *,
                            providers: Sequence[str]) -> Dict[str, Dict[str, Dict[str, int]]]:
    """{provider: {channel: {"bound": n, "unbound": m}}}; never reads or prints token values."""
    # FILL IN: for p in providers: scan "oauth2:{p}:*" keeping 4-segment non-nonce keys; for "jira" also scan
    #          "jira:oauth:*"; parse channel/user; bound if await resolver.resolve(channel, user) is not None
    raise NotImplementedError


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: --provider P (repeatable, default jira o365); prints a table of counts."""
    # FILL IN: argparse; redis.asyncio.from_url(OAUTH2_REDIS_URL); asyncio.run(audit_legacy_keys(...));
    #          print via sys.stdout.write (CLI output, not logging); return 0
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```

### `docs/auth/connections.md` (CREATE)
Sections (FILL IN prose): Principal & key layout (`oauth2:{provider}:{user_id}`, lock key, legacy layouts) ·
Adding a provider (descriptor YAML in `OAUTH2_PROVIDERS_FILE` + `OAUTH2_<PROVIDER>_CLIENT_ID/_CLIENT_SECRET/_REDIRECT_URI`;
post-exchange hooks by name) · Durable owner (Identity Vault via `CredentialStore`; durable-first) · Channel adapters
(`ChannelNotifier`, `PrincipalResolver`, same-process constraint) · Needs-auth contract (`AuthRequiredPayload`) ·
API (`/api/v1/connections*`) · Migration window (`OAUTH2_LEGACY_KEYS_UNTIL` = deploy + 30 d; run `legacy_audit` first)
· Sample PDP policy for `integration:connect` / `integration:disconnect` · Key rotation (`reencrypt`, retirement gate).

### `docs/auth/jira-credential-ownership.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '# Who owns the Jira credential' docs/auth/jira-credential-ownership.md → :1) -->
# Who owns an OAuth2 (3LO) credential
<!-- FILL IN: first paragraph states the Identity Vault (auth.user_identities) owns every 3LO provider's grant
     through CredentialStore (FEAT-773); Redis is the hot cache; keep the Jira history below as context -->
```

### FILL IN checklist
- [ ] `audit_legacy_keys`, `main`
- [ ] connections.md prose
- [ ] ownership doc intro
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-13: `python -m parrot.auth.oauth2.legacy_audit` reports bound/unbound counts per provider and channel without token values
- [ ] AC-15: `docs/auth/connections.md` exists; the ownership doc states the Identity Vault owns every 3LO provider

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_legacy_audit.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_legacy_audit.py
@pytest.mark.asyncio
async def test_legacy_audit_counts(): ...   # seed oauth2:jira:telegram:1, oauth2:jira:telegram:2, jira:oauth:slack:T:U,
                                            # oauth2:jira:1042 (principal key, ignored), oauth2:jira:nonce:x (ignored)
def test_connections_docs_exist(): ...      # AC-15 text assertions
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

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-luna (codex)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only reds are legacy tests/integration/oauth2/test_e2e_{web_connect,telegram_regression,auth_envelope}.py, intentionally rewritten by TASK-4964.
