# TASK-4656: `teams_signing_secret` on `setup_form_api` — make the producing side signable

**Feature**: FEAT-733 — MS Teams submit envelope — fail-closed tenant isolation
**Spec**: `sdd/specs/msteams-submit-envelope-fail-closed.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. This is **gate 3 of 3**, and it is the reason FEAT-733 is a
spec rather than a configuration change.

`setup_form_api()` calls `register_teams_renderer()` at `routes.py:316` passing
only `public_base_url`, `api_base_path`, `ui_base_path` and `renderer` — **no
`signing_secret`**, and `setup_form_api` has no parameter for one.
`register_teams_renderer()` *does* accept `signing_secret` (`render.py:122`) and
forwards it to `TeamsFormRenderer` (`render.py:144`), so the capability exists
and is simply unreachable from the documented entry point.

Consequence today: every host that wires Teams the documented way emits
envelopes with `sig: null`, and configuring the bot-side secret would reject
every legitimate submission. That is why the deployment has no secret set.

**This must ship with TASK-4653.** TASK-4653 refuses to start a bot that has a
bearer token and no secret; without this task there is no supported way to make
the producing side sign, so the pairing would be unsatisfiable.

---

## Scope

- Add `teams_signing_secret: str | None = None` to `setup_form_api()`.
- Fall back to the environment variable `FORMDESIGNER_TEAMS_SIGNING_SECRET`.
- Forward it to `register_teams_renderer(signing_secret=...)` at `routes.py:316`.
- Document the parameter in the `setup_form_api` docstring, next to the existing
  `public_base_url` / `teams_renderer` entries.
- Write tests in `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py`.

**NOT in scope**:
- Any change to `register_teams_renderer()` — it already accepts the argument.
- Any change to `TeamsFormRenderer` or `TeamsSubmitEnvelope.sign()`.
- The bot side (`models.py`, `formdesigner_submit.py`, `wrapper.py`) — other tasks.
- Documentation of the pairing — TASK-4658.
- Comparing or synchronizing the two secrets in code. They live in different
  distributions and are deployed separately; a cross-check would create coupling
  that does not exist (spec §7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Parameter, env fallback, forwarding, docstring |
| `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py` | MODIFY | Tests for forwarding, env fallback, renderer precedence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test-side, already present in test_setup_form_api.py:
from parrot_formdesigner.api import setup_form_api            # verified: test_setup_form_api.py:7
from parrot_formdesigner.api.render import _RENDERERS         # verified: test_setup_form_api.py:8
from parrot_formdesigner.services.registry import FormRegistry  # verified: test_setup_form_api.py:9
```

`test_setup_form_api.py` already has an autouse fixture that snapshots and
restores `_RENDERERS` (`test_setup_form_api.py:12-18`) — reuse it, do not add a
second one.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(
    ...,
    public_base_url: str | None = None,                               # line 214
    teams_renderer: "AbstractFormRenderer | None" = None,             # line 215
) -> None:
    ...
    render_module.register_teams_renderer(                            # line 316
        public_base_url=public_base_url,                              # line 317
        api_base_path=base_path,                                      # line 318
        ui_base_path=app.get("_form_prefix", ""),                     # line 319
        renderer=teams_renderer,                                      # line 320
    )

# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
def register_teams_renderer(                                          # line 117
    *,
    public_base_url: str | None = None,                               # line 119
    api_base_path: str = "/api/v1",                                   # line 120
    ui_base_path: str = "",                                           # line 121
    signing_secret: str | None = None,                                # line 122  ← already accepted
    renderer: AbstractFormRenderer | None = None,                     # line 123
) -> bool:
    # line 136  if renderer is None:
    # line 137      if not (public_base_url or os.environ.get(PUBLIC_URL_ENV)):  -> returns False
    # line 140      renderer = TeamsFormRenderer(
    # line 144          signing_secret=signing_secret,
    # line 146  register_renderer(TEAMS_FORMAT_KEY, renderer)

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
class TeamsFormRenderer(AdaptiveCardRenderer):                        # line 88
    def __init__(self, public_base_url=None, *, api_base_path="/api/v1",
                 ui_base_path="", signing_secret: str | None = None,
                 version=None) -> None: ...                           # line 94
        self.signing_secret = signing_secret                          # line 108
```

The existing env-var idiom in this area, for the shape to copy:

```python
# render.py:132,137 — os.environ, lazily imported inside the function
import os
if not (public_base_url or os.environ.get(PUBLIC_URL_ENV)):
```

### Does NOT Exist

- ~~`setup_form_api(signing_secret=...)`~~ — not a parameter today. The whole
  point of this task.
- ~~`FORMDESIGNER_TEAMS_SIGNING_SECRET`~~ — no such environment variable exists
  yet; this task introduces it. The existing `PUBLIC_URL_ENV`
  (`FORMDESIGNER_PUBLIC_URL`, `renderers/teams.py`) is unrelated and must not be
  reused or renamed.
- ~~`register_teams_renderer` needing a change~~ — it already accepts and
  forwards `signing_secret`. Touching it is out of scope.
- ~~`navconfig.config` in `parrot-formdesigner`~~ — this package reads the
  environment with `os.environ` (`render.py:132`), not navconfig. Follow the
  local convention, not `models.py`'s.
- ~~`TeamsFormRenderer.secret`~~ — the attribute is `signing_secret`
  (`teams.py:108`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py#register_teams_renderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py#TeamsFormRenderer"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **An explicit `teams_renderer=` still wins**, unchanged. A host that already
  builds its own `TeamsFormRenderer` (today's only way to get signing) must not
  have its renderer replaced or its secret overridden. `register_teams_renderer`
  already implements that precedence at `render.py:136`; just do not break it by
  constructing a renderer in `routes.py`.
- Use `os.environ`, not navconfig — see "Does NOT Exist".
- Passing the argument through is the whole change; resist adding validation
  (length, entropy) that the bot side does not mirror.

### References in Codebase

- `render.py:136-145` — the precedence and construction this task feeds.
- `routes.py:262-274` — the docstring block where `public_base_url` and
  `teams_renderer` are documented; the new entry goes with them.

---

## Implementation Blueprint

### Steps (in order)

1. Add the parameter next to `teams_renderer` — *why*: keeps the Teams-related
   arguments contiguous in a long signature.
2. Add the docstring entry — *why*: this parameter's absence is what caused the
   vulnerability to be unfixable; an undocumented fix repeats the mistake.
3. Forward it with an `os.environ` fallback at the call site — *why*: the env
   fallback is how a deployment sets it without code changes.
4. Write the three tests — *why*: `test_setup_form_api_explicit_renderer_still_wins`
   guards the one behaviour an operator already depends on.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY) — signature

```python
# occurrences: 1 (verified: grep -c '    teams_renderer: "AbstractFormRenderer | None" = None,' routes.py)
# AFTER — insert below `    teams_renderer: "AbstractFormRenderer | None" = None,` (verified: routes.py:215)
    teams_signing_secret: str | None = None,
```

**Why**: keyword with a `None` default, so every existing call site stays valid
and an unconfigured deployment behaves exactly as today.

### `routes.py` (MODIFY) — docstring

```python
# occurrences: 1 (verified: grep -c '            ``None`` (default) defers to ``public_base_url`` / env var.' routes.py)
# AFTER — insert below `            ``None`` (default) defers to ``public_base_url`` / env var.` (verified: routes.py:274)
        teams_signing_secret: HMAC secret used to sign the ``_formdesigner``
            routing envelope of each Teams card. Falls back to the
            ``FORMDESIGNER_TEAMS_SIGNING_SECRET`` environment variable.
            ``None`` (default) emits envelopes with ``sig: null``, which a bot
            configured with ``formdesigner_submit_secret`` rejects — the two are
            one setting in two places and must be given the same value. Ignored
            when ``teams_renderer`` is supplied; configure the secret on that
            renderer instead.
```

**Why**: states the pairing at the point of use. "Ignored when `teams_renderer`
is supplied" is the non-obvious part and is the behaviour tested below.

### `routes.py` (MODIFY) — forwarding

```python
# occurrences: 1 (verified: grep -c '    render_module.register_teams_renderer(' routes.py)
# REPLACE the call at `    render_module.register_teams_renderer(` (verified: routes.py:316-321)
    render_module.register_teams_renderer(
        public_base_url=public_base_url,
        api_base_path=base_path,
        ui_base_path=app.get("_form_prefix", ""),
        signing_secret=teams_signing_secret or os.environ.get("FORMDESIGNER_TEAMS_SIGNING_SECRET"),
        renderer=teams_renderer,
    )
```

**Why**: `or` gives the explicit argument precedence over the environment, which
matches how `public_base_url` behaves in `TeamsFormRenderer.__init__`
(`teams.py:105`). An empty-string secret collapses to the env lookup and then to
`None`, which is the safe direction.

**FILL IN**: confirm `os` is imported at module scope in `routes.py`; if it is
not, add the import rather than doing a function-local import — *why*: a
function-local `import os` is the pattern in `render.py:132` only because that
function is on a deliberately-light import path, which `routes.py` is not.

### `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py` (MODIFY)

```python
# AFTER — append at end of file
class TestTeamsSigningSecret:
    """FEAT-733 — the producing side must be able to sign through the documented entry point."""

    def test_setup_form_api_forwards_signing_secret(self):
        """setup_form_api(teams_signing_secret=...) -> the registered renderer carries it."""
        # FILL IN: build an aiohttp web.Application and a FormRegistry as the existing tests in
        # this file do, call setup_form_api(..., public_base_url="https://forms.test",
        # teams_signing_secret="s3cret"), then assert _RENDERERS["teams"].signing_secret == "s3cret";
        # bounded by AC "reaches TeamsFormRenderer.signing_secret"

    def test_setup_form_api_signing_secret_from_env(self, monkeypatch):
        """FORMDESIGNER_TEAMS_SIGNING_SECRET is used when the argument is omitted."""
        # FILL IN: monkeypatch.setenv("FORMDESIGNER_TEAMS_SIGNING_SECRET", "from-env")

    def test_setup_form_api_explicit_renderer_still_wins(self):
        """An explicit teams_renderer= is registered as-is; the secret argument does not replace it."""
        # FILL IN: pass a sentinel renderer object plus teams_signing_secret=...; assert
        # _RENDERERS["teams"] is that exact object; bounded by AC "an explicit teams_renderer still wins"
```

**Why**: the autouse `_reset_renderers` fixture (`test_setup_form_api.py:12-18`)
already isolates `_RENDERERS` between tests — rely on it. Follow the existing
tests in this file for how an app and registry are constructed; do not invent a
new fixture shape.

### FILL IN checklist

- [ ] `routes.py` — confirm/add the module-scope `import os`
- [ ] `test_setup_form_api.py` — three test bodies, following the file's existing app/registry construction

---

## Acceptance Criteria

- [ ] `setup_form_api(teams_signing_secret=...)` reaches
      `TeamsFormRenderer.signing_secret`.
- [ ] `FORMDESIGNER_TEAMS_SIGNING_SECRET` is used when the argument is omitted;
      the explicit argument wins over the environment.
- [ ] An explicit `teams_renderer=` is still registered unchanged.
- [ ] Omitting both leaves behaviour byte-for-byte as today (`sig: null`).
- [ ] `register_teams_renderer()` is unmodified.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`

---

## Completion Note

Delivered by gpt-5.6-luna (codex), 1 attempt, merged by engine. test_setup_form_api passes (6 passed).
