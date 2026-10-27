# TASK-4655: Wire `require_signature` and tenant derivation into `_handle_formdesigner_submit`

**Feature**: FEAT-733 — MS Teams submit envelope — fail-closed tenant isolation
**Spec**: `sdd/specs/msteams-submit-envelope-fail-closed.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4653, TASK-4654
**Assigned-to**: unassigned

---

## Context

Spec §3 Modules 2 and 6 (call-site halves). TASK-4653 added the config fields
and TASK-4654 added the two pure helpers; this task is the only place they meet.

Two edits in one block of `wrapper.py`:
1. pass `require_signature` to `verify_envelope()`, derived from the escape hatch;
2. extract the Bot Framework-asserted Azure AD tenant GUID from the activity and
   run `resolve_submit_tenant()` — **after** verification, never before.

---

## Scope

- In `_handle_formdesigner_submit`, pass
  `require_signature=not self.config.formdesigner_allow_unsigned_submissions`.
- Immediately after `verify_envelope(...)` returns, extract
  `activity.channel_data["tenant"]["id"]` defensively and call
  `resolve_submit_tenant()`, rebinding `env`.
- Log at `INFO` when a tenant claim was overridden.
- Import `resolve_submit_tenant` in the existing import block at `wrapper.py:36`.
- Write wrapper-level tests in
  `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py`.

**NOT in scope**:
- The config fields themselves — TASK-4653.
- The helpers themselves — TASK-4654.
- Roundtrip / cross-tenant integration tests — TASK-4657.
- Any change to the `EnvelopeRejected` / generic exception handling already at
  `wrapper.py:1085-1089`; it already renders a refusal as text and needs nothing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | Import, `require_signature` argument, tenant derivation |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py` | MODIFY | Wrapper-level tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# wrapper.py:36 is inside an existing multi-symbol import from this module —
# ADD `resolve_submit_tenant` to it, do not write a second import statement.
from .formdesigner_submit import (   # verified: wrapper.py:36 (verify_envelope on that line)
    EnvelopeRejected,
    parse_envelope,
    verify_envelope,
    post_submission,
    extract_answers,
    build_reply_card,
)
```

New symbols this task consumes, both landed by its dependencies:

```python
resolve_submit_tenant            # TASK-4654, formdesigner_submit.py
MSTeamsAgentConfig.formdesigner_allow_unsigned_submissions   # TASK-4653, models.py
MSTeamsAgentConfig.formdesigner_tenant_map                   # TASK-4653, models.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
async def _handle_formdesigner_submit(                               # line 1057
    self, turn_context: TurnContext, submitted_data: Dict[str, Any]
) -> None:
    """Forward a FormDesigner Teams-card submission (spec §3 M4). Never raises; never continues the dialog."""
    allowed = list(self.config.formdesigner_allowed_hosts or [])     # line 1059
    if not allowed: ...                                              # line 1060-1062
    try:
        env = parse_envelope(submitted_data)                         # line 1064
        verify_envelope(                                             # line 1065
            env,
            allowed_hosts=allowed,
            secret=self.config.formdesigner_submit_secret,           # line 1068
            api_base_path=getattr(self.config, "formdesigner_api_base_path", FORMDESIGNER_API_BASE_PATH),
        )
        activity_id = getattr(turn_context.activity, "id", None)     # line 1071
        if activity_id and self._formdesigner_recent.seen(activity_id): ...
        answers = extract_answers(submitted_data)                    # line 1075
        outcome = await post_submission(                             # line 1076
            await self._get_formdesigner_session(), env, answers,
            bearer_token=self.config.formdesigner_submit_token,      # line 1080
            timeout=self.config.formdesigner_submit_timeout,
        )
        self.logger.info("formdesigner submit: form=%s status=%s", env.form_uid, outcome.status)
        await self.send_card(build_reply_card(outcome, env), turn_context)
    except EnvelopeRejected as exc:                                  # line 1085
        await self.send_text(str(exc), turn_context)
    except Exception:                                                # line 1087
        ...
```

The activity's Teams tenant, verified against the installed `botbuilder`:

```python
# botbuilder.schema.Activity has attribute `channel_data`  (verified at runtime)
# botbuilder.schema.teams.TeamsChannelData fields:
#   channel, event_type, team, notification, tenant, meeting, settings, on_behalf_of
# TeamsChannelData._attribute_map['tenant'] -> {'key': 'tenant', 'type': 'TenantInfo'}
# TenantInfo fields: ['id']    ← the Azure AD tenant GUID, the ONLY field
```

On a raw incoming activity `channel_data` arrives as a **plain dict**, so read it
with `.get()`, not attribute access.

### Does NOT Exist

- ~~`TeamsInfo.get_tenant_id()`~~ / ~~`teams_get_tenant_id()`~~ — no such helper.
  `botbuilder.core.teams` exposes only `teams_get_channel_id` and
  `teams_get_selected_channel_id` (verified against the installed package).
  Read `channel_data` directly.
- ~~`turn_context.activity.tenant_id`~~ — not an `Activity` attribute.
- ~~`self.config.app_tenantid` as the FormDesigner tenant~~ — it is the AAD GUID
  for `SingleTenant` bot auth (`models.py:37`), a different namespace from the
  FormDesigner slug. It is also the *bot's* tenant, not the caller's. Never use
  it here.
- ~~`channel_data` always being a dict~~ — it is absent on non-Teams channels and
  in most hand-built test activities. Treat anything without a `tenant.id` as a
  miss and never raise from the extraction.
- ~~`TenantInfo` carrying a name or slug~~ — its only field is `id`.
- ~~A second import statement for `resolve_submit_tenant`~~ — add it to the
  existing block at `wrapper.py:36`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper._handle_formdesigner_submit",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#verify_envelope"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Order: `verify_envelope` → `resolve_submit_tenant`, never the reverse.**
  `resolve_submit_tenant` can rewrite `submit_url`; running it first would let a
  crafted envelope be rewritten into a shape that then passes the host/path
  guard. This is an acceptance criterion with its own test in TASK-4657.
- **The extraction must never raise.** `channel_data` is absent on non-Teams
  channels and in most test activities. A `None`/non-dict/missing-`tenant` case
  is a *miss* that falls through to the envelope, not an error.
- `_handle_formdesigner_submit` "never raises; never continues the dialog"
  (`wrapper.py:1058`). Do not add new `except` clauses — `EnvelopeRejected` is
  already handled at `wrapper.py:1085`.
- Derivation placement relative to the dedupe check (`wrapper.py:1071-1074`) is
  free; put it right after `verify_envelope` so the ordering rule is visible in
  the diff.

### References in Codebase

- `wrapper.py:1065-1070` — the `verify_envelope` call to extend.
- `wrapper.py:1083` — the existing `self.logger.info` shape for this handler.

---

## Implementation Blueprint

### Steps (in order)

1. Add `resolve_submit_tenant` to the existing import block — *why*: a second
   import statement from the same module would be flagged by `ruff`.
2. Add `require_signature=...` to the `verify_envelope` call — *why*: without it
   the call uses the new `True` default, which is correct but makes the hatch
   unreachable from configuration.
3. Insert the derivation immediately after that call — *why*: see Key Constraints.
4. Write the wrapper tests — *why*: the ordering and the no-raise extraction are
   both invisible to the unit tests in TASK-4654.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (MODIFY) — import

```python
# occurrences: 1 (verified: grep -c '    verify_envelope,' wrapper.py)
# AFTER — insert below `    verify_envelope,` (verified: wrapper.py:36)
    resolve_submit_tenant,
```

**Why**: keeps one import block from `.formdesigner_submit`. Reorder the names
if the block is alphabetised — check before inserting.

### `wrapper.py` (MODIFY) — the call site

```python
# occurrences: 1 (verified: grep -c '            verify_envelope(' wrapper.py)
# REPLACE the call and insert the derivation after it (verified: wrapper.py:1065-1070)
            verify_envelope(
                env,
                allowed_hosts=allowed,
                secret=self.config.formdesigner_submit_secret,
                api_base_path=getattr(self.config, "formdesigner_api_base_path", FORMDESIGNER_API_BASE_PATH),
                require_signature=not self.config.formdesigner_allow_unsigned_submissions,
            )
            # Tenant derivation runs AFTER verification: resolve_submit_tenant can rewrite
            # submit_url, and a rewrite before the SSRF/path guard would launder the envelope.
            channel_data = getattr(turn_context.activity, "channel_data", None)
            tenant_info = channel_data.get("tenant") if isinstance(channel_data, dict) else None
            asserted_tenant_id = tenant_info.get("id") if isinstance(tenant_info, dict) else None
            env, tenant_overridden = resolve_submit_tenant(
                env,
                asserted_tenant_id=asserted_tenant_id,
                tenant_map=self.config.formdesigner_tenant_map,
                api_base_path=getattr(self.config, "formdesigner_api_base_path", FORMDESIGNER_API_BASE_PATH),
            )
            if tenant_overridden:
                self.logger.info(
                    "formdesigner submit: tenant claim overridden by the bot-asserted tenant (form=%s, tenant=%s)",
                    env.form_uid,
                    env.tenant,
                )
```

**Why**: the two `isinstance` guards are what make the extraction total — a
non-Teams channel, a `None` `channel_data`, or a test activity without one all
collapse to `asserted_tenant_id=None`, which `resolve_submit_tenant` already
treats as a miss. The comment above the block is not decoration: the ordering is
a security property and the next person to refactor this handler needs to see
why the lines cannot move. Note `env` is **rebound** — everything downstream
(`post_submission`, `build_reply_card`, the `self.logger.info` at line 1083)
then uses the resolved tenant, which is the point.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py` (MODIFY)

```python
# AFTER — append at end of file
class TestFormDesignerSubmitSecurity:
    """FEAT-733 — the wrapper passes the hatch through and derives the tenant after verifying."""

    async def test_require_signature_passed_from_config(self):
        """Hatch False -> verify_envelope called with require_signature=True, and vice versa."""
        # FILL IN: patch verify_envelope in the wrapper's namespace, assert the kwarg for both
        # hatch values; bounded by AC "derives require_signature from the hatch"

    async def test_refused_envelope_never_posts(self):
        """EnvelopeRejected -> post_submission is never awaited, a text refusal is sent."""
        # FILL IN: bounded by AC "a refused envelope never reaches post_submission"

    async def test_derivation_runs_after_verification(self):
        """resolve_submit_tenant is not called when verify_envelope raises."""
        # FILL IN: make verify_envelope raise EnvelopeRejected; assert the resolve mock
        # was never called. This is the ordering guard.

    async def test_mapped_tenant_rebinds_env_for_post(self):
        """A mapped GUID -> post_submission receives the RESOLVED tenant, not the claimed one."""
        # FILL IN: assert on the env passed to the post_submission mock

    async def test_missing_channel_data_does_not_raise(self):
        """An activity with no channel_data -> envelope untouched, submission proceeds."""
        # FILL IN: cover channel_data None AND channel_data without a "tenant" key
```

**Why**: `test_derivation_runs_after_verification` is the regression test for the
ordering constraint — it is the one thing a future refactor of this handler is
most likely to break, and nothing else in the suite would notice.

### FILL IN checklist

- [ ] `wrapper.py` — confirm whether the `.formdesigner_submit` import block is alphabetised and place `resolve_submit_tenant` accordingly
- [ ] `test_formdesigner_wrapper.py` — five test bodies; follow the existing mocking style in this file for `TurnContext` and `send_text`/`send_card`
- [ ] Check how the existing tests in this file build a `turn_context` double before inventing one

---

## Acceptance Criteria

- [ ] `verify_envelope` is called with
      `require_signature=not self.config.formdesigner_allow_unsigned_submissions`.
- [ ] `resolve_submit_tenant` runs strictly **after** `verify_envelope`; an
      envelope that fails verification never reaches it.
- [ ] `env` is rebound, so `post_submission` and `build_reply_card` use the
      resolved tenant.
- [ ] An override logs once at `INFO`; a non-override logs nothing extra.
- [ ] An activity with no `channel_data`, a non-dict `channel_data`, or no
      `tenant` key proceeds normally and raises nothing.
- [ ] A refused envelope never reaches `post_submission`.
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py -q`
- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py -q`

---

## Completion Note

Delivered by gpt-5.6-terra (codex), 1 attempt, merged by engine. Merge-tier run: wrapper tests green; sole remaining red is test_formdesigner_roundtrip (owned by TASK-4657).
