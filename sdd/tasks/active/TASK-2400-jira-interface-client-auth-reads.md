# TASK-2400: `JiraInterface` — auth resolution, lazy `jira` import, read surface

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2399
**Assigned-to**: unassigned

---

## Context

Second half of **Module 1** (spec §3 M1, §2 "New Public Interfaces", G1).
Builds `JiraInterface`: the single Jira read implementation in the repo, which
both `JiraToolkit` (TASK-2402) and the sweep (TASK-2403) consume. This is the
task that makes G1 true — *"one core implementation of Jira reads, no
duplicated client code."*

Two disciplines carried over from `JiraToolkit` are non-negotiable here
because getting either wrong is silent and self-perpetuating:

1. **No auth heuristic.** An unresolved `auth_type` leaves the interface
   *unauthenticated*; every read raises. The legacy code guessed `basic_auth`
   from an `atlassian.net` URL and silently pulled env credentials, producing
   a shared service-account client — see the long comment at
   `jiratoolkit.py:767-775`.
2. **An empty result set is not proof of an empty scope.** Jira Cloud answers
   a failed auth with `200` + an empty list + `X-Seraph-Loginreason:
   AUTHENTICATED_FAILED`. Trusting it would advance the sweep's watermark over
   a corpus that was never fetched — the worst failure mode in this feature.

Also lands the resolved AC-field decision (spec §8): `JIRA_WIKI_AC_FIELD`
wins when set, otherwise resolve by field *name* from `/rest/api/2/field`,
cache it, and degrade to `None`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/interfaces/jira/client.py` with
  `JiraInterface` per the spec's signature (plus `resolve_ac_field_id`).
- Lazy-import `jira` inside the method that first needs a client, raising an
  actionable error naming the install extra — never letting a raw
  `ModuleNotFoundError` escape.
- Implement all four auth modes with full parity: `basic_auth`, `token_auth`,
  `oauth` (OAuth 1.0a), and `oauth2_3lo` via the already-core
  `JiraOAuthManager`.
- Implement the reads: `verify_auth`, `get_issue`, `search_issues` (async
  paginating iterator), `get_changelog`, `get_projects`, `get_remote_links`,
  and `resolve_ac_field_id`.
- Attach the pure projection from TASK-2399 as `JiraInterface.parse_issue`
  (a `@staticmethod` delegating to `parse.parse_issue` — no duplicated logic).
- Implement the `AUTHENTICATED_FAILED` probe: an empty result page triggers a
  `/myself` check, and a failed probe raises.
- Wrap the synchronous `jira` client in `asyncio.to_thread` — no blocking I/O
  in an async path.
- Extend `parrot/interfaces/jira/__init__.py` to export `JiraInterface` and
  the error types.
- Write the unit tests listed below.

**NOT in scope**:
- Any Jira **write** (transition, comment, assign, create). This interface is
  read-only; ticket mutation stays `JiraToolkit`'s job.
- Refactoring `JiraToolkit` to use this — TASK-2402.
- Markdown rendering — TASK-2401. The sweep — TASK-2403.
- Fetching ticket **comments** — explicit v1 non-goal.
- Downloading attachment payloads — explicit non-goal (refs only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/jira/client.py` | CREATE | `JiraInterface` + auth + reads |
| `packages/ai-parrot/src/parrot/interfaces/jira/errors.py` | CREATE | `JiraInterfaceError`, `JiraAuthError`, `JiraDependencyError` |
| `packages/ai-parrot/src/parrot/interfaces/jira/__init__.py` | MODIFY | Export `JiraInterface` + errors |
| `packages/ai-parrot/tests/interfaces/jira/test_jira_interface.py` | CREATE | Auth-mode, lazy-import, pagination, seraph-probe tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing code.

### Verified Imports

```python
# Core, already present — SAFE to import at module load:
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet  # jira_oauth.py:86, :59

# This feature's own, from TASK-2399:
from .models import JiraIssue, JiraPerson
from .parse import parse_issue

# Standard:
import asyncio, logging, os
from typing import Any, AsyncIterator

# LAZY ONLY — never at module scope:
#     from jira import JIRA
```

`nav_config` is optional in this repo. Resolve it the way `JiraToolkit` does
(see `_cfg` below) and tolerate its absence.

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:751-760
# The config idiom to copy — navconfig FIRST, then os.getenv:
def _cfg(key: str, default: Optional[str] = None) -> Optional[str]:
    if (nav_config is not None) and hasattr(nav_config, "get"):
        val = nav_config.get(key)
        if val is not None:
            return str(val)
    return os.getenv(key, default)

# jiratoolkit.py:767-775 — THE NO-HEURISTIC RULE (copy this discipline):
_configured_auth = auth_type or _cfg("JIRA_AUTH_TYPE")
if _configured_auth:
    self.auth_type = _configured_auth.lower()
else:
    self.auth_type = None      # unauthenticated; every call must raise
# jiratoolkit.py:780 — server_url = server_url or _cfg("JIRA_INSTANCE") or ""
#   For oauth2_3lo the server URL is resolved PER-USER at runtime, so it is
#   optional in that mode only.

# jiratoolkit.py:955 — _init_jira_client() -> JIRA. Static modes:
options = {"server": self.server_url, "verify": False,
           "headers": {"Accept-Encoding": "gzip, deflate"}}
#   basic_auth -> JIRA(options=options, basic_auth=(username, password), timeout=...)
#     raises ValueError("basic_auth requires username and password")
#   token_auth -> JIRA(options=options, token_auth=self.token, timeout=...)
#     raises ValueError("token_auth requires a Personal Access Token")
#   oauth      -> JIRA(options=options, oauth={access_token,
#                      access_token_secret, consumer_key, key_cert}, timeout=...)
#     key_cert via self._read_key_cert(self.oauth_key_cert) — PEM content OR path
#   else       -> raise ValueError(f"Unsupported auth_type: {self.auth_type}")

# jiratoolkit.py:1017 — _init_jira_client_from_token(token_set) -> JIRA (3LO):
options = {"server": token_set.api_base_url, "verify": True,
           "headers": {"Authorization": f"Bearer {token_set.access_token}",
                       "Accept-Encoding": "gzip, deflate"}}
return JIRA(options=options, timeout=self.request_timeout)
# jiratoolkit.py:1030-1033 — _OAUTH_SCOPES mirrors
#   parrot.auth.jira_oauth.DEFAULT_SCOPES to avoid a hard import:
#   ("read:jira-work", "write:jira-work", "read:jira-user", "offline_access")
#   NOTE: this interface is READ-ONLY — request read scopes; do not widen.

# jiratoolkit.py:2152-2154 — the seraph constants to reuse:
_SERAPH_HEADER = "X-Seraph-Loginreason"
_SERAPH_FAIL_VALUES = {"AUTHENTICATED_FAILED", "AUTHENTICATION_DENIED"}
# jiratoolkit.py:2174-2176 — API VERSION IS AUTH-DEPENDENT:
api_path = ("/rest/api/3/myself" if self.auth_type == "oauth2_3lo"
            else "/rest/api/2/myself")
# jiratoolkit.py:2259-2266 — an empty search result MUST be probed via
#   /myself; never trusted.
# jiratoolkit.py:2310 — async def jira_verify_auth(): performs a raw
#   GET .../myself so the X-Seraph-Loginreason header can be inspected.
# jiratoolkit.py:205, :249 — `expand` is already documented as accepting
#   'renderedFields'.
# jiratoolkit.py:1314 — async def _get_full_changelog(self, issue, page_size=100)
# jiratoolkit.py:1198 — _ensure_bounded_jql(jql) — the toolkit's JQL guard.
#   Do NOT port it here: the sweep declares its own scope by design and an
#   unbounded backfill is the intended first run (spec §8, default JQL).

# packages/ai-parrot/src/parrot/auth/jira_oauth.py — ALREADY IN CORE
class JiraTokenSet(BaseModel): ...   # :59  — carries api_base_url, access_token
class JiraOAuthManager: ...          # :86
# Read this file for the exact per-user token-resolution call before using it.
```

### Does NOT Exist

- ~~`parrot/interfaces/jira/client.py`~~ — created by this task.
- ~~A `jira` import anywhere in core today~~ — confirm with
  `grep -rn "^from jira\|^import jira" packages/ai-parrot/src/`. Keeping that
  grep empty **except inside a function body** is an acceptance criterion.
- ~~`JiraInterface` inheriting `AbstractToolkit` / `AbstractTool`~~ — it is a
  plain class. Tool machinery lives in `parrot_tools`, and importing it here
  would invert the dependency direction G1 exists to prevent.
- ~~`JiraToolEnvelope` in core~~ — the envelope is a `parrot_tools` concern
  (`jiratoolkit.py:58`). `JiraInterface` returns raw dicts / `JiraIssue`
  models, never an envelope.
- ~~`_ensure_bounded_jql` in this interface~~ — deliberately not ported.
- ~~An ADF parser~~ — none in the repo. Always request
  `expand=renderedFields` so the description arrives as HTML on both API v2
  and v3.
- ~~`jira.JIRA.search_issues` returning an async iterator~~ — the pycontribs
  client is **synchronous**. Every call must be wrapped in
  `asyncio.to_thread`.
- ~~`nav_config` guaranteed importable~~ — guard it; `JiraToolkit` does.

---

## Implementation Notes

### Pattern to Follow — the lazy optional-dependency import

Copy `graphindex/builder.py:667-704` (`_loader_for`): try the import, raise an
actionable message naming the missing distribution, never let
`ModuleNotFoundError` escape raw.

```python
def _import_jira():
    """Import the pycontribs ``jira`` client, or raise actionably."""
    try:
        from jira import JIRA
    except ModuleNotFoundError as exc:      # pragma: no cover - env dependent
        raise JiraDependencyError(
            "The Jira read interface needs the optional `jira` "
            "distribution. Install it with:  pip install 'ai-parrot[jira]'"
        ) from exc
    return JIRA
```

Read the real `_loader_for` before writing this — match its message shape.

### Pattern to Follow — pagination as an async iterator

```python
async def search_issues(
    self, jql: str, *, fields: str | None = None,
    expand: str | None = None, page_size: int = 100,
) -> AsyncIterator[dict[str, Any]]:
    """Yield raw issue dicts for ``jql``, paging until exhausted."""
    start_at = 0
    while True:
        page = await asyncio.to_thread(
            self._client.search_issues, jql, startAt=start_at,
            maxResults=page_size, fields=fields, expand=expand,
            json_result=True,
        )
        issues = (page or {}).get("issues") or []
        if not issues:
            if start_at == 0:
                await self._probe_auth_or_raise()   # the seraph trap
            return
        for raw in issues:
            yield raw
        start_at += len(issues)
        if start_at >= (page or {}).get("total", start_at):
            return
```

This is a sketch, not gospel — verify `search_issues`' real kwargs against
`jiratoolkit.py:2638` (`jira_search_issues`) and the installed `jira` version
before committing to it. The **invariants** that must survive any rewrite:
an empty first page probes auth; paging terminates on `total`; nothing is
buffered wholesale in memory.

### Pattern to Follow — AC field resolution (spec §8, resolved)

```python
_AC_FIELD_NAMES: tuple[str, ...] = (
    "acceptance criteria", "acceptance criterion", "criterios de aceptacion",
)

async def resolve_ac_field_id(self) -> str | None:
    """Resolve the acceptance-criteria custom-field id.

    ``JIRA_WIKI_AC_FIELD`` wins when set. Otherwise the field is matched
    by name (case-insensitive, accent-stripped) against ``GET
    /rest/api/2/field``, and the result is cached for the process
    lifetime. Returns ``None`` when neither path resolves — the renderer
    then omits the acceptance-criteria section entirely rather than
    emitting an empty one, so determinism holds either way.
    """
```

Never guess a `customfield_NNNNN`. Never raise from this method — a Jira
instance without the field is normal.

### Key Constraints

- **Unauthenticated is a real state.** When `auth_type` is `None`, the
  constructor must succeed (so `--help`, config probing and tests work) and
  every read must raise `JiraAuthError` with a message naming
  `JIRA_AUTH_TYPE`. Never fall back to env credentials.
- **`verify_credentials=True` default** matches `JiraToolkit`'s constructor.
  Honour it: when true, probe on first use; when false, skip the probe.
- **`request_timeout: float = 30.0`** — pass it to `JIRA(timeout=...)` as the
  toolkit does.
- **3LO is per-user and per-call.** In `oauth2_3lo` mode there is no
  process-wide client; resolve the token set via `credential_resolver` /
  `JiraOAuthManager` and build the client for that user. Cache clients bounded
  — `jiratoolkit.py:1029` uses `_CLIENT_CACHE_MAX_SIZE = 100`; mirror that
  bound rather than an unbounded dict.
- **Read-only scopes.** Do not request `write:jira-work` for this interface.
- **No blocking I/O in async paths**: every `jira` call goes through
  `asyncio.to_thread`.
- `self.logger = logging.getLogger(__name__)`; no `print`.
- Google-style docstrings, strict type hints, pydantic v2 for any new model.

### Known Gotchas

- `options["verify"] = False` in the static-mode path (`jiratoolkit.py:960`)
  is the *existing* behaviour. Keep parity, but make it overridable via a
  `verify_tls: bool = False` constructor kwarg so the sweep can be run
  strictly. Do not silently change the default — that would be a behaviour
  change TASK-2402's regression gate would catch.
- The `oauth` (1.0a) mode's `key_cert` may be PEM *content* or a *file path*.
  Port `_read_key_cert` semantics (`jiratoolkit.py`, near `:983`); read the
  real implementation rather than reimplementing from this description.
- Remote links come from a **separate** endpoint (`/rest/api/2/issue/{key}/
  remotelink`), not from `fields`. `get_remote_links` is its own read.
- The changelog can exceed one page; `get_changelog` must page like
  `_get_full_changelog` (`jiratoolkit.py:1314`) does.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py:667-704` —
  lazy optional-dependency idiom
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:731-1050` —
  constructor, `_cfg`, auth resolution, both client builders
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:2152-2330` —
  seraph constants, api-version selection, `jira_verify_auth`
- `packages/ai-parrot/src/parrot/auth/jira_oauth.py` — `JiraOAuthManager`
- `packages/ai-parrot/src/parrot/interfaces/obsidian/abstract.py` — interface
  + error-class style

---

## Acceptance Criteria

- [ ] `from parrot.interfaces.jira import JiraInterface` works, and
      `grep -rn "^from jira\|^import jira" packages/ai-parrot/src/` returns
      **nothing** (the import lives inside a function body).
- [ ] With `jira` absent, the first call raises `JiraDependencyError` whose
      message names `ai-parrot[jira]` — no `ModuleNotFoundError` traceback.
- [ ] **G1**: all four auth modes (`basic_auth`, `token_auth`, `oauth`,
      `oauth2_3lo`) resolve the expected server URL and client options.
- [ ] Unresolved `auth_type` → constructor succeeds, every read raises
      `JiraAuthError` naming `JIRA_AUTH_TYPE`, and **no** env credential is
      consulted.
- [ ] An empty first search page triggers the `/myself` probe; a probe whose
      response carries `X-Seraph-Loginreason: AUTHENTICATED_FAILED` raises
      instead of returning an empty iterator.
- [ ] `search_issues` pages through multiple pages and terminates on `total`.
- [ ] `resolve_ac_field_id` prefers `JIRA_WIKI_AC_FIELD`, falls back to a
      by-name lookup, caches the result, and returns `None` (never raises)
      when neither resolves.
- [ ] `JiraInterface.parse_issue` is a `@staticmethod` delegating to
      `parse.parse_issue` — no duplicated projection logic
      (`grep -c 'accountId' client.py` is 0).
- [ ] No blocking `jira` call outside `asyncio.to_thread`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/interfaces/jira/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/interfaces/jira/`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/jira/test_jira_interface.py
import asyncio
import builtins

import pytest

from parrot.interfaces.jira import (
    JiraAuthError, JiraDependencyError, JiraInterface,
)

BASE = "https://example.atlassian.net"


class FakeJIRA:
    """Minimal stand-in for pycontribs `jira.JIRA` (synchronous)."""

    def __init__(self, pages, *, myself=None, fields=None, **kwargs):
        self.pages, self.calls, self.kwargs = list(pages), [], kwargs
        self._myself, self._fields = myself, fields or []

    def search_issues(self, jql, startAt=0, maxResults=100, **kw):
        self.calls.append((jql, startAt, maxResults))
        idx = startAt // max(maxResults, 1)
        issues = self.pages[idx] if idx < len(self.pages) else []
        total = sum(len(p) for p in self.pages)
        return {"issues": issues, "total": total, "startAt": startAt}

    def fields(self):
        return self._fields


class TestLazyDependency:
    def test_missing_jira_raises_actionable_error(self, monkeypatch):
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "jira":
                raise ModuleNotFoundError("No module named 'jira'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        with pytest.raises(JiraDependencyError, match=r"ai-parrot\[jira\]"):
            asyncio.run(iface.get_projects())

    def test_module_does_not_import_jira_at_load(self):
        import inspect
        import parrot.interfaces.jira.client as mod
        src = inspect.getsource(mod)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("from jira", "import jira")):
                assert line.startswith((" ", "\t")), \
                    "the `jira` import must be inside a function body"


class TestAuthResolution:
    @pytest.mark.parametrize("mode,kwargs", [
        ("basic_auth", {"username": "u", "password": "p"}),
        ("token_auth", {"token": "t"}),
    ])
    def test_static_modes_resolve(self, mode, kwargs):
        iface = JiraInterface(server_url=BASE, auth_type=mode,
                              verify_credentials=False, **kwargs)
        assert iface.auth_type == mode
        assert iface.server_url == BASE

    def test_basic_auth_without_credentials_raises(self):
        with pytest.raises(ValueError, match="basic_auth requires"):
            JiraInterface(server_url=BASE, auth_type="basic_auth",
                          verify_credentials=True)._build_client()

    def test_oauth2_3lo_does_not_require_server_url(self):
        """3LO resolves the URL per-user at runtime (jiratoolkit.py:780)."""
        iface = JiraInterface(auth_type="oauth2_3lo", verify_credentials=False)
        assert iface.auth_type == "oauth2_3lo"

    def test_unresolved_auth_type_never_uses_env(self, monkeypatch):
        """jiratoolkit.py:767-775 — no heuristic, no silent service account."""
        monkeypatch.setenv("JIRA_USERNAME", "leaked")
        monkeypatch.setenv("JIRA_API_TOKEN", "leaked")
        monkeypatch.delenv("JIRA_AUTH_TYPE", raising=False)
        iface = JiraInterface(server_url=BASE)
        assert iface.auth_type is None
        with pytest.raises(JiraAuthError, match="JIRA_AUTH_TYPE"):
            asyncio.run(iface.get_issue("NAV-1"))

    def test_env_auth_type_is_honoured_and_lowercased(self, monkeypatch):
        monkeypatch.setenv("JIRA_AUTH_TYPE", "TOKEN_AUTH")
        iface = JiraInterface(server_url=BASE, token="t",
                              verify_credentials=False)
        assert iface.auth_type == "token_auth"


class TestSearchPagination:
    def test_pages_until_exhausted(self, raw_issue):
        pages = [[raw_issue] * 100, [raw_issue] * 40]
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA(pages)

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        assert len(asyncio.run(collect())) == 140
        assert [c[1] for c in iface._client.calls] == [0, 100, 140] or \
               [c[1] for c in iface._client.calls] == [0, 100]

    def test_empty_first_page_probes_auth(self):
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([[]])
        probed = {"n": 0}

        async def probe():
            probed["n"] += 1
            return {"accountId": "x"}

        iface._probe_myself = probe

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        assert asyncio.run(collect()) == []
        assert probed["n"] == 1, "an empty page MUST probe /myself"

    def test_seraph_failure_on_empty_page_raises(self):
        """The AUTHENTICATED_FAILED trap — jiratoolkit.py:2259-2266."""
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([[]])

        async def probe():
            raise JiraAuthError("X-Seraph-Loginreason: AUTHENTICATED_FAILED")

        iface._probe_myself = probe

        async def collect():
            return [r async for r in iface.search_issues("project = NAV")]

        with pytest.raises(JiraAuthError, match="AUTHENTICATED_FAILED"):
            asyncio.run(collect())


class TestAcceptanceCriteriaField:
    def test_config_key_wins(self, monkeypatch):
        monkeypatch.setenv("JIRA_WIKI_AC_FIELD", "customfield_99999")
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        assert asyncio.run(iface.resolve_ac_field_id()) == "customfield_99999"

    def test_dynamic_by_name_fallback(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([], fields=[
            {"id": "customfield_10101", "name": "Acceptance Criteria"},
            {"id": "customfield_10102", "name": "Story Points"},
        ])
        assert asyncio.run(iface.resolve_ac_field_id()) == "customfield_10101"

    def test_returns_none_and_never_raises_when_absent(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        iface._client = FakeJIRA([], fields=[{"id": "customfield_1",
                                              "name": "Story Points"}])
        assert asyncio.run(iface.resolve_ac_field_id()) is None

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.delenv("JIRA_WIKI_AC_FIELD", raising=False)
        iface = JiraInterface(server_url=BASE, auth_type="token_auth",
                              token="t", verify_credentials=False)
        calls = {"n": 0}

        class CountingFake(FakeJIRA):
            def fields(self):
                calls["n"] += 1
                return [{"id": "customfield_10101",
                         "name": "Acceptance Criteria"}]

        iface._client = CountingFake([])
        asyncio.run(iface.resolve_ac_field_id())
        asyncio.run(iface.resolve_ac_field_id())
        assert calls["n"] == 1


class TestReadOnlySurface:
    def test_no_write_methods_exposed(self):
        """This interface is read-only; writes stay in JiraToolkit."""
        for forbidden in ("transition_issue", "add_comment", "create_issue",
                          "assign_issue", "update_issue", "add_attachment"):
            assert not hasattr(JiraInterface, forbidden)

    def test_parse_issue_is_a_delegating_staticmethod(self, raw_issue):
        from parrot.interfaces.jira import parse as parse_mod
        assert isinstance(
            JiraInterface.__dict__["parse_issue"], staticmethod)
        a = JiraInterface.parse_issue(raw_issue, base_url=BASE)
        b = parse_mod.parse_issue(raw_issue, base_url=BASE)
        assert a.model_dump_json() == b.model_dump_json()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§2 "New Public Interfaces", §3 M1, §7, G1) for full context
2. **Check dependencies** — TASK-2399 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `jiratoolkit.py:731-1050` in full. Do not implement auth from this
     task file's excerpts alone — they are an index, not the source
   - Read `jiratoolkit.py:2152-2330` for the seraph probe and api-version rule
   - Read `parrot/auth/jira_oauth.py` for the real `JiraOAuthManager` call
   - Read `graphindex/builder.py:667-704` for the lazy-import message shape
   - Check the installed `jira` version's `search_issues` signature:
     `source .venv/bin/activate && python -c "import jira, inspect;
     print(inspect.signature(jira.JIRA.search_issues))"`
4. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2400-jira-interface-client-auth-reads.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
