# TASK-809: Add JIRA_ALLOWED_REPORTERS / JIRA_DEFAULT_REPORTER config constants

**Feature**: FEAT-110 — jiraspecialist-webhook-ticket-creation
**Spec**: `sdd/specs/FEAT-110-jiraspecialist-webhook-ticket-creation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec § 3 / Module 2. The handler added in TASK-810 needs a
configurable allow-list of reporter emails plus an optional default
replacement. These live in `parrot.conf`, following the pattern
established by the other `JIRA_*` constants already in that file.

---

## Scope

- Add `JIRA_ALLOWED_REPORTERS: list[str]` via `config.getlist`.
- Add `JIRA_DEFAULT_REPORTER: Optional[str]` via `config.get`.
- Place both next to the existing `JIRA_USERS` block (currently at
  line 551) so future readers see all Jira-auth config together.
- No parsing helper is needed — `navconfig.config.getlist` already
  handles comma-separated env vars.

**NOT in scope**:
- Adding per-project allow-lists (`JIRA_ALLOWED_REPORTERS__NAV=...`).
  The spec defers this as an open question.
- Importing the new constants into `jira_specialist.py` (belongs to
  TASK-810).
- Writing tests (TASK-811).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add two new constants immediately after the `JIRA_USERS` list. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

The file already imports `config` from `navconfig` at module level — no
new imports needed. Check the top of `conf.py` for the exact alias;
every other `JIRA_*` constant in the file uses `config.get(...)` and
`config.getlist(...)` directly.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/conf.py
JIRA_USERS = [                                           # line 551
    {
        "id": "35",
        "name": "Jesus Lara",
        "jira_username": "jesuslarag@gmail.com",
        "telegram_chat_id": "286137732",
        "manager_chat_id": "286137732",
        "username": "jlara@trocglobal.com"
    }
]
JIRA_CLIENT_ID = config.get("JIRA_CLIENT_ID")            # line 561
JIRA_CLIENT_SECRET = config.get("JIRA_CLIENT_SECRET")    # line 562
JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")      # line 563
JIRA_OAUTH_REDIS_URL = config.get(                       # line 564
    "JIRA_OAUTH_REDIS_URL", fallback="redis://localhost:6379/4"
)
```

### Does NOT Exist
- ~~`config.getstrlist`~~ — not a method. Use `config.getlist`.
- ~~`config.get_list`~~ — not a method. Use `config.getlist`.
- ~~`JIRA_REPORTERS` / `JIRA_DEFAULT_ASSIGNEE`~~ — not existing constants
  and not what this task is for. The new names are
  `JIRA_ALLOWED_REPORTERS` and `JIRA_DEFAULT_REPORTER`.
- ~~A fallback of `JIRA_USERS` emails~~ — do not auto-derive the allow-
  list from `JIRA_USERS`. These are orthogonal concepts: developers vs.
  authorized reporters. Leave the fallback empty (`[]`).

---

## Implementation Notes

Add immediately after the `JIRA_OAUTH_REDIS_URL` line (so all Jira
config stays together):

```python
JIRA_ALLOWED_REPORTERS: list[str] = config.getlist(
    "JIRA_ALLOWED_REPORTERS",
    fallback=[],
)
JIRA_DEFAULT_REPORTER: str | None = config.get(
    "JIRA_DEFAULT_REPORTER",
    fallback=None,
)
```

### Key Constraints
- **Fallback values matter.** The handler in TASK-810 treats empty
  list as "feature disabled, skip". Do NOT fall back to a stub email —
  that would flip the feature on by accident.
- **No type annotation imports needed.** `list[str]` and `str | None`
  are PEP 604 built-in syntax; the file already uses `typing` style
  elsewhere — either is fine. Match the style of surrounding lines if
  unsure.
- **No lowercasing or normalisation at read time.** The comparison in
  TASK-810 handles case-insensitivity. Storing the raw list keeps
  config dumps readable and round-trippable.

---

## Acceptance Criteria

- [ ] `from parrot.conf import JIRA_ALLOWED_REPORTERS, JIRA_DEFAULT_REPORTER`
      succeeds.
- [ ] With no env var set, `JIRA_ALLOWED_REPORTERS == []` and
      `JIRA_DEFAULT_REPORTER is None`.
- [ ] With `JIRA_ALLOWED_REPORTERS=a@x.com,b@y.com` in the environment,
      the constant becomes `["a@x.com", "b@y.com"]` (whitespace trimmed
      by `navconfig.config.getlist`).
- [ ] `ruff check packages/ai-parrot/src/parrot/conf.py` is clean.
- [ ] `pytest packages/ai-parrot/tests/ -v -k "not slow"` still passes
      (sanity — no test should break from adding two constants).

---

## Test Specification

No dedicated tests for this task. Coverage lives in TASK-811 via the
handler tests that monkey-patch these constants on the config module.

---

## Agent Instructions

1. Read the spec section 3 / Module 2.
2. Open `packages/ai-parrot/src/parrot/conf.py`, jump to line 551.
3. Add the two lines as shown above, right after `JIRA_OAUTH_REDIS_URL`.
4. Smoke-test in the venv:
   ```bash
   source .venv/bin/activate
   python -c "from parrot.conf import JIRA_ALLOWED_REPORTERS, JIRA_DEFAULT_REPORTER; print(JIRA_ALLOWED_REPORTERS, JIRA_DEFAULT_REPORTER)"
   ```
5. Move this file to `sdd/tasks/completed/` and mark the index entry
   `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
