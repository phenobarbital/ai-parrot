# TASK-5114: Core toolkits serve without ai-parrot-tools (resolver built-ins tolerate a missing distribution)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12, amendments C34–C35 — acceptance gap)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5113
**Assigned-to**: unassigned

---

## Context

Testing TASK-5112/5113 in the sandbox project (a foreign repo that installs `ai-parrot` from source and does
**not** install `ai-parrot-tools`): `parrot sdd install` registered `parrot-sdd-coder` and `parrot-bounded-source`
in `.mcp.json`, but both servers die at start-up:

```
$ parrot mcp-local bounded-source --config .parrot/mcp-toolkits.yaml
Error: No module named 'parrot_tools'
```

Cause (pre-existing on `dev`, not introduced by FEAT-633): every `AbstractToolkit.get_tools()` →
`_generate_tools()` → `_create_tool_from_method()` → `effective_access()` → `_is_host_class()` →
`ToolkitResolver.entries()` → `_build()` → `_builtin_classes()`, which imports
`parrot.knowledge.wiki.LLMWikiToolkit`; that name is a lazy re-export of `parrot_tools.wiki.toolkit`
(`parrot/knowledge/wiki/toolkit.py` `_EXPORTS`). Without the distribution the import raises, so **no** core
toolkit can list its tools and no `parrot mcp-local` server starts. TASK-5112's tests hid `parrot_tools` only for
the import, never for `get_tools()` or a served handshake, and the test environment has ai-parrot-tools installed.

Verified by simulation in the sandbox venv (2026-11-03): with `_builtin_classes` skipping the class whose import
fails, `BoundedSourceToolkit(repo_root=".").get_tools()` returns its 3 tools; `DatasetManager` and
`InfographicToolkit` import fine without `parrot_tools`; `_build()` already guards the `parrot_tools.TOOL_REGISTRY`
lookup with `except ImportError`.

---

## Scope

- In `packages/ai-parrot/src/parrot/tools/resolver.py`, make `_builtin_classes()` import each built-in toolkit
  class independently and omit the one whose import raises `ImportError` (log once at DEBUG with the slug and the
  missing module). The returned dict keeps the same slugs and classes when everything imports.
- Write `packages/ai-parrot/tests/tools/test_resolver_without_parrot_tools.py`:
  - with `parrot_tools` hidden (`monkeypatch.setitem(sys.modules, "parrot_tools", None)` plus every
    `parrot_tools.*` entry removed, and the resolver singleton reset), `_builtin_classes()` has no `"wiki"` and
    still has `"dataset_manager"` / `"infographic"`;
  - in a **subprocess** that blocks `parrot_tools` with a `sys.meta_path` finder raising `ModuleNotFoundError`,
    `BoundedSourceToolkit(repo_root=tmp).get_tools()` and `SddCoderToolkit` tool generation both succeed;
  - in the same blocked subprocess, `parrot mcp-local bounded-source --config <seeded yaml>` answers a JSON-RPC
    `initialize` with a `result` (stdout is one JSON line, nothing else).
  - with `parrot_tools` available (normal test env), `_builtin_classes()["wiki"]` is still `LLMWikiToolkit`.

**NOT in scope**:
- Making `LLMWikiToolkit` itself work without ai-parrot-tools.
- Any change to `parrot/knowledge/wiki/toolkit.py`'s lazy exports, the installer, or the templates.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/resolver.py` | MODIFY | `_builtin_classes()` tolerates a missing optional distribution |
| `packages/ai-parrot/tests/tools/test_resolver_without_parrot_tools.py` | CREATE | Unit + subprocess + served-handshake regression tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `origin/feat-FEAT-633-parrot-installer` at `607b259571` (2026-11-03).

### Verified Imports
```python
from parrot.tools.resolver import _builtin_classes, get_toolkit_resolver      # resolver.py:38, :241
from parrot.tools.optimizations.reader import BoundedSourceToolkit             # TASK-5112
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/resolver.py
def _builtin_classes() -> dict[str, type]:                         # line 38
    from parrot.knowledge.wiki import LLMWikiToolkit                # line 40  <- raises without parrot_tools
    from parrot.tools.dataset_manager.tool import DatasetManager    # line 41
    from parrot.tools.infographic_toolkit import InfographicToolkit # line 42
    return {"dataset_manager": DatasetManager, "wiki": LLMWikiToolkit, "infographic": InfographicToolkit}
class ToolkitResolver:
    def entries(self) -> list[ToolkitEntry]                         # line 58
    def is_host_class(self, cls: type) -> bool                      # line 77
    def _ensure(self) -> dict[str, ToolkitEntry]                    # line 118
    def _build(self) -> dict[str, ToolkitEntry]                     # line 132 — loops _builtin_classes() (136);
                                                                    #   parrot_tools.TOOL_REGISTRY already in try/except ImportError
def get_toolkit_resolver() -> ToolkitResolver                       # line 241

# packages/ai-parrot/src/parrot/tools/toolkit.py
def _is_host_class(cls: type) -> bool                               # line 203 — get_toolkit_resolver().is_host_class(cls)
def effective_access(cls: type, method_name: str) -> Optional[str]  # line 214

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
_EXPORTS = {"LLMWikiToolkit": "parrot_tools.wiki.toolkit", ...}     # line 6 — lazy re-export to the optional dist

# existing resolver tests to keep green: packages/ai-parrot/tests/tools/test_toolkit_resolver.py
```

### Does NOT Exist
- ~~a resolver reset helper~~ — check `test_toolkit_resolver.py` for how it resets the singleton; reuse that, do not invent one
- ~~a core `LLMWikiToolkit` implementation~~ — it lives only in ai-parrot-tools

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/resolver.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_resolver_without_parrot_tools.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/resolver.py#_builtin_classes",
    "sym:packages/ai-parrot/src/parrot/tools/resolver.py#ToolkitResolver",
    "sym:packages/ai-parrot/src/parrot/tools/resolver.py#get_toolkit_resolver",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#effective_access"
  ]
}
```

---

## Acceptance Criteria

- [ ] With `parrot_tools` blocked, `BoundedSourceToolkit(...).get_tools()` and `SddCoderToolkit` tool generation succeed.
- [ ] With `parrot_tools` blocked, `parrot mcp-local bounded-source` answers `initialize` with a `result` on clean stdout.
- [ ] With `parrot_tools` available, the resolver still lists `wiki` → `LLMWikiToolkit` (no behaviour change).
- [ ] `test_toolkit_resolver.py`, `test_optimizations_core.py`, `test_installer_toolkits.py` still pass; `ruff check` clean.
- [ ] Re-run in the sandbox project: both registered servers complete the `initialize` + `tools/list` handshake
      (record the tool counts in the Completion Note).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_resolver_without_parrot_tools.py -q`
- `pytest packages/ai-parrot/tests/tools/test_toolkit_resolver.py -q`
- `pytest packages/ai-parrot/tests/tools/test_optimizations_core.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_toolkits.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_resolver_without_parrot_tools.py
import subprocess
import sys
import textwrap

BLOCK = textwrap.dedent('''
    import sys
    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name == "parrot_tools" or name.startswith("parrot_tools."):
                raise ModuleNotFoundError(f"No module named {name!r}")
    sys.meta_path.insert(0, _Block())
''')


def _run(code: str, tmp_path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", BLOCK + code], capture_output=True, text=True, cwd=tmp_path)


def test_bounded_source_lists_tools_without_parrot_tools(tmp_path) -> None:
    proc = _run("from parrot.tools.optimizations.reader import BoundedSourceToolkit\n"
                f"print(len(BoundedSourceToolkit(repo_root={str(tmp_path)!r}).get_tools()))", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip().splitlines()[-1]) > 0


def test_sdd_coder_tools_without_parrot_tools(tmp_path) -> None: ...
def test_mcp_local_bounded_source_handshake_without_parrot_tools(tmp_path) -> None: ...
def test_wiki_still_builtin_when_parrot_tools_present() -> None: ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — branch `feat-FEAT-633-parrot-installer` (never on `dev`)
2. **Check dependencies** — TASK-5113 must be `done`
3. **Verify the Codebase Contract**, then mark `"in-progress"` in the index and commit only that file
4. **Implement**, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
5. **Commit the code** — stage only the two files above
6. **Close the task** with `parrot sdd task close TASK-5114 parrot-installer verified`
7. **Fill in the Completion Note** (include the sandbox handshake result), then commit the staged SDD state

---

## Completion Note
*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
