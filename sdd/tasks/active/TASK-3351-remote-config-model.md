# TASK-3351: `WikiRemoteConfig` + `remote` block + `resolve_remote()` (M1)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every client-side piece of FEAT-569 (the core client, the CLI
proxy, the stdio pass-through, the installers) switches on one thing: an
effective `WikiRemoteConfig`. This task declares the model, hangs it off
`WikiProjectConfig` and `WikiEnvOverlay` (so `.parrot/wiki.<env>.json` can
override it, FEAT-461), and provides the single resolver that applies the
`WIKITOOLKIT_REMOTE_URL` env override. Decided in brainstorm: fail-closed
semantics live in the *client* (TASK-3359), not here — this task only resolves
configuration and never opens a network connection.

---

## Scope

- Add `WikiRemoteConfig(BaseModel)` to `project.py` with exactly the fields fixed in spec §2 Data Models (`url`, `token_env="WIKITOOLKIT_TOKEN"`, `timeout` 1–600 default 30, `actor: str | None`, `verify_tls=True`) and a `url` validator (absolute `http(s)` URL, trailing slash stripped).
- Add `remote: WikiRemoteConfig | None = None` to `WikiProjectConfig` and to `WikiEnvOverlay` (the overlay merge in `load_effective_config` iterates `model_fields`, so no merge code changes).
- Add `REMOTE_URL_ENV = "WIKITOOLKIT_REMOTE_URL"` and `resolve_remote(config) -> WikiRemoteConfig | None` with precedence env override > `config.remote` > `None`; the env override keeps `token_env`/`timeout`/`actor`/`verify_tls` from `config.remote` when present, defaults otherwise.
- Unit tests.

**NOT in scope**: token presence checks, HTTP calls, CLI wiring (TASK-3359 / TASK-3362), installer reads of `config.remote` (TASK-3365 / TASK-3366).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `WikiRemoteConfig`, `remote` fields, `REMOTE_URL_ENV`, `resolve_remote()` |
| `packages/ai-parrot/tests/knowledge/wiki/test_remote_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, field_validator        # already imported in project.py (used at project.py:497)
from parrot.knowledge.wiki.project import (                    # all verified in project.py
    WikiProjectConfig,          # :379
    WikiEnvOverlay,             # :780
    WikiEffectiveConfig,        # ~:842
    WikiConfigError,            # :732
    load_effective_config,      # :897  (root: Path, env: str | None = None) -> WikiEffectiveConfig
    save_project_config,        # :761
    overlay_path,               # ~:892  (root: Path, env: str) -> Path  → ".parrot/wiki.{env}.json"
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):                       # :379-543
    wiki_name: str = Field(default="codebase")
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")
    sync_graph: bool = Field(default=False)               # anchor line (1 occurrence)
class WikiEnvOverlay(BaseModel):                          # :780-839 — every field Optional; last field:
    claude: ClaudeIntegrationConfig | None = None         # anchor line (1 occurrence)
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig   # :897-951
    # merge: `for name in overlay.__class__.model_fields if name != "namespaces" and getattr(overlay, name) is not None`
    # → base.model_copy(update=updates). A new Optional field on BOTH models merges with no code change.
```

### Does NOT Exist
- ~~`WikiProjectConfig.remote`~~, ~~`WikiRemoteConfig`~~, ~~`resolve_remote`~~, ~~`REMOTE_URL_ENV`~~ — created by this task.
- ~~`backend: "remote"`~~ — do NOT add a backend literal; remote mode is orthogonal to `backend`.
- ~~`WikiNamespaceConfig.url`~~ — no remote namespace kind in this feature.
- ~~`load_effective_config(..., remote=...)`~~ — the resolver is a separate function; do not change `load_effective_config`'s signature.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_remote_config.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiEnvOverlay",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2 only; Google docstrings; 120 cols.
- Never read `os.environ` at import time — only inside `resolve_remote()`.
- Do not touch `load_effective_config` (its merge is generic — verify by test, not by editing).
- The URL validator must reject `ftp://…`, relative paths and empty strings with `ValueError` (Pydantic turns it into `ValidationError`; `load_project_config` already wraps validation errors into `WikiConfigError`).

---

## Implementation Blueprint

### Steps (in order)
1. Insert `WikiRemoteConfig` immediately **before** `class WikiProjectConfig` — *why*: it must be defined before the field annotation that references it.
2. Add the `remote` field to `WikiProjectConfig` right after `sync_graph` — *why*: keeps the FEAT-569 field next to the other opt-in behaviour flags; the anchor is unique.
3. Add `remote: WikiRemoteConfig | None = None` to `WikiEnvOverlay` after `claude` — *why*: the overlay merge iterates `model_fields`, so declaring it is sufficient.
4. Insert `REMOTE_URL_ENV` + `resolve_remote()` immediately **before** `def load_effective_config(` — *why*: module-level helpers group with the config loaders; the anchor is unique.
5. Write the tests, run them, `ruff check` the file.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY — block 1)
```python
# occurrences: 1 (verified: grep -c '^class WikiProjectConfig(BaseModel):' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# BEFORE — insert above `class WikiProjectConfig(BaseModel):` (verified: project.py:379)
class WikiRemoteConfig(BaseModel):
    """Remote wikitoolkit MCP server this repository proxies to (FEAT-569).

    Attributes:
        url: Absolute ``http(s)`` URL of ONE wiki mount, e.g.
            ``https://wiki.example.com/mcp/parrot`` (trailing slash stripped).
        token_env: Environment variable holding the bearer token.
        timeout: Per-call timeout in seconds.
        actor: Explicit ``X-Wiki-Actor`` value; ``None`` derives it from the
            local identity at call time.
        verify_tls: Whether the client verifies the server certificate.
    """

    url: str
    token_env: str = Field(default="WIKITOOLKIT_TOKEN", min_length=1)
    timeout: float = Field(default=30.0, ge=1.0, le=600.0)
    actor: str | None = None
    verify_tls: bool = True

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        """Require an absolute ``http://`` / ``https://`` URL; strip a trailing slash."""
        # FILL IN: urllib.parse.urlsplit(value); scheme in {"http","https"} and netloc non-empty
        #          else raise ValueError(f"remote.url must be an absolute http(s) URL, got {value!r}");
        #          return value.rstrip("/") — bounded by AC7/AC8 (a bad URL must fail at config load, not at call time)
        raise NotImplementedError


```
**Why this shape**: spec §2 Data Models fixes these five fields and their defaults; the validator makes a mistyped URL a `WikiConfigError` at load time (fail-fast), which is where FEAT-461 already surfaces overlay typos.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY — block 2)
```python
# occurrences: 1 (verified: grep -c '    sync_graph: bool = Field(default=False)' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# AFTER — insert below `    sync_graph: bool = Field(default=False)` (verified: project.py:~423, inside WikiProjectConfig)
    remote: WikiRemoteConfig | None = Field(
        default=None,
        description="Proxy every tool-backed command to this remote wikitoolkit MCP server (FEAT-569).",
    )
```
**Why**: the field is optional and `None` by default so every existing `wiki.json` keeps validating and local behaviour is byte-identical (AC14).

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY — block 3)
```python
# occurrences: 1 (verified: grep -c '    claude: ClaudeIntegrationConfig | None = None' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# AFTER — insert below `    claude: ClaudeIntegrationConfig | None = None` (verified: project.py:~828, inside WikiEnvOverlay)
    remote: WikiRemoteConfig | None = None
```
**Why**: `load_effective_config` merges every non-`None` overlay field by name (project.py:~935-941); declaring the field is the whole overlay story. Also add `remote:` to the class docstring's Attributes list.

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY — block 4)
```python
# occurrences: 1 (verified: grep -c '^def load_effective_config(' packages/ai-parrot/src/parrot/knowledge/wiki/project.py)
# BEFORE — insert above `def load_effective_config(` (verified: project.py:897)
REMOTE_URL_ENV = "WIKITOOLKIT_REMOTE_URL"


def resolve_remote(config: WikiProjectConfig) -> WikiRemoteConfig | None:
    """Return the effective remote for this repository, or ``None`` for local mode.

    Precedence: ``WIKITOOLKIT_REMOTE_URL`` (overrides only the URL; the other
    fields come from ``config.remote`` when set, else defaults) > ``config.remote`` > ``None``.

    Args:
        config: The already-merged effective project config.

    Returns:
        The remote to proxy to, or ``None`` when the CLI/MCP must stay local.
    """
    override = os.environ.get(REMOTE_URL_ENV, "").strip()
    if override:
        base = config.remote.model_dump() if config.remote is not None else {}
        return WikiRemoteConfig(**{**base, "url": override})
    return config.remote


```
**Why**: one resolver, no I/O, no token check — TASK-3359's client owns "token missing" so the error names the env var at the moment a request is attempted. `os` is already imported in project.py.

### FILL IN checklist
- [ ] `project.py::WikiRemoteConfig._absolute_http_url` — scheme/netloc check + `rstrip("/")`; bounded by AC7/AC8.
- [ ] `WikiEnvOverlay` docstring Attributes entry for `remote`.
- [ ] Confirm by test (not by code) that `load_effective_config` merges `remote` from `wiki.dev.json`.

---

## Acceptance Criteria

- [ ] `WikiProjectConfig.model_validate({"remote": {"url": "https://h/mcp/parrot/"}}).remote.url == "https://h/mcp/parrot"`.
- [ ] `remote.url = "ftp://x"` / `"/mcp/parrot"` / `""` → `pydantic.ValidationError`.
- [ ] Overlay `.parrot/wiki.dev.json` with `remote.url` overrides the base under `WIKI_ENV=dev`; without overlay the base value is kept.
- [ ] `resolve_remote()` precedence: env override > config > `None`; env override preserves `token_env`/`timeout` from config.
- [ ] Existing `wiki.json` files (no `remote` key) still validate; `test_env_e2e.py` / `test_cli.py` unchanged.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/project.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_remote_config.py -q`
- `pytest tests/knowledge/wiki/test_env_e2e.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_remote_config.py
import json
import pytest
from pydantic import ValidationError
from parrot.knowledge.wiki.project import (
    REMOTE_URL_ENV, WikiProjectConfig, WikiRemoteConfig, load_effective_config, resolve_remote, save_project_config,
)


def test_url_validator_normalises_and_rejects():
    assert WikiRemoteConfig(url="https://h/mcp/parrot/").url == "https://h/mcp/parrot"
    for bad in ("ftp://h/x", "/mcp/parrot", ""):
        with pytest.raises(ValidationError):
            WikiRemoteConfig(url=bad)


def test_overlay_merges_remote(tmp_path, monkeypatch):
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url="https://base/mcp/w")))
    (tmp_path / ".parrot" / "wiki.dev.json").write_text(json.dumps({"remote": {"url": "https://dev/mcp/w"}}))
    monkeypatch.setenv("WIKI_ENV", "dev")
    assert load_effective_config(tmp_path).config.remote.url == "https://dev/mcp/w"


def test_resolve_remote_precedence(monkeypatch):
    cfg = WikiProjectConfig(remote=WikiRemoteConfig(url="https://cfg/mcp/w", token_env="T", timeout=5))
    monkeypatch.delenv(REMOTE_URL_ENV, raising=False)
    assert resolve_remote(cfg).url == "https://cfg/mcp/w"
    monkeypatch.setenv(REMOTE_URL_ENV, "https://env/mcp/w")
    r = resolve_remote(cfg)
    assert (r.url, r.token_env, r.timeout) == ("https://env/mcp/w", "T", 5)
    assert resolve_remote(WikiProjectConfig()) is not None  # env override alone builds a remote
    monkeypatch.delenv(REMOTE_URL_ENV)
    assert resolve_remote(WikiProjectConfig()) is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the four anchor lines still occur exactly once
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
