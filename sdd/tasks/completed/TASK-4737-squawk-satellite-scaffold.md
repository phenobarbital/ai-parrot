# TASK-4737: M0a — scaffold the `ai-parrot-squawk` satellite distribution

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0 (U5): every transport-related part of Squawk lives in a new PEP 420 satellite `ai-parrot-squawk` contributing `parrot.squawk`. This task creates the distribution skeleton (pyproject, README, version, config, tests packages) and registers it in the root workspace declarator, modelled on `packages/ai-parrot-advisors/pyproject.toml`. It is **exclusive** because it edits the root `pyproject.toml` and requires a lockfile refresh. The dead gRPC stub removal is the sibling task TASK-4738.

---

## Scope

- Create `packages/ai-parrot-squawk/pyproject.toml` (setuptools, dynamic version, `namespaces = true`, deps: `ai-parrot` (workspace), `pyarrow>=25.0`, `pycapnp>=2.2.4`, `biscuit-python>=0.4.0`, `cryptography`), `README.md`, `src/parrot/squawk/__init__.py`, `version.py`, `config.py`, `tests/__init__.py`, `tests/spikes/__init__.py`, `tests/test_satellite_imports.py`.
- Add `"ai-parrot-squawk",` to the root `[project] dependencies` and `ai-parrot-squawk = { workspace = true }` to root `[tool.uv.sources]`; run `uv lock` from the **main checkout operator side** (the worktree agent records the need; see Key Constraints).
- **No** `src/parrot/__init__.py` (PEP 420), no grpcio, no polars.

**NOT in scope**: deleting the gRPC stub (TASK-4738), any protocol code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-squawk/pyproject.toml` | CREATE | Distribution metadata + deps |
| `packages/ai-parrot-squawk/README.md` | CREATE | One-page purpose + layout |
| `packages/ai-parrot-squawk/src/parrot/squawk/__init__.py` | CREATE | Package docstring + `__version__` |
| `packages/ai-parrot-squawk/src/parrot/squawk/version.py` | CREATE | `__version__ = "0.1.0"` |
| `packages/ai-parrot-squawk/src/parrot/squawk/config.py` | CREATE | `SQUAWK_*` settings via `parrot.conf.config` |
| `packages/ai-parrot-squawk/tests/__init__.py` | CREATE | tests package |
| `packages/ai-parrot-squawk/tests/spikes/__init__.py` | CREATE | gate-test package |
| `packages/ai-parrot-squawk/tests/test_satellite_imports.py` | CREATE | import + forbidden-import test |
| `pyproject.toml` | MODIFY | workspace dependency + uv source |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import config   # verified pattern: packages/ai-parrot/src/parrot/conf.py:44  `config.get("PLUGINS_DIR", fallback=...)`
```

### Existing Signatures to Use
```toml
# packages/ai-parrot-advisors/pyproject.toml (template)
[project] dependencies = [ ... ]            # line 28
[tool.setuptools.packages.find] where = ["src"]  # line 45 ; namespaces = true  # line 47
[tool.uv.sources] ai-parrot = { workspace = true }   # line 53
# root pyproject.toml
    "ai-parrot-advisors",                   # line 22 (dependencies list)
ai-parrot-advisors = { workspace = true }   # line 242 ([tool.uv.sources])
```

### Does NOT Exist
- ~~`packages/ai-parrot-squawk/`~~ — created here.
- ~~`src/parrot/__init__.py` in any satellite~~ — never create it (PEP 420).
- ~~`ai-parrot-squawk` in `KNOWN_PROJECTS` (`scripts/sdd/sdd_meta.py`)~~ — taxonomy warns; out of scope.
- ~~`grpcio`, `polars` as satellite deps~~ — forbidden (spec AC17).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-squawk/pyproject.toml", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/README.md", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/version.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/config.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/spikes/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/test_satellite_imports.py", "action": "CREATE"},
    {"path": "pyproject.toml", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Exclusive task (`parallel: false`): root `pyproject.toml` + `uv.lock`.
- Worktree agents must not run `uv sync`/`uv lock` against the shared venv (worktree rule). Run `uv lock` only if the task runs in the main checkout; otherwise state in the Completion Note that the operator must run `uv lock && uv sync` and commit `uv.lock` — do not hand-edit the lockfile.
- `cryptography` floor: take the version from `uv.lock` (`grep -A2 'name = "cryptography"' uv.lock`), never guess.
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-squawk/src pytest ...`.

### References in Codebase
- `packages/ai-parrot-advisors/pyproject.toml` — template.
- `packages/ai-parrot-advisors/src/parrot/advisors/version.py` — dynamic version idiom.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the advisors pyproject, rename, set deps and `package-data` — *why*: proven PEP 420 layout.
2. Create `version.py`, `__init__.py`, `config.py` — *why*: dynamic version + the `SQUAWK_*` keys every later module reads.
3. Add the two root pyproject lines — *why*: workspace membership and `uv sync` discovery.
4. Write the import test — *why*: AC18 and the no-polars/no-grpc rule need a permanent check.

### `packages/ai-parrot-squawk/pyproject.toml` (CREATE)
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-squawk"
dynamic = ["version"]
requires-python = ">=3.11,<3.14"
description = "Squawk — typed binary inter-agent protocol for AI-Parrot (Cap'n Proto RPC + event-bus carrier, contract catalog, handles, capability policy gate)"
readme = "README.md"
authors = [{name = "Jesus Lara", email = "jesuslara@phenobarbital.info"}]
license = "MIT"
keywords = ["ai", "agents", "inter-agent", "protocol", "capnproto", "arrow"]
classifiers = ["Development Status :: 3 - Alpha", "Programming Language :: Python :: 3 :: Only", "Framework :: AsyncIO", "Typing :: Typed"]
dependencies = [
    "ai-parrot",
    "pyarrow>=25.0",
    "pycapnp>=2.2.4",
    "biscuit-python>=0.4.0",
    "cryptography>=FILL_IN_FROM_UV_LOCK",
]

[project.urls]
Homepage = "https://github.com/phenobarbital/ai-parrot"
Repository = "https://github.com/phenobarbital/ai-parrot"

[tool.setuptools.dynamic]
version = {attr = "parrot.squawk.version.__version__"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true

[tool.setuptools.package-data]
"parrot.squawk" = ["py.typed", "schema/*.capnp", "sql/*.sql"]

[tool.uv.sources]
ai-parrot = { workspace = true }
```
**Why this shape**: identical to the advisors satellite (verified lines 45-53) so PEP 420 merging into `parrot.*` works; `package-data` already lists the `.capnp`/`.sql` files later modules add.

### `packages/ai-parrot-squawk/src/parrot/squawk/version.py` (CREATE)
```python
"""Version of the ai-parrot-squawk distribution."""
__version__ = "0.1.0"
```

### `packages/ai-parrot-squawk/src/parrot/squawk/__init__.py` (CREATE)
```python
"""Squawk — typed binary inter-agent protocol for parrot-to-parrot cross-network calls (FEAT-746).

The transport-free data contract lives in core ``parrot.interagent``; this package owns
the Cap'n Proto schema and codec, the RPC and bus carriers, the serving dispatcher and
policy gate, the served ledger, the blob store, the client toolkit and the adapters.
"""
from .version import __version__

__all__ = ["__version__"]
```

### `packages/ai-parrot-squawk/src/parrot/squawk/config.py` (CREATE)
```python
"""Deployment settings for Squawk, read through ``parrot.conf.config`` (env / navconfig)."""
from __future__ import annotations

from pathlib import Path

from parrot.conf import config  # verified pattern: packages/ai-parrot/src/parrot/conf.py:44

#: "local" | "filemanager" — which SquawkBlobStore backend a deployment uses (spec Q8).
SQUAWK_BLOB_BACKEND: str = config.get("SQUAWK_BLOB_BACKEND", fallback="local")
SQUAWK_BLOB_ROOT: Path = Path(config.get("SQUAWK_BLOB_ROOT", fallback=".squawk/blobs"))
SQUAWK_BLOB_TTL_S: int = int(config.get("SQUAWK_BLOB_TTL_S", fallback=86_400))
SQUAWK_MAX_FRAME_BYTES: int = int(config.get("SQUAWK_MAX_FRAME_BYTES", fallback=4 * 1024 * 1024))
#: Root public key for Biscuit verification (issuance is navigator-auth's, spec Q4). None ⇒ tokens refused.
SQUAWK_BISCUIT_ROOT_PUBLIC_KEY: str | None = config.get("SQUAWK_BISCUIT_ROOT_PUBLIC_KEY", fallback=None)
#: YAML overriding DEFAULT_GATE_POLICIES per data class (spec Q5). None ⇒ built-in defaults only.
_gate = config.get("SQUAWK_GATE_POLICY_PATH", fallback=None)
SQUAWK_GATE_POLICY_PATH: Path | None = Path(_gate) if _gate else None
```

### `packages/ai-parrot-squawk/tests/test_satellite_imports.py` (CREATE)
```python
"""AC18 / AC17 — the satellite imports with core and never imports polars or grpc."""
from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "parrot" / "squawk"


def test_import_and_version():
    import parrot.squawk as sq

    assert re.match(r"^\d+\.\d+\.\d+", sq.__version__)


def test_no_namespace_init():
    assert not (SRC.parent / "__init__.py").exists(), "PEP 420: src/parrot/__init__.py must not exist"


def test_no_forbidden_imports():
    pat = re.compile(r"^\s*(import|from)\s+(polars|grpc)\b", re.M)
    for py in SRC.rglob("*.py"):
        assert not pat.search(py.read_text()), f"forbidden import in {py}"
```

### `pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '    "ai-parrot-advisors",' pyproject.toml)
# AFTER — insert below `    "ai-parrot-advisors",` (verified: pyproject.toml:22)
    "ai-parrot-squawk",
```
```toml
# occurrences: 1 (verified: grep -c 'ai-parrot-advisors = { workspace = true }' pyproject.toml)
# AFTER — insert below `ai-parrot-advisors = { workspace = true }` (verified: pyproject.toml:242)
ai-parrot-squawk = { workspace = true }
```
**Why**: the root declarator lists every workspace member in both places (verified for advisors).

### FILL IN checklist
- [ ] `pyproject.toml::cryptography` floor — from `uv.lock`; bounded by "declare, never guess"
- [ ] `README.md` — purpose, layout table (contract/schema/transport/server/client/blobs/security/adapters), install line
- [ ] `uv.lock` refresh — operator action if in a worktree (state it in the Completion Note)

---

## Acceptance Criteria

- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-squawk/src pytest packages/ai-parrot-squawk/tests/test_satellite_imports.py -q` passes
- [ ] Root `pyproject.toml` lists `ai-parrot-squawk` in dependencies and `[tool.uv.sources]`
- [ ] No `src/parrot/__init__.py`; no grpcio/polars declared (AC17, AC18)
- [ ] `ruff check packages/ai-parrot-squawk` clean

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/test_satellite_imports.py -q`

---

## Test Specification

See blueprint test file.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M0, §7 Patterns (satellite packaging)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** (re-grep both root pyproject anchors)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement** from the blueprint
7. **Verify** — Validation Commands
8. **Commit** — only the listed files (and `uv.lock` only if you ran `uv lock` in the main checkout)
9. **Close** with `scripts/sdd/close_task.sh TASK-4737 inter-agent-protocol verified`
10. **Completion Note** — state whether `uv.lock` was refreshed

---

## Completion Note

**Completed by**: sdd-worker (seat: gpt-5.6-terra · codex · 1 attempt · 163s)
**Date**: 2026-10-26
**Notes**: Satellite scaffold delivered; its own test (3 passed) and diff review against acceptance criteria are green. Merge-tier selector reported 4 failures in `packages/ai-parrot/tests/repl_worker` / `task_memory/test_strict_worker_transport.py` (REPL worker `output_dir escapes allowed directories` under the sandboxed /tmp); reproduced on unmodified `dev`, so they are pre-existing and not caused by this task. `uv.lock` not refreshed (read-only shared env).

**Deviations from spec**: none
