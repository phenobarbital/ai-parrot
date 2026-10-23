# TASK-4672: Write the Jira credential ownership down

**Feature**: FEAT-735 — One owner for the Jira credential
**Spec**: `sdd/specs/services-vault-token-sync-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-4669, TASK-4670, TASK-4671
**Assigned-to**: unassigned
**Discovered-from**: `issue:2e85cce93cab`

---

## Context

Implements **spec §3 Module 4** and satisfies **AC-1** and **AC-6** of the
spec. `issue:2e85cce93cab` was not opened because a write was broken — it was
opened because **nobody could say which store owned the credential**, and two
reviews of TASK-4664 reached opposite conclusions from the same code. Code
alone cannot close that: the next person to add a Jira reader has to be able to
find the answer without re-deriving it.

This task records the decision where it will be found: one page under `docs/`,
plus a pointer in the module docstrings of the two files that implement the
split.

By the time this runs, three tasks have landed: the sink keeps the owner
current at refresh (TASK-4668) and link time (TASK-4669), the badge reads the
owner (TASK-4670), and the two redundant writers are gone (TASK-4671).

---

## Scope

- A new page: which store owns the Jira credential, which copies are derived,
  which were retired, and what a new reader must call.
- The Q3 migration note: existing `jira:*` vault keys are left in place, and
  what would change that.
- A short ownership paragraph in the two module docstrings (AC-1).

### NOT in scope

- Any behaviour change. This task touches docstrings and one Markdown file.
- Documenting `CredentialResolver` or the `unified-credential-broker`
  proposal — out of scope for the whole feature.
- Deleting any vault data.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/auth/jira-credential-ownership.md` | CREATE | The ownership page |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | Module docstring: Redis is the hot cache, the Identity Vault is the owner |
| `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | MODIFY | Module docstring: no longer the Jira store; which providers remain |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `52f1ccd2e`, 2026-10-23. Re-read both docstrings
> before editing — three tasks land in `jira_oauth.py` first.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py — module docstring, lines 1-16.
# Current bullet list ends with:
#   - Store and retrieve tokens from Redis, keyed by ``channel:user_id``.
#   - Handle Atlassian's rotating refresh tokens with a Redis distributed
#     lock to avoid losing tokens when two requests refresh concurrently.
# and closes with the paragraph beginning "The manager never holds
# credentials in memory".

# packages/ai-parrot-server/src/parrot/services/vault_token_sync.py — module
# docstring, lines 1-15. It currently documents the flat key scheme with
# **Jira as its worked example**:
#   Example keys stored for a Jira auth:
#       jira:access_token
#       jira:refresh_token
#       jira:cloud_id
#       jira:site_url
#       jira:account_id
# That example is exactly what TASK-4671 stopped writing — it must change.
```

### Edit Sites

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `jira_oauth.py` | MODIFY | `The manager never holds credentials in memory — everything flows through` | `:14` | 1 (`grep -c`, 2026-10-23) |
| `vault_token_sync.py` | MODIFY | `Example keys stored for a Jira auth:` | `:9` | 1 (`grep -c`, 2026-10-23) |

### Does NOT Exist

- ~~`docs/auth/`~~ — verify with `ls docs/auth` and create the directory if it
  is absent.
- ~~an existing credential-ownership page~~ — check `docs/` before creating, so
  this does not become a second source of truth.
- ~~any remaining Jira reader of the Session Vault~~ — after TASK-4670 and
  TASK-4671 there is none. If `grep -rn "read_tokens.*jira"` finds one, the
  page is wrong: stop and report it instead of documenting a false state.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/auth/jira-credential-ownership.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/auth/jira_oauth.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/services/vault_token_sync.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Write what is **true after TASK-4671**, not what the spec planned. Re-read
  the three implementations before describing them; if any shipped
  `done-with-issues`, say so on the page rather than describing the intent.
- The page is for the next engineer adding a Jira reader. Lead with the answer
  (read the Identity Vault; Redis is the hot path for the toolkit), then the
  reasoning, then the history.
- Name the gap honestly: a first-ever Slack or MS Teams link still writes no
  durable copy, because those flows carry no Navigator user id
  (`issue:187ce3fe3b93`). A page that implies full coverage would be worse
  than none.

---

## Implementation Blueprint

### `docs/auth/jira-credential-ownership.md` (CREATE)

```markdown
# Who owns the Jira credential

> Decided by FEAT-735 (2026-10-23), from `issue:2e85cce93cab`.

## The answer

| Store | Role | Written by | Read by |
|---|---|---|---|
| `auth.user_identities` (Identity Vault) | **durable owner** | ... | ... |
| Redis (`JiraOAuthManager`, TTL 90 d) | hot cache, the tool read path | ... | ... |
| `auth.user_vault_secrets` (Session Vault) | **retired for Jira** | nothing | nothing |

<!-- FILL IN: complete the table from the shipped code, then: -->
<!-- - "Adding a reader": call IdentityStore.get_by_provider + decrypt_credential
       (SYNC); do NOT add a Postgres read to the per-call tool path (spec G4).
     - "Why Redis stays": it is the live JiraToolkit path and the only copy the
       refresh maintained before FEAT-735.
     - "Migration (Q3)": existing jira:* vault keys are LEFT in place, inert
       once unread; a bulk delete is a risk with no payoff. Revisit only if an
       audit requires that a revoked credential leave no copy.
     - "Known gap": a first-ever Slack / MS Teams link writes no durable copy —
       those flows carry no Navigator user id (issue:187ce3fe3b93).
     - "History": TASK-4664 added the third copy; its two reviews disagreed on
       the owner; FEAT-735 Q1 settled it.
     Bounded by AC-1, AC-2, AC-3, AC-4. -->
```

### `packages/ai-parrot/src/parrot/auth/jira_oauth.py` (MODIFY)

```python
# AFTER — the paragraph starting `The manager never holds credentials in memory`
# (verified: jira_oauth.py:14) occurrences: 1
# FILL IN: add two or three sentences — Redis is the hot cache and the tool
# read path; the durable owner is the Identity Vault, kept current by the
# injected ``credential_sink`` at link and refresh time; link to
# ``docs/auth/jira-credential-ownership.md``. Bounded by AC-1.
```

### `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` (MODIFY)

```python
# MODIFY — the Jira worked example
# anchor: `Example keys stored for a Jira auth:` (verified: vault_token_sync.py:9)
# occurrences: 1
# FILL IN: replace the Jira example with a provider that still uses this class
# (fireflies / workiq / entra / o365) and add one line: Jira no longer stores
# here — its owner is the Identity Vault (FEAT-735), see
# docs/auth/jira-credential-ownership.md. Bounded by AC-1, AC-5.
```

**Why**: `vault_token_sync.py`'s docstring currently teaches the exact pattern
this feature removed. Leaving it would send the next reader straight back to
the retired copy.

### Steps (in order)

1. Re-read the three shipped implementations; note anything that differs from
   the spec.
2. `ls docs/auth` and `grep -rn` for an existing ownership page.
3. Write the page.
4. Update the two docstrings, each pointing at the page.

### FILL IN checklist

- [ ] the ownership table, filled from the shipped code; AC-1, AC-2
- [ ] "Adding a reader" and the G4 warning; AC-2
- [ ] the Q3 migration note; AC-3
- [ ] the known Slack / Teams gap; AC-4
- [ ] both module docstrings, each linking the page; AC-1, AC-5

---

## Acceptance Criteria

- [ ] AC-1 One store is named the durable owner in `docs/` **and** in both
      module docstrings; the page says which copies are derived and which were
      retired (spec AC-1)
- [ ] AC-2 The page tells a new reader exactly what to call, and warns against
      putting a Postgres read on the per-call tool path (spec G4)
- [ ] AC-3 The page records the Q3 decision — existing `jira:*` vault keys are
      left in place — and what would change it (spec AC-6)
- [ ] AC-4 The page names the remaining gap: a first-ever Slack / MS Teams link
      writes no durable copy (`issue:187ce3fe3b93`)
- [ ] AC-5 `vault_token_sync.py`'s docstring no longer uses Jira as its worked
      example
- [ ] AC-6 No behaviour change: the only Python edits are docstrings

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_vault_token_sync_f4_regression.py -q`

---

## Test Specification

No new tests: this task changes documentation and docstrings only. The two
commands above are regression guards proving the edited modules still import
and behave identically.

---

## Agent Instructions

Describe what shipped, not what was planned — re-read the three
implementations first. Do not change a single line of executable code: every
Python edit in this task is inside a docstring.

---

## Completion Note

**Completed 2026-10-23** (verification: verified).

`docs/auth/jira-credential-ownership.md` created (the `docs/auth/` directory
did not exist; checked for an existing ownership page first — there is none).
It describes what **shipped**, re-read from the three implementations, not
what the spec planned.

Both docstrings updated and pointing at it. `vault_token_sync.py`'s was the
more important of the two: it used Jira as its worked example of the flat key
scheme — the exact pattern TASK-4671 retired — so it would have sent the next
reader straight back to the dead copy. It now documents fireflies and states
that Jira is not stored there.

**Honest gap, recorded on the page rather than smoothed over**: a first-ever
Jira link from Slack or MS Teams still writes no durable copy, because those
flows carry no Navigator user id in the OAuth state. A re-link works via the
account fallback. The page names `issue:187ce3fe3b93` as the fix and warns
against closing it by inventing an id at the callback, citing the two ids that
have already been written into a `bigint` column here.

**Evidence**: `pytest test_jira_oauth_manager.py test_vault_token_sync_f4_regression.py
test_vault_token_sync.py -q` → 64 passed; `ruff check` clean. Every Python
edit in this task is inside a docstring — no executable line changed (AC-6).
