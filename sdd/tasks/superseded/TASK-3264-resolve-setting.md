# TASK-3264: `resolve_setting()` — one configuration reader for the graph tree

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4**. The graph tree has three different configuration readers
today, each with its own resolution order:

- `wiki/project.py` `_navconfig()` (:546) + `_env_credential()` (:576) — `os.environ` → navconfig → default.
- `wiki/cli.py` `_env_setting()` (:499) — navconfig **first**, `os.environ` only if navconfig raises.
- `graphindex/loader.py` `GraphIndexLoader._resolve_arango()` — inline `from navconfig import config` (:337) with a local `_cfg` helper.

This task replaces all three with one public reader, `resolve_setting()`, plus a
`require_setting()` companion that turns a missing credential into one
actionable error (spec AC: "never a loopback default"). navconfig stays an
optional, lazily imported provider — never a module-level import (spec §2,
brainstorm decision).

Binding design: brief D8.

---

## Scope

- Add to `wiki/project.py`: `resolve_setting()`, `MissingSettingError`, `require_setting()`.
- Delete `_navconfig()` and `_env_credential()`; rewrite `resolve_arango_params()` (same signature) to call through the new functions. `{prefix}_HOST` becomes **required** (`require_setting`) — no `127.0.0.1` default.
- Delete `_env_setting()` from `wiki/cli.py`; repoint its 18 call sites to `resolve_setting(...)`.
- Replace the inline navconfig block in `GraphIndexLoader._resolve_arango()` (graphindex/loader.py:337-342) with a lazy `resolve_setting` / `require_setting` import from `parrot.knowledge.wiki.project`.
- Guard `wiki/sync.py:131` (`resolve_arango_params(config).get("host")` inside an `except` handler) so a `MissingSettingError` cannot mask the original connection error.
- Tests: `test_resolve_setting_order`, `test_resolve_setting_navconfig_broken`, `test_missing_credential_message`, plus `resolve_arango_params` host-required test.
- **Own the existing tests that relied on the loopback default** (verified by grep of `packages/*/tests` for `resolve_arango_params` / `backend="arangodb"` / `open_namespace_store` / `ArangoDBWikiStore`):
  - `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py:127` `TestCreateWikiMcpServerArangoBackend::test_arangodb_backend_passes_connection_params` — asserts `captured["kwargs"]["arango_params"]["host"]` truthy (:147); add `monkeypatch.setenv("ARANGODB_HOST", "arango.test")` and assert `== "arango.test"`.
  - `packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py:51` `TestOpenNamespaceStoreExtraBackendDispatch::test_dispatches_extra_backend_for_database_kind` — `federation.open_namespace_store` calls `resolve_arango_params(_arango_config_for(cfg))` (federation.py:423) before the fake factory; add `monkeypatch.setenv("ARANGODB_HOST", "arango.test")`.
  - Checked and NOT affected: `test_extra_backends.py:73` (raises `ValueError` for the unknown backend before resolving params); `packages/ai-parrot-tools/tests/legal/test_wiki_store.py:160,272` (pass `arango_params={}` directly); `packages/ai-parrot-tools/tests/legal/test_boe_integration.py:271-273` (live test, skips without `ARANGODB_HOST`).

**NOT in scope**:
- `resolve_wiki_env()` (project.py:861) — see Implementation Notes: it deliberately does NOT consult navconfig ("plane selection is not credential selection", its docstring), and routing `WIKI_ENV`/`ENV` through navconfig would import navconfig on the PreToolUse hook path on every call. Leave its body unchanged; record the deviation.
- `graphindex/pg_schema.py:20,23` module-level `navconfig` / `parrot.conf` imports — [postgres] plane, out of scope (brief drift list).
- Relocating `GraphIndexLoader` (TASK-3266) — this task edits it in place.
- `wiki/mcp_server.py` transport selection (`WIKI_MCP_TRANSPORT`, TASK-3265 consumes `resolve_setting`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | add `resolve_setting`/`require_setting`/`MissingSettingError`; remove `_navconfig`/`_env_credential`; rewrite `resolve_arango_params` body |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | delete `_env_setting`; 18 call sites → `resolve_setting`; import it |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | `_resolve_arango` uses lazy `resolve_setting`/`require_setting` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` | MODIFY | guard host lookup inside except (line 131) |
| `packages/ai-parrot/tests/knowledge/wiki/test_resolve_setting.py` | CREATE | unit tests |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` | MODIFY | `test_arangodb_backend_passes_connection_params` sets `ARANGODB_HOST` |
| `packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py` | MODIFY | `test_dispatches_extra_backend_for_database_kind` sets `ARANGODB_HOST` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `2c54cbac2` on 2026-09-15.

### Verified Imports
```python
from parrot.knowledge.wiki.project import WikiProjectConfig, resolve_arango_params   # project.py:379, :605
from parrot.knowledge.wiki import project as project_mod     # module has `logger = logging.getLogger(__name__)` at :67, `import os` at :17
from collections.abc import Iterator                          # project.py top block (add Mapping to this line)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
import os                                                     # line 17
from collections.abc import Iterator                          # occurrences: 1
logger = logging.getLogger(__name__)                          # line 67
class WikiProjectConfig(BaseModel):                           # line 379 (fields arango_credentials_env default "ARANGODB", arango_database, wiki_name)
def _navconfig() -> Any | None:                               # line 546  (body to 573) ← DELETE
def _env_credential(key: str, default: Any) -> Any:           # line 576  (body to 602) ← DELETE
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]:  # line 605
    prefix = config.arango_credentials_env
    return {
        "host": str(_env_credential(f"{prefix}_HOST", "127.0.0.1")),      # line 629
        "port": int(_env_credential(f"{prefix}_PORT", 8529)),             # line 630
        "protocol": str(_env_credential(f"{prefix}_PROTOCOL", "http")),   # line 631
        "username": str(_env_credential(f"{prefix}_USERNAME", "root")),   # line 632
        "password": str(_env_credential(f"{prefix}_PASSWORD", "")),       # line 633
        "database": config.arango_database or f"wiki_{config.wiki_name}",
    }
def resolve_wiki_env(env: str | None = None) -> str:          # line 861 — reads os.environ directly; leave unchanged

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
from parrot.knowledge.wiki.project import (   # line 61 … `    validate_namespace_name,` (line 81, occurrences: 1) … `)` line 83
def _env_setting(name: str) -> str | None:     # line 499 — body to 512:
    try:
        from navconfig import config as _nav
        value = _nav.get(name, fallback=None)
    except Exception:
        import os
        value = os.environ.get(name)
    return value or None
# call sites (18; `grep -c '_env_setting(' cli.py` == 19 incl. the def):
#   562 WIKI_STORE · 564 WIKI_STORE_BACKEND · 581 WIKI_STORE_BACKEND · 1451 WIKI_STORE_BACKEND
#   3117 WIKI_STORE · 3119 WIKI_STORE_BACKEND · 3127 WIKI_STORE_BACKEND
#   3241 WIKI_EXTRACT_LLM · 3242 PARROT_NO_AUTO_LLM · 3966 `cli_value or _env_setting(env_name)`
#   4406 WIKI_LIGHTWEIGHT_MODEL · 4407 WIKI_MODEL · 4408 PARROT_NO_AUTO_LLM
#   4802 JIRA_WIKI_JQL · 4806 JIRA_DEFAULT_PROJECT · 4822 JIRA_WIKI_ISSUES_DIR
#   4826 JIRA_WIKI_CONCURRENCY · 4879 `_env_setting("JIRA_WIKI_NAMESPACE") or "issues"`

# packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py
class GraphIndexLoader(AbstractLoader):                       # line 96
    def _resolve_arango(self, arango, host, port, protocol, user, password, database) -> Optional[dict]:  # line 314
        explicit = arango is not None or any(v is not None for v in (host, user, password, database))
        if not explicit:
            return None
        from navconfig import config  # local import: optional dependency   # line 337 (occurrences: 1)
        def _cfg(key: str, default: Any) -> Any: ...          # lines 339-342; `_cfg(` occurrences: 7 (1 def + 6 uses)
        base = dict(arango) if isinstance(arango, dict) else {}
        return {"host": base.get("host") or host or _cfg("ARANGODB_HOST", "127.0.0.1"), ...
                "database": base.get("database") or database or _cfg("ARANGODB_DATABASE", f"db_{self.tenant_id}")}
        # method ends at line 370

# packages/ai-parrot/src/parrot/knowledge/wiki/sync.py
    except Exception as exc:  # re-raised below as a typed, clean error
        host = resolve_arango_params(config).get("host") if config.backend == "arangodb" else None   # line 131
        where = f"{target_env!r} ({host})" if host else repr(target_env)
        raise SyncError(...) from exc

# Other resolve_arango_params callers (arango backend only — behaviour change = missing host raises):
#   wiki/mcp_server.py:119-125, wiki/federation.py:243,423,429, wiki/cli.py:414-420,
#   wiki/structural/toolkit.py:83-89, wiki/toolkit.py:119-121
```

### Does NOT Exist
- ~~`resolve_setting`, `require_setting`, `MissingSettingError`~~ — created by THIS task.
- ~~`parrot.knowledge.wiki.settings`~~ — no such module; the spec fixes the location as `wiki/project.py`.
- ~~A `wiki.json` loader inside `resolve_setting`~~ — the function has no `root`; the wiki.json level is the caller-supplied `config` mapping.
- ~~Tests asserting the literal `127.0.0.1` value~~ — none; but two tests *implicitly* rely on a non-empty default host (see Scope: test_mcp_server.py:127, test_extra_backends.py:51). `tests/knowledge/graphindex/test_loader.py:90,166` pass `arango_host="127.0.0.1"` explicitly and are unaffected.
- ~~`.mcp.json` at repo root~~ — absent.

---

## Implementation Notes

### Resolution order (binding, brief D8)
`explicit` (if not `None`) → `os.environ[key]` → navconfig `config.get(key)` (lazy import, only when
not found yet; any exception swallowed + `logger.debug`) → `config` mapping (wiki.json-derived values)
→ `default`. navconfig's `get` may return `None` for a missing key even with a fallback — coalesce
explicitly (existing guard, loader.py:340).

### Deviations to record in the Completion Note
- `resolve_setting` gains a keyword-only `config: Mapping[str, Any] | None = None` — spec §2 lists a
  wiki.json level but its skeleton has no input for it (additive; skeleton call shape unchanged).
- `_env_setting` callers: env now wins over navconfig (old reader preferred navconfig). navconfig
  copies `.env` into `os.environ` on import, so values normally coincide; an explicit `export`
  now overrides an `.env` file, consistent with `_env_credential`.
- `resolve_wiki_env` not routed through `resolve_setting` (see NOT in scope).

### Key Constraints
- Module stays dependency-light: no module-level `navconfig` import anywhere (hook path).
- `require_setting` message must name the key AND the order tried, e.g.
  `"Missing required setting 'ARANGODB_HOST' — tried: explicit argument, os.environ, navconfig, wiki.json, (no default)."`
- Empty strings: old `_env_setting` returned `value or None`. Call sites that only truth-test are
  unaffected; where the value is stored/compared, preserve semantics with `resolve_setting(...) or None`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Mapping` to `from collections.abc import Iterator` in project.py — *why*: annotation of the new `config` parameter.
2. Replace project.py lines 546-602 (`_navconfig` + `_env_credential`) with the new block below — *why*: one reader, same lazy/tolerant navconfig behaviour, now public and ordered per spec.
3. Rewrite the `return {...}` of `resolve_arango_params` (lines 628-635) — *why*: host has no loopback default (spec AC); other keys keep non-loopback defaults. Update its docstring ("Each variable resolves through :func:`resolve_setting`…; `{prefix}_HOST` is required").
4. In cli.py: add `resolve_setting,` to the project import block, delete `_env_setting` (lines 499-512), replace the 18 call sites — *why*: AC "`_env_setting` … gone".
5. In graphindex/loader.py `_resolve_arango`: replace lines 337-342 and the `_cfg(...)` uses — *why*: AC "the inline navconfig block is gone".
6. Guard sync.py:131 — *why*: an exception raised inside the `except` block would replace the real connection error.
7. Write `tests/knowledge/wiki/test_resolve_setting.py`; add `monkeypatch.setenv("ARANGODB_HOST", "arango.test")` at the top of `test_mcp_server.py::test_arangodb_backend_passes_connection_params` (line 127, after the import) and `test_extra_backends.py::test_dispatches_extra_backend_for_database_kind` (line 51) — *why*: both reach `resolve_arango_params` with no host configured and passed only because of the removed loopback default; run the test commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY — replaces lines 546-602)
```python
# occurrences: 1 (verified: grep -c '^def _navconfig() -> Any | None:' project.py)
# occurrences: 1 (verified: grep -c '^def _env_credential(key: str, default: Any) -> Any:' project.py)
# REPLACE from `def _navconfig() -> Any | None:` (line 546) through the end of `_env_credential` (line 602, `return default`)

#: Human-readable resolution order, used in MissingSettingError messages.
_SETTING_ORDER = ("explicit argument", "os.environ", "navconfig", "wiki.json")


class MissingSettingError(KeyError):
    """Raised by :func:`require_setting` when no source provides a key."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            f"Missing required setting {key!r} — tried: {', '.join(_SETTING_ORDER)}. "
            f"Set {key} in the environment (or env/.env loaded by navconfig)."
        )

    def __str__(self) -> str:  # KeyError would otherwise repr() the message
        return str(self.args[0])


def resolve_setting(
    key: str,
    *,
    default: Any = None,
    explicit: Any = None,
    config: Mapping[str, Any] | None = None,
) -> Any:
    """Resolve one configuration value.

    Order: ``explicit`` argument → ``os.environ`` → navconfig (imported
    lazily, only if the key was not already found) → ``config`` (values
    from ``wiki.json``) → ``default``. A navconfig import failure is
    swallowed, logged at debug, and resolution continues — deliberate,
    because this path runs inside the Claude Code PreToolUse hook.

    Args:
        key: Setting name, e.g. ``"ARANGODB_HOST"``.
        default: Returned when no source provides ``key``.
        explicit: A caller-supplied value that wins when not ``None``.
        config: Optional mapping of wiki.json-derived values.

    Returns:
        The resolved value, or ``default``.
    """
    if explicit is not None:
        return explicit
    value = os.environ.get(key)
    if value is not None:
        return value
    try:
        from navconfig import config as nav_config
    except Exception:  # noqa: BLE001 — a broken env file must not break the hook
        logger.debug("navconfig unavailable while resolving %s; continuing without it", key)
    else:
        # FILL IN: call nav_config.get(key) inside its own try/except Exception (debug log) and
        #          return it when not None — bounded by "navconfig failure degrades, never raises"
        #          (test_resolve_setting_navconfig_broken).
        pass
    if config is not None and config.get(key) is not None:
        return config[key]
    return default


def require_setting(
    key: str,
    *,
    explicit: Any = None,
    config: Mapping[str, Any] | None = None,
) -> Any:
    """Resolve ``key`` like :func:`resolve_setting` but fail when nothing provides it.

    Raises:
        MissingSettingError: Naming ``key`` and every source tried.
    """
    value = resolve_setting(key, explicit=explicit, config=config)
    # FILL IN: treat None and "" as missing — bounded by spec AC "never a loopback default"
    if value is None:
        raise MissingSettingError(key)
    return value
```
**Why**: keeps `_navconfig`'s documented tolerance (broad `except`, debug log) while centralising order. `__str__` override because `KeyError.__str__` quotes its argument.

### `resolve_arango_params` body (MODIFY — project.py:628-635)
```python
# occurrences: 1 (verified: grep -c '"host": str(_env_credential(f"{prefix}_HOST", "127.0.0.1")),' project.py)
    prefix = config.arango_credentials_env
    return {
        "host": str(require_setting(f"{prefix}_HOST")),
        "port": int(resolve_setting(f"{prefix}_PORT", default=8529)),
        "protocol": str(resolve_setting(f"{prefix}_PROTOCOL", default="http")),
        "username": str(resolve_setting(f"{prefix}_USERNAME", default="root")),
        "password": str(resolve_setting(f"{prefix}_PASSWORD", default="")),
        "database": config.arango_database or f"wiki_{config.wiki_name}",
    }
```
**Why**: spec AC "A missing credential produces one actionable message … never a loopback default". Port/protocol/username/password defaults are not loopback addresses and are kept (FILL IN only if a test proves otherwise — ESCALATE rather than inventing new required keys).

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    validate_namespace_name,' cli.py)
# AFTER — insert below `    save_project_config,` … keep alphabetical: add between `resolve_entry_base,` (line 76) and `save_env_overlay,` (line 77):
    resolve_setting,

# occurrences: 1 (verified: grep -c '^def _env_setting(name: str) -> str | None:' cli.py)
# DELETE lines 499-512 (the whole `_env_setting` function incl. its docstring and trailing blank lines).

# occurrences: 18 call sites (verified: grep -c '_env_setting(' cli.py == 19 incl. def)
# REPLACE each `_env_setting(<NAME>)` with `resolve_setting(<NAME>)`.
# FILL IN: for sites whose value is stored rather than truth-tested — 3966 (`value = cli_value or ...`),
#          4822 (`resolve_issues_dir(issues_dir_opt or ...)`), 4826 (`env_concurrency = ...`) — confirm an
#          empty string behaves like None downstream; if not, append `or None` — bounded by "old reader
#          returned `value or None`".
```
**Why**: a mechanical rename keeps the diff reviewable; `resolve_setting(name)` defaults to `None`, matching the old signature.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` (MODIFY — `_resolve_arango`)
```python
# occurrences: 1 (verified: grep -c '        from navconfig import config  # local import: optional dependency' loader.py)
# REPLACE lines 337-342 (the navconfig import and the nested `_cfg` helper) with:
        # Lazy: keeps the graph tree free of a module-level wiki.project → navconfig edge.
        from parrot.knowledge.wiki.project import require_setting, resolve_setting

# Then REPLACE the six `_cfg(` uses (`grep -c '_cfg(' loader.py` == 7 incl. def) in the return dict:
            "host": base.get("host") or host or require_setting("ARANGODB_HOST"),
            "port": int(base.get("port") or port or resolve_setting("ARANGODB_PORT", default=8529)),
            "protocol": base.get("protocol") or protocol or resolve_setting("ARANGODB_PROTOCOL", default="http"),
            "username": base.get("username") or user or resolve_setting("ARANGODB_USERNAME", default="root"),
            # FILL IN: "password" keeps its `is not None` cascade (base → password → resolve_setting("ARANGODB_PASSWORD", default=""))
            "database": base.get("database") or database or resolve_setting("ARANGODB_DATABASE", default=f"db_{self.tenant_id}"),
```
**Why**: persistence is enabled only when the caller passed explicit credentials; if they omitted the host, a loopback guess silently targets the wrong server. Update the docstring (line ~329): "Missing fields fall back to ``ARANGODB_*`` via :func:`resolve_setting`; ``ARANGODB_HOST`` is required." Also update the module docstring line 13 ("via ``navconfig``" → "via :func:`resolve_setting`").

### `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'host = resolve_arango_params(config).get("host") if config.backend == "arangodb" else None' sync.py)
        host = None
        if config.backend == "arangodb":
            try:
                host = resolve_arango_params(config).get("host")
            except MissingSettingError:
                host = None
```
Add `MissingSettingError` to sync.py's existing `from parrot.knowledge.wiki.project import (` block (it already imports `resolve_arango_params`, sync.py:30).

### FILL IN checklist
- [ ] `project.py::resolve_setting` navconfig `get` — tolerant call; bounded by `test_resolve_setting_navconfig_broken`.
- [ ] `project.py::require_setting` — `""` treated as missing; bounded by AC "never a loopback default".
- [ ] cli.py sites 3966/4822/4826 — empty-string semantics; bounded by old `value or None`.
- [ ] loader.py password cascade — preserve `is not None` semantics (explicit `""` password allowed).
- [ ] Final sweep: `grep -rn "resolve_arango_params\|backend=\"arangodb\"\|open_namespace_store" packages/*/tests` — any other test reaching `resolve_arango_params` without `ARANGODB_HOST` gets the same monkeypatch; bounded by "fix the test's setup, never re-add a loopback default".

---

## Addendum — tests that rely on the loopback host default (review, 2026-09-15)

Dropping the `127.0.0.1` host default breaks
`packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py::test_arangodb_backend_passes_connection_params`
(:127 — it builds an arangodb-backend MCP server with no host set and asserts
`captured["kwargs"]["arango_params"]["host"]` is truthy). In that test add
`monkeypatch.setenv("ARANGODB_HOST", "arango.test")` before
`create_wiki_mcp_server(tmp_path)` — add the file to this task's scope.

Also re-check, at execution time, any other test reaching `resolve_arango_params`
or `GraphIndexLoader._resolve_arango` without a host (grep both `packages/*/tests`
and the repo-root `tests/` tree — e.g. `tests/knowledge/wiki/test_toolkit_arango.py`,
`tests/knowledge/wiki/test_arango_integration.py:185` already sets `ARANGODB_HOST`;
`tests/knowledge/wiki/conftest.py:216` builds params with its own
`TEST_ARANGODB_HOST` default and is unaffected). Set `ARANGODB_HOST` via monkeypatch
where needed — never reintroduce a loopback default in production code.

---

## Acceptance Criteria

- [ ] `grep -rn "_env_setting\|_env_credential\|_navconfig" packages/ai-parrot/src/parrot/knowledge` returns nothing.
- [ ] `grep -rn "from navconfig" packages/ai-parrot/src/parrot/knowledge/wiki packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` returns only the lazy import inside `resolve_setting`.
- [ ] `resolve_setting` honours explicit → env → navconfig → config → default (each asserted).
- [ ] A raising navconfig import degrades to `os.environ` and logs at debug.
- [ ] `resolve_arango_params` with no `ARANGODB_HOST` raises `MissingSettingError` whose message names the key and the order; no `127.0.0.1` anywhere in project.py's resolution code.
- [ ] `test_mcp_server.py::TestCreateWikiMcpServerArangoBackend::test_arangodb_backend_passes_connection_params` and `test_extra_backends.py::TestOpenNamespaceStoreExtraBackendDispatch::test_dispatches_extra_backend_for_database_kind` set `ARANGODB_HOST` via monkeypatch and pass with `ARANGODB_HOST` unset in the outer environment (`env -u ARANGODB_HOST pytest ...`).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/ packages/ai-parrot/tests/knowledge/graphindex/test_loader.py packages/ai-parrot-tools/tests/legal/test_wiki_store.py -v`
- [ ] `ruff check` clean on changed files.
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py tests/knowledge/wiki/ -v` passes (arango host test sets `ARANGODB_HOST`)

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_resolve_setting.py
"""FEAT-540 Module 4 — resolve_setting() (TASK-3264)."""
from __future__ import annotations

import builtins
import logging
import sys
import types

import pytest

from parrot.knowledge.wiki.project import (
    MissingSettingError,
    WikiProjectConfig,
    require_setting,
    resolve_arango_params,
    resolve_setting,
)

KEY = "FEAT540_TEST_SETTING"


@pytest.fixture
def fake_navconfig(monkeypatch):
    """Install a stub navconfig whose config.get returns from a dict."""
    values: dict[str, str] = {}
    module = types.ModuleType("navconfig")
    module.config = types.SimpleNamespace(get=lambda k, fallback=None: values.get(k, fallback))
    monkeypatch.setitem(sys.modules, "navconfig", module)
    return values


def test_resolve_setting_order(monkeypatch, fake_navconfig):
    monkeypatch.delenv(KEY, raising=False)
    assert resolve_setting(KEY, default="d") == "d"
    assert resolve_setting(KEY, default="d", config={KEY: "json"}) == "json"
    fake_navconfig[KEY] = "nav"
    assert resolve_setting(KEY, default="d", config={KEY: "json"}) == "nav"
    monkeypatch.setenv(KEY, "env")
    assert resolve_setting(KEY, default="d", config={KEY: "json"}) == "env"
    assert resolve_setting(KEY, explicit="x", default="d") == "x"


def test_resolve_setting_navconfig_broken(monkeypatch, caplog):
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.delitem(sys.modules, "navconfig", raising=False)
    real_import = builtins.__import__

    def _raising(name, *args, **kwargs):
        if name == "navconfig":
            raise RuntimeError("broken env file")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising)
    with caplog.at_level(logging.DEBUG, logger="parrot.knowledge.wiki.project"):
        assert resolve_setting(KEY, default="d") == "d"
    assert any("navconfig" in r.getMessage() for r in caplog.records)


def test_missing_credential_message(monkeypatch, fake_navconfig):
    monkeypatch.delenv("ARANGODB_HOST", raising=False)
    with pytest.raises(MissingSettingError) as exc:
        resolve_arango_params(WikiProjectConfig(wiki_name="w", backend="arangodb"))
    msg = str(exc.value)
    assert "ARANGODB_HOST" in msg and "os.environ" in msg and "navconfig" in msg
    assert "127.0.0.1" not in msg


def test_require_setting_returns_value(monkeypatch):
    monkeypatch.setenv(KEY, "v")
    assert require_setting(KEY) == "v"


def test_resolve_arango_params_uses_env(monkeypatch, fake_navconfig):
    monkeypatch.setenv("ARANGODB_HOST", "arango.internal")
    params = resolve_arango_params(WikiProjectConfig(wiki_name="w", backend="arangodb"))
    assert params["host"] == "arango.internal"
    assert params["port"] == 8529
    # FILL IN: assert protocol/username/password defaults and database == "wiki_w"
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 4, §2 New Public Interfaces).
2. **Dependencies**: none — but TASK-3261 also edits `wiki/cli.py` (`_structural_tool`) and TASK-3266 relocates `graphindex/loader.py`; if either already landed, re-run every `grep -c` anchor first.
3. **Verify the Codebase Contract** before editing; update it if lines drifted.
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Run tests in the worktree** with `PYTHONPATH=packages/ai-parrot/src pytest ...` (shared venv points at the main checkout).
7. Move this file to `sdd/tasks/completed/`, set index → `"done"`, fill in the Completion Note (record the three deviations above).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: `config` keyword added to `resolve_setting`; `resolve_wiki_env` not routed through it; `_env_setting` callers now env-first.
