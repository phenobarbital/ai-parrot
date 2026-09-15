# TASK-3087: MCP toolkit configuration — `ToolkitSection.llm_kwargs` pass-through and example config

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Client Configuration and Lifecycle", §3 Module M6, AC8 (config
half). The MCP toolkit server currently builds an LLM client with
`LLMFactory.create(section.llm)` and no extra kwargs
(`toolkit_server.py:100-102`). The writer needs
`fallback_model: null`, `max_retries`, `read_timeout` on the Bedrock
client, so `ToolkitSection` gains an optional, trusted `llm_kwargs`
mapping. Old configurations must behave identically.

This task touches only core `parrot.mcp` files, the example YAML and
core tests, so it can run in parallel with the toolkit tasks.

---

## Scope

- `packages/ai-parrot/src/parrot/mcp/toolkit_config.py`:
  - Add `llm_kwargs: dict[str, Any] = Field(default_factory=dict)` to
    `ToolkitSection` with a docstring line in the class Attributes list.
  - Add `@model_validator(mode="after")`: `llm_kwargs` non-empty without
    `llm` → `ValueError("llm_kwargs requires llm")`; key `"llm"` present →
    `ValueError("llm_kwargs must not contain 'llm' (collides with LLMFactory.create's first argument)")`.
    Keep `populate_by_name=True`.
- `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`:
  - `LLMFactory.create(section.llm, **section.llm_kwargs)` — same lazy
    import block; nothing else changes. Deterministic toolkits (no `llm`)
    still never import `LLMFactory` (existing behaviour, asserted by
    `test_stdout_purity`-style test).
- `examples/tool-optimizations-mcp.yaml` (CREATE) — the spec's example,
  verbatim, plus comments explaining each key and the alias provenance
  (`qwen3-coder-480b-a35b` → `qwen.qwen3-coder-480b-a35b-v1:0`,
  `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/models.py:130`)
  and that `fallback_model: null` is REQUIRED for the writer
  (`bedrock.py:1669` default). `examples/**/*.py` is gitignored but
  `.yaml` is not (verified with `git check-ignore`); commit it normally.
  Also add `expected_model_ids: ["qwen.qwen3-coder-480b-a35b-v1:0"]`
  under `targeted-writer.kwargs` (consumed by TASK-3085's constructor).
- `docs/mcp-local-toolkits.md`: add `llm_kwargs` to the "Schema" table
  (§ "Configuration") with two sentences and a pointer to the example.
- Tests (root `tests/mcp/`, where FEAT-485's suites live):
  - `tests/mcp/test_toolkit_config.py`: `llm_kwargs` default empty; YAML
    section with `llm` + `llm_kwargs` parses; without `llm` → ValueError
    naming the section; with `llm` key inside → ValueError; old sections
    (no key) unchanged (`test_builtin_defaults_match` still passes).
  - `tests/mcp/test_toolkit_server.py`: extend the existing
    `test_llm_wired_when_configured` pattern (mock `LLMFactory.create`,
    `:114-140`) to assert `create` receives
    `("bedrock-converse:qwen3-coder-480b-a35b", fallback_model=None, max_retries=1, read_timeout=120)`;
    add a test that a toolkit without `llm` never triggers the
    `parrot.clients.factory` import (monkeypatch `importlib.import_module`
    to fail on that name — reuse the file's `mock_import_module` fixture).
  - `tests/mcp/test_toolkit_config.py`: load `examples/tool-optimizations-mcp.yaml`
    through `load_toolkits_config(root, config_path=...)` and assert the
    three sections, class paths, `llm_kwargs["fallback_model"] is None`.

**NOT in scope**: the toolkit classes themselves; installer changes
(TASK-3089); stdio exposure tests for the three servers (TASK-3091).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` | MODIFY | `llm_kwargs` field + validator |
| `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | MODIFY | Pass `**section.llm_kwargs` |
| `examples/tool-optimizations-mcp.yaml` | CREATE | Example configuration |
| `docs/mcp-local-toolkits.md` | MODIFY | Schema table row |
| `tests/mcp/test_toolkit_config.py` | MODIFY | New cases |
| `tests/mcp/test_toolkit_server.py` | MODIFY | Pass-through + no-import cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import ToolkitSection, MCPToolkitsConfig, load_toolkits_config   # toolkit_config.py:19, :54, :80
from parrot.mcp.toolkit_server import create_toolkit_mcp_server                                 # toolkit_server.py:29
from pydantic import BaseModel, ConfigDict, Field, model_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):                       # :19
    class_path: str = Field(..., alias="class")        # :43
    enabled: bool = True                               # :44
    kwargs: dict[str, Any] = Field(default_factory=dict)   # :45
    include: list[str] | None = None                   # :46
    exclude: list[str] | None = None                   # :47
    llm: str | None = None                             # :48
    env: dict[str, str] = Field(default_factory=dict)  # :49
    model_config = ConfigDict(populate_by_name=True)   # :51
BUILTIN_TOOLKITS: dict[str, ToolkitSection]            # :64 (scraping/browsing/memory) — unchanged
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig   # :80 (:147-152 model_validate per section, error names the section)

# packages/ai-parrot/src/parrot/mcp/toolkit_server.py
def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer   # :29
#   :96-106   if section.llm: from parrot.clients.factory import LLMFactory; llm_client = LLMFactory.create(section.llm)
#             else: drop_tools = set(toolkit_cls.llm_dependent_tools)
#   :108-112  kwargs = dict(section.kwargs); if llm_client is not None: kwargs["llm_client"] = llm_client; toolkit = toolkit_cls(**kwargs)

# packages/ai-parrot/src/parrot/clients/factory.py
@staticmethod
def create(llm: str, model_args: Optional[Dict[str, Any]] = None, tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient   # :257
#   :336 init_params.update(kwargs) → :339 client_class(**init_params)   ⇒ llm_kwargs reach the client constructor verbatim

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py
#   ctor accepts read_timeout (stored :270 self._read_timeout) and fallback_model (:282 setdefault) ; base ctor accepts max_retries (:188)
```

### Does NOT Exist
- ~~`ToolkitSection.llm_kwargs`~~ — does not exist yet (this task adds it).
- ~~`ToolkitSection.model_args`~~ — not a field; `llm_kwargs` may carry `model_args` because the factory has that parameter, but do not add a dedicated field.
- ~~Deep-merging `llm_kwargs` with builtin sections~~ — file sections replace builtins wholesale (existing rule, `toolkit_config.py:90-93`).
- ~~`examples/` being a Python package or gitignored for YAML~~ — only `examples/**/*.py` is ignored.

---

## Implementation Notes

### Pattern to Follow
```python
# toolkit_config.py
llm_kwargs: dict[str, Any] = Field(default_factory=dict)

@model_validator(mode="after")
def _check_llm_kwargs(self) -> "ToolkitSection":
    if self.llm_kwargs and not self.llm:
        raise ValueError("llm_kwargs requires llm to be set")
    if "llm" in self.llm_kwargs:
        raise ValueError("llm_kwargs must not contain 'llm' (collides with LLMFactory.create(llm=...))")
    return self
```

```yaml
# examples/tool-optimizations-mcp.yaml (spec §2 example, extended with expected_model_ids)
toolkits:
  local-git:
    class: parrot_tools.tool_optimizations.git.LocalGitToolkit
    kwargs:
      repo_root: .
  bounded-source:
    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit
    kwargs:
      repo_root: .
  targeted-writer:
    class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit
    llm: bedrock-converse:qwen3-coder-480b-a35b
    llm_kwargs:
      fallback_model: null     # REQUIRED: BedrockConverseClient otherwise falls back to claude-haiku-4-5
      max_retries: 1
      read_timeout: 120
    kwargs:
      repo_root: .
      expected_model_ids: ["qwen.qwen3-coder-480b-a35b-v1:0"]
```

### Key Constraints
- `repo_root: .` is relative to the MCP host's cwd; document in the YAML
  comment that hosts may start servers from a different cwd and that
  `parrot mcp-local --config` exists (`toolkit_server.py:66-72`).
- No secrets in the example (AWS credentials come from the standard
  chain — `bedrock.py:236-243`).
- `filterwarnings = error`: use `model_validator`, not deprecated
  `root_validator`.

### References in Codebase
- `tests/mcp/test_toolkit_server.py:114-140` — mock-factory pattern.
- `tests/mcp/test_toolkit_config.py:98-130` — builtin/alias tests to keep green.
- `docs/mcp-local-toolkits.md:45-100` — schema section to extend.

---

## Acceptance Criteria

- [ ] Old YAML without `llm_kwargs` produces identical `ToolkitSection` objects (existing tests untouched and green).
- [ ] `llm_kwargs` without `llm` → `ValueError` whose message names the section (through `load_toolkits_config`).
- [ ] `llm_kwargs: {llm: x}` → rejected.
- [ ] `LLMFactory.create` receives `section.llm` plus the kwargs verbatim; without `llm`, `parrot.clients.factory` is never imported.
- [ ] Example YAML loads; `targeted-writer.llm_kwargs["fallback_model"] is None`.
- [ ] All tests pass: `pytest tests/mcp -v`; `ruff check packages/ai-parrot/src/parrot/mcp`; log in `artifacts/logs/TASK-3087-pytest.log`.

---

## Test Specification

```python
# tests/mcp/test_toolkit_config.py (additions)
def test_llm_kwargs_requires_llm(tmp_path):
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  w:\n    class: x.Y\n    llm_kwargs: {fallback_model: null}\n")
    with pytest.raises(ValueError, match="'w'"):
        load_toolkits_config(tmp_path)

def test_llm_kwargs_rejects_llm_key():
    with pytest.raises(ValueError):
        ToolkitSection.model_validate({"class": "x.Y", "llm": "openai:gpt", "llm_kwargs": {"llm": "z"}})

def test_example_config_loads():
    cfg = load_toolkits_config(Path.cwd(), config_path=Path("examples/tool-optimizations-mcp.yaml"))
    assert set(cfg.toolkits) >= {"local-git", "bounded-source", "targeted-writer"}
    w = cfg.toolkits["targeted-writer"]
    assert w.llm == "bedrock-converse:qwen3-coder-480b-a35b" and w.llm_kwargs["fallback_model"] is None
    assert cfg.toolkits["local-git"].llm is None and cfg.toolkits["local-git"].llm_kwargs == {}
```

```python
# tests/mcp/test_toolkit_server.py (addition, mirrors :114-140)
def test_llm_kwargs_passed_to_factory(stub_config, monkeypatch):
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)
    ...write stub_config section with llm + llm_kwargs...
    from parrot.clients.factory import LLMFactory
    seen = {}
    monkeypatch.setattr(LLMFactory, "create", staticmethod(lambda llm, **kw: seen.update({"llm": llm, **kw}) or object()))
    create_toolkit_mcp_server("stub", root=stub_config)
    assert seen == {"llm": "bedrock-converse:qwen3-coder-480b-a35b", "fallback_model": None, "max_retries": 1, "read_timeout": 120}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3087-mcp-llm-kwargs-config.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Added `ToolkitSection.llm_kwargs` with its `model_validator`, changed the
one factory call to `LLMFactory.create(section.llm, **section.llm_kwargs)`,
created `examples/tool-optimizations-mcp.yaml`, documented the field in
`docs/mcp-local-toolkits.md`, and added 8 tests (33 passing across the two
toolkit test modules).

The production diff is deliberately tiny — 4 lines in `toolkit_server.py`
and a field plus validator in `toolkit_config.py` — because backward
compatibility is the requirement: a section without `llm_kwargs` produces
an identical call, asserted by
`test_old_config_without_llm_kwargs_is_unchanged` (`seen["kwargs"] == {}`).

Tests worth noting:

- `test_llm_kwargs_passed_to_factory` asserts the captured kwargs are
  exactly `{"fallback_model": None, "max_retries": 1, "read_timeout": 120}`
  **and** that `fallback_model` is present as a key. An explicit `None` is
  not the same as an absent key here: `BedrockConverseBase.__init__` uses
  `kwargs.setdefault("fallback_model", self._fallback_model)`, so only an
  explicitly-passed `None` prevents the class default `claude-haiku-4-5`.
- `test_deterministic_toolkit_never_imports_the_client_factory` makes
  `importlib.import_module("parrot.clients.factory")` *raise*, so a
  regression that eagerly imports the factory for a model-free toolkit
  fails loudly. This is what keeps the Git and reader servers free of
  provider/AWS dependencies.
- `test_example_tool_optimizations_config_loads` loads the shipped example
  and pins `fallback_model is None` plus the `expected_model_ids` entry, so
  the documented configuration cannot silently rot.

**Environment note for later tasks (important).** The venv's editable
installs point at the MAIN repo checkout, so core `parrot` changes made in
this worktree are invisible to pytest unless
`PYTHONPATH=$PWD/packages/ai-parrot/src` is set. Doing that initially broke
imports with `ModuleNotFoundError: parrot.utils.types` — that module is a
compiled Cython extension whose `.so` is a gitignored build artifact
present only in the main checkout. Fixed by symlinking the two compiled
extensions into the worktree:

    packages/ai-parrot/src/parrot/utils/types.cpython-312-*.so
    packages/ai-parrot/src/parrot/utils/parsers/toml.cpython-312-*.so

Both are covered by `.gitignore:7` (`*.so`), so they never enter the repo.
`parrot/__init__.py` uses `pkgutil.extend_path`, so the satellite packages
(e.g. `parrot.clients.amazon`) still resolve from the main checkout while
core modules resolve from the worktree — verified explicitly.

**Pre-existing failures, not caused by this change.** `pytest tests/mcp`
reports 10 failures and 1 error on this branch; running the same suite on
`dev` reports the *same* 10 failures and 1 error (netsuite, oauth,
chrome-manager). This branch adds 8 passing tests (184 -> 192 passed).
Likewise, `ruff check packages/ai-parrot/src/parrot/mcp` reports 2
pre-existing implicit-string-concat errors at `toolkit_server.py:86` and 3
in `integration.py`; `git show dev:...` confirms line 86 is unchanged by
this task. They were left alone rather than opportunistically fixed.
`black --check` is clean on both files this task modified.

**Testing**: 33 tests in the two toolkit modules; log at
`artifacts/logs/TASK-3087-pytest.log`.

**Deviations from spec**: none.
