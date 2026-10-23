# TASK-4653: `MSTeamsAgentConfig` fail-closed on an unsigned-but-authenticated FormDesigner branch

**Feature**: FEAT-733 — MS Teams submit envelope — fail-closed tenant isolation
**Spec**: `sdd/specs/msteams-submit-envelope-fail-closed.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (plus M6's config half). This is **gate 1 of 3**: refuse the
vulnerable configuration at construction time, so a deployment cannot start in
the state that ledger `issue:bcd04b2170a0` describes.

The vulnerable combination is: `formdesigner_allowed_hosts` set (the branch is
enabled) **and** `formdesigner_submit_token` set (the bot forwards with its own
bearer) **and** `formdesigner_submit_secret` unset (no HMAC check runs). In that
state any Teams user can craft an `Action.Submit` naming another tenant and the
bot writes it, authenticated as itself.

This task also lands M6's configuration field (`formdesigner_tenant_map`) because
it is the same file — see "Why combined" below. The *behaviour* that consumes it
belongs to TASK-4655.

---

## Scope

- Add `UnsignedSubmitConfigError(ValueError)` to
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py`.
- Add two fields to `MSTeamsAgentConfig`:
  - `formdesigner_allow_unsigned_submissions: bool = False` (escape hatch, M1)
  - `formdesigner_tenant_map: Optional[Dict[str, str]] = None` (AAD GUID → FormDesigner slug, M6)
- Add env fallbacks for both inside `__post_init__`, following the existing
  FormDesigner fallback shape (`models.py:87-99`):
  - `<NAME>_FORMDESIGNER_ALLOW_UNSIGNED` (spec §8 Q1 — resolved yes)
  - `<NAME>_FORMDESIGNER_TENANT_MAP` (JSON object string)
- Add the validation branch **after** all FormDesigner env fallbacks resolve.
- Add the two fields to the `from_dict`-style constructor block at `models.py:167-171`.
- Write unit tests in `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py`.

**Why combined**: M1 and M6 both modify `models.py`. Per the task-graph rules,
two tasks touching one file must serialize anyway, so splitting them buys no
parallelism and costs a dependency edge plus a merge conflict risk.

**NOT in scope**:
- `verify_envelope()` / `resolve_submit_tenant()` — TASK-4654.
- The wrapper call site — TASK-4655.
- `setup_form_api(teams_signing_secret=...)` — TASK-4656.
- Documentation — TASK-4658.
- Deciding where `formdesigner_tenant_map` comes from operationally (spec §8 Q4
  is open). This task only accepts a dict.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | Exception, two fields, two env fallbacks, validation branch, constructor block |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py` | MODIFY | Unit tests for the new validation and fallbacks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present at the top of models.py — do NOT re-import:
from dataclasses import dataclass, field          # verified: models.py:5
from typing import TYPE_CHECKING, Dict, List, Optional, Any  # verified: models.py:6
from navconfig import config                       # verified: models.py:7
```

`Dict` and `Optional` are already imported — `formdesigner_tenant_map`'s
annotation needs no new import. `logging` is **not** imported in `models.py`
today; add `import logging` if you emit the hatch `WARNING` from this module.

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
@dataclass
class MSTeamsAgentConfig:                                           # line 16
    name: str                                                       # line 32
    chatbot_id: str                                                 # line 33
    app_tenantid: Optional[str] = None                              # line 37
    # FormDesigner card submissions — FEAT-551
    formdesigner_allowed_hosts: Optional[List[str]] = None          # line 62
    formdesigner_submit_token: Optional[str] = None                 # line 63
    formdesigner_submit_secret: Optional[str] = None                # line 64
    formdesigner_submit_timeout: float = 15.0                       # line 65
    formdesigner_api_base_path: str = "/api/v1"                     # line 66

    def __post_init__(self):                                        # line 68
        ...
        # line 87-88  token env fallback
        # line 90-91  secret env fallback
        # line 92-95  allowed-hosts env fallback (comma-split, lowercased)
        # line 96-99  api_base_path env fallback  ← LAST FormDesigner fallback
        # line 100    "# Resolve whitelists from env vars (comma-separated)"
```

The existing fallback idiom, to copy verbatim in shape:

```python
# models.py:90-91
if not self.formdesigner_submit_secret:
    self.formdesigner_submit_secret = config.get(f"{self.name.upper()}_FORMDESIGNER_SUBMIT_SECRET")
```

### Does NOT Exist

- ~~`MSTeamsAgentConfig.formdesigner_require_signature`~~ — the field is
  `formdesigner_allow_unsigned_submissions`. Inverted on purpose: the safe value
  is the falsy default, so omitting it is safe.
- ~~`MSTeamsAgentConfig.app_tenantid` as the FormDesigner tenant~~ — it is the
  **Azure AD tenant GUID** used for `app_type: SingleTenant` bot auth
  (`models.py:37`, resolved at `models.py:78-79`). A different namespace from the
  FormDesigner tenant slug. Never use it as a `{tenant}` path segment and never
  seed `formdesigner_tenant_map` from it.
- ~~`logging` already imported in `models.py`~~ — it is not. Check before use.
- ~~`self.logger` on `MSTeamsAgentConfig`~~ — this is a plain `@dataclass`, not a
  parrot component. There is no `self.logger`. Use a module-level logger.
- ~~A validator decorator / Pydantic hooks~~ — `MSTeamsAgentConfig` is a stdlib
  `@dataclass` (`models.py:15`), not a Pydantic model. Validation goes in
  `__post_init__`, nowhere else.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py#MSTeamsAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py#MSTeamsAgentConfig.__post_init__"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Order is load-bearing.** The validation must run **after** every FormDesigner
  env fallback (i.e. after `models.py:99`), or a secret supplied only through the
  environment would be invisible to the check and a correctly-configured
  deployment would refuse to start. This is an explicit acceptance criterion.
- `MSTeamsAgentConfig` is a stdlib `@dataclass`. No Pydantic, no `self.logger`.
- The hatch warning fires **once per startup** — it lives in `__post_init__`,
  which runs once per config object. Do not add caching or dedup.
- `UnsignedSubmitConfigError` subclasses `ValueError` so a host that already
  guards config construction keeps working unchanged.

### References in Codebase

- `models.py:87-99` — the FormDesigner env-fallback block; copy its shape.
- `models.py:92-95` — the comma-split list fallback; the JSON map fallback is
  the analogous shape for a dict.

---

## Implementation Blueprint

### Steps (in order)

1. Add `import logging` and a module-level `logger` to `models.py` — *why*: the
   hatch must emit a `WARNING`, and this dataclass has no `self.logger`.
2. Define `UnsignedSubmitConfigError(ValueError)` above the dataclass — *why*:
   callers need a specific type to catch; `ValueError` keeps existing guards working.
3. Add the two fields after `formdesigner_api_base_path` — *why*: keeps the whole
   FormDesigner block contiguous and the diff reviewable.
4. Add both env fallbacks immediately after the `api_base_path` fallback — *why*:
   the validation in step 5 reads them, so they must resolve first.
5. Add the validation branch right after the fallbacks — *why*: see Key Constraints.
6. Add both fields to the constructor block at `models.py:167-171` — *why*: a
   config built from a dict must be able to set them too, or YAML-configured bots
   silently cannot opt in.
7. Write the tests — *why*: the ordering bug in step 4/5 is invisible without
   `test_config_secret_from_env_satisfies_check`.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` (MODIFY) — fields

```python
# occurrences: 1 (verified: grep -c '    formdesigner_api_base_path: str = "/api/v1"  # must match setup_form_api(base_path=...) on the FormDesigner side' models.py)
# AFTER — insert below `    formdesigner_api_base_path: str = "/api/v1"  # must match setup_form_api(base_path=...) on the FormDesigner side` (verified: models.py:66)
    formdesigner_allow_unsigned_submissions: bool = False
    """Accept unsigned submit envelopes. DEVELOPMENT ONLY — logs a WARNING on every startup.

    When False (the default) a bearer token without a signing secret is refused at
    construction: tenant/form_uid are client-supplied, so an unsigned envelope is
    unauthenticated routing forwarded under the bot's own credentials.
    """
    formdesigner_tenant_map: Optional[Dict[str, str]] = None
    """Azure AD tenant GUID -> FormDesigner tenant slug. A mapped GUID overrides the envelope's claim."""
```

**Why this shape**: the hatch is inverted (`allow_unsigned`, default `False`) so
that omitting it is the safe choice — spec §2. The map is `Optional` rather than
an empty dict because "no map configured" and "configured empty" must both mean
*fall back to the envelope*, and `None` says so without an extra flag.

### `models.py` (MODIFY) — env fallbacks

```python
# occurrences: 1 (verified: grep -c '                self.formdesigner_api_base_path = str(env_base_path)' models.py)
# AFTER — insert below `                self.formdesigner_api_base_path = str(env_base_path)` (verified: models.py:99)
        if not self.formdesigner_allow_unsigned_submissions:
            raw_allow = config.get(f"{self.name.upper()}_FORMDESIGNER_ALLOW_UNSIGNED")
            # FILL IN: coerce raw_allow to bool — accept the truthy spellings navconfig may
            # return ("1"/"true"/"yes", case-insensitive, and a real bool); bounded by AC
            # "<NAME>_FORMDESIGNER_ALLOW_UNSIGNED sets it through the environment"
        if self.formdesigner_tenant_map is None:
            raw_map = config.get(f"{self.name.upper()}_FORMDESIGNER_TENANT_MAP")
            # FILL IN: parse raw_map as a JSON object of {str: str}; a malformed value must
            # NOT crash startup — log a WARNING and leave the map None (fall back to the
            # envelope); bounded by "an absent or unmapped GUID leaves the envelope untouched"
        if (
            self.formdesigner_allowed_hosts
            and self.formdesigner_submit_token
            and not self.formdesigner_submit_secret
        ):
            if self.formdesigner_allow_unsigned_submissions:
                logger.warning(
                    "%s: FormDesigner submit envelopes are NOT signature-verified "
                    "(%s_FORMDESIGNER_SUBMIT_SECRET unset, unsigned submissions explicitly allowed). "
                    "Any Teams user can target another tenant on an allowed host. Development only.",
                    self.name,
                    self.name.upper(),
                )
            else:
                raise UnsignedSubmitConfigError(
                    f"{self.name}: FormDesigner submissions are enabled with a bearer token but no "
                    f"signing secret. Set {self.name.upper()}_FORMDESIGNER_SUBMIT_SECRET (and the "
                    f"matching teams_signing_secret on the FormDesigner side), or set "
                    f"formdesigner_allow_unsigned_submissions=True for development."
                )
```

**Why**: the three-way `and` is the exact precondition from the ledger issue —
branch enabled, bearer present, no secret. Placing it after `models.py:99` is
what makes an env-only secret count. The message names the variable *and* its
FormDesigner-side counterpart because setting only one of the two is the next
mistake an operator makes (TASK-4656 adds that side).

### `models.py` (MODIFY) — exception + logger

```python
# occurrences: 1 (verified: grep -c 'from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION' models.py)
# AFTER — insert below `from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION` (verified: models.py:9)
import logging

logger = logging.getLogger(__name__)


class UnsignedSubmitConfigError(ValueError):
    """The FormDesigner Teams branch is enabled with a bearer token but no signing secret."""
```

**Why**: a module-level logger, because `MSTeamsAgentConfig` is a plain
dataclass with no `self.logger`. Keep `import logging` with the other stdlib
imports if the module's existing grouping prefers that — the placement of the
import is free, the logger name is not.

### `models.py` (MODIFY) — constructor block

```python
# occurrences: 1 (verified: grep -c '            formdesigner_api_base_path=data.get("formdesigner_api_base_path", "/api/v1"),' models.py)
# AFTER — insert below `            formdesigner_api_base_path=data.get("formdesigner_api_base_path", "/api/v1"),` (verified: models.py:171)
            formdesigner_allow_unsigned_submissions=bool(
                data.get("formdesigner_allow_unsigned_submissions", False)
            ),
            formdesigner_tenant_map=data.get("formdesigner_tenant_map"),
```

**Why**: without this, a bot configured from a dict/YAML can never set either
field, and the hatch would be unreachable for exactly the deployments most
likely to need it.

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        assert config.voice_config is None' test_msteams_models.py)
# AFTER — append at end of file, below `        assert config.voice_config is None` (verified: test_msteams_models.py:EOF)
class TestFormDesignerSubmitConfig:
    """FEAT-733 — the unsigned-but-authenticated combination is refused at construction."""

    def test_config_rejects_token_without_secret(self):
        """hosts + token + no secret -> UnsignedSubmitConfigError naming the env var."""
        # FILL IN: build MSTeamsAgentConfig(name=..., chatbot_id=..., formdesigner_allowed_hosts=[...],
        # formdesigner_submit_token=...) with no secret; assert pytest.raises(UnsignedSubmitConfigError)
        # and that "FORMDESIGNER_SUBMIT_SECRET" is in str(excinfo.value); bounded by AC
        # "the message names <NAME>_FORMDESIGNER_SUBMIT_SECRET"

    def test_config_allows_token_with_secret(self):
        """hosts + token + secret -> constructs cleanly."""
        # FILL IN

    def test_config_allows_no_token_no_secret(self):
        """hosts, no token, no secret -> constructs; there is no bearer to escalate with."""
        # FILL IN

    def test_config_hatch_allows_unsigned_and_warns(self, caplog):
        """hatch True -> constructs and emits exactly one WARNING."""
        # FILL IN: assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1;
        # bounded by AC "logs exactly one WARNING per startup"

    def test_config_secret_from_env_satisfies_check(self, monkeypatch):
        """ORDERING GUARD: a secret supplied only via env must satisfy the check."""
        # FILL IN: monkeypatch the navconfig lookup for <NAME>_FORMDESIGNER_SUBMIT_SECRET,
        # then construct with hosts + token and NO explicit secret; assert no raise.
        # This test fails if the validation runs before the env fallbacks.

    def test_hatch_env_fallback_sets_allow_unsigned(self, monkeypatch):
        """<NAME>_FORMDESIGNER_ALLOW_UNSIGNED=1 turns the hatch on (spec §8 Q1)."""
        # FILL IN
```

**Why**: `test_config_secret_from_env_satisfies_check` is the one test that
catches the ordering mistake in step 4/5, which is otherwise invisible — every
other test passes with the check in the wrong place. Note the tests patch
`navconfig.config`, not `os.environ`: the module reads through
`config.get(...)` (`models.py:7`), so patching the environment alone may not
take effect depending on when navconfig loaded.

### FILL IN checklist

- [ ] `models.py::__post_init__` — truthy-spelling coercion for `<NAME>_FORMDESIGNER_ALLOW_UNSIGNED`; bounded by the env-fallback AC
- [ ] `models.py::__post_init__` — JSON parse of `<NAME>_FORMDESIGNER_TENANT_MAP`, malformed ⇒ `WARNING` + `None`, never a crash
- [ ] `test_msteams_models.py` — all six test bodies, including the ordering guard
- [ ] Confirm how `navconfig.config` is patched in the existing tests in this file and follow it

---

## Acceptance Criteria

- [ ] `MSTeamsAgentConfig` with `formdesigner_allowed_hosts` and
      `formdesigner_submit_token` set and `formdesigner_submit_secret` unset
      raises `UnsignedSubmitConfigError`.
- [ ] The message names `<NAME>_FORMDESIGNER_SUBMIT_SECRET`.
- [ ] The check runs **after** the env fallbacks: a secret provided only through
      the environment satisfies it.
- [ ] `formdesigner_allow_unsigned_submissions=True` permits it and logs exactly
      one `WARNING`.
- [ ] `<NAME>_FORMDESIGNER_ALLOW_UNSIGNED` sets the hatch through the environment.
- [ ] `<NAME>_FORMDESIGNER_TENANT_MAP` parses a JSON object; a malformed value
      logs a `WARNING` and leaves the map `None` — it never raises at startup.
- [ ] Both new fields are settable through the dict constructor block.
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py`

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py -q`

---

## Completion Note

<!-- Filled in by the implementing agent when the task is closed. -->
