# TASK-1948: TOML compressor manifest schema + multi-source CompressorRegistry

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1947
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half) and §2 "Data Models". This task makes
compression **configurable without touching core Python** (G6): a project
`.parrot/compressors.toml`, third-party package manifests, and core defaults
are merged into one immutable `CompressorRegistry` loaded once per process.

The multi-source discovery mechanics mirror `parrot/tools/discovery.py`.
Load-time validation is a hard requirement: a malformed TOML or an unknown
`codec` value must fail at startup with the file path and the offending entry
— never silently at the first tool call.

---

## Scope

- Implement `config.py`: the Pydantic TOML schema (`CompressorEntry`,
  `CompressorConfig`) exactly as specified in §2.
- Implement `registry.py`: `CompressorRegistry` with
  - `load(project_root=None)` classmethod — reads, in precedence order:
    1. project `.parrot/compressors.toml`
    2. third-party package manifests (discovery-style multi-source walk)
    3. core defaults (a `compressors.toml` shipped inside
       `parrot/tools/compression/`)
  - `resolve(tool_name) -> CompressorEntry | None` — match precedence:
    exact `tool_name` → glob pattern (`fnmatch`) → `"*"` wildcard.
  - Immutability after load (mutating accessors raise).
- Emit `logger.warning` when a user entry shadows a built-in entry, naming
  both sources.
- Validate at load: unknown `codec` (not in `known_codecs()`) raises an
  explicit error carrying the manifest path and the offending entry key.
- Ship the core default manifest containing at minimum
  `[compressor."*"] codec = "json_compact", level = "minimal"`.
- Export `CompressorRegistry` from `compression/__init__.py`.
- Provide a **test fixture package** proving a third-party package can add a
  compressor with zero core edits (acceptance criterion G6).

**NOT in scope**:
- The `json_compact` codec implementation itself → TASK-1949 (this task's
  core default manifest names it; tests here register a dummy codec or
  `pytest.importorskip` rather than depending on TASK-1949).
- Effective-**level** precedence resolution (per-call override, error-forces-
  NONE, global default) → that is the stage's job, TASK-1951. This task
  resolves the **entry** (codec + configured level + tee + params) only.
- Any `manager.py` change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/config.py` | CREATE | `CompressorEntry`, `CompressorConfig` Pydantic schema |
| `packages/ai-parrot/src/parrot/tools/compression/registry.py` | CREATE | `CompressorRegistry` multi-source loader + match resolution |
| `packages/ai-parrot/src/parrot/tools/compression/compressors.toml` | CREATE | Core default manifest (wildcard → `json_compact`/`minimal`) |
| `packages/ai-parrot/src/parrot/tools/compression/__init__.py` | MODIFY | Export `CompressorRegistry` |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `"parrot.tools.compression" = ["*.toml"]` to package-data so the default manifest ships in the wheel |
| `packages/ai-parrot/tests/tools/compression/test_registry.py` | CREATE | Unit tests |
| `packages/ai-parrot/tests/tools/compression/fixture_pkg/` | CREATE | Third-party fixture package with its own `compressors.toml` (G6 proof) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.
> Restrict every `grep` to `packages/ai-parrot/src/`.

### Verified Imports

```python
import tomllib                                   # stdlib, py >= 3.11 — no new dependency
from fnmatch import fnmatch
from pydantic import BaseModel, Field

# Created by TASK-1947 (must exist before you start):
from parrot.tools.compression import FilterLevel, known_codecs
```

### Existing Signatures to Use

```python
# parrot/tools/discovery.py — multi-source mechanics to MIRROR (do not import
# these to load TOML; they discover tool classes, not manifests. Copy the
# source-precedence shape, not the functions.)
DEFAULT_SOURCES = [...]                                        # line 22
def discover_from_registry(sources=None) -> Dict[str, str]: ...      # line 31
def discover_from_walk(sources=None, filter_fn=None) -> Dict[str, Type]: ...  # line 64
def discover_all(sources=None) -> Dict[str, Union[str, Type]]: ...   # line 111
def resolve_class(dotted_path: str) -> Type: ...                     # line 139
# NOTE: TOOL_REGISTRY is a CONVENTION (a dict in an external package's
# __init__.py), NOT a symbol defined in discovery.py or registry.py.

# parrot/tools/registry.py
class ToolkitRegistry: ...                       # line 42 — naming/style reference
def get_supported_toolkits(): ...                # line 78
```

### Contract to Create

```python
# parrot/tools/compression/config.py
class CompressorEntry(BaseModel):
    codec: str                                  # must be in known_codecs() at load
    level: FilterLevel = FilterLevel.MINIMAL
    tee: bool = False
    params: dict[str, Any] = Field(default_factory=dict)

class CompressorConfig(BaseModel):
    compressor: dict[str, CompressorEntry]      # keys: exact tool name | glob | "*"
```

TOML format (per-package manifest; project override wins):

```toml
[compressor."execute_database_query"]
codec = "columnar"
level = "normal"
tee = true
  [compressor."execute_database_query".params]
  min_rows = 20
  drop_null_columns = true

[compressor."*"]
codec = "json_compact"
level = "minimal"
```

### Does NOT Exist

- ~~`parrot.tools.discovery.discover_manifests()`~~ — no manifest discovery
  exists; you are writing it.
- ~~A `.parrot/` directory convention in this repo~~ — verify before assuming;
  the project-level path is a new convention introduced by this feature.
- ~~`tomli`~~ — do NOT add it as a dependency; `tomllib` is stdlib on the
  supported Python floor (3.11).
- ~~`CompressorRegistry` in any existing module~~ — zero occurrences.
- ~~A global mutable codec config~~ — the registry is immutable after `load()`
  by design; do not add a `set()`/`update()` public method.

---

## Implementation Notes

### Pattern to Follow

```python
# registry.py — precedence is source-order, later sources NEVER override earlier
class CompressorRegistry:
    """Immutable, process-wide compressor configuration."""

    @classmethod
    def load(cls, project_root: Path | None = None) -> "CompressorRegistry":
        merged: dict[str, tuple[CompressorEntry, str]] = {}   # key -> (entry, source)
        for path in cls._sources(project_root):        # project → 3rd-party → core
            cfg = cls._parse(path)                     # tomllib + Pydantic + validate
            for key, entry in cfg.compressor.items():
                if key in merged:
                    continue                           # first source wins
                merged[key] = (entry, str(path))
        return cls(merged)
```

Match resolution — check in this order and return the first hit:
1. exact `tool_name` key
2. glob keys via `fnmatch(tool_name, key)` (deterministic order: sort glob
   keys, longest-first, so `execute_db_*` beats `execute_*`)
3. the `"*"` key

### Key Constraints

- Load-time error message MUST include the manifest path and the offending
  entry key, e.g.
  `Unknown codec 'colunmar' for entry 'execute_database_query' in /abs/path/compressors.toml (known: columnar, json_compact)`.
- Shadow warning fires when a *project or third-party* key shadows a key that
  also appears in the **core** manifest — log both paths at `warning`.
- `tomllib.load` requires a **binary** file handle (`open(path, "rb")`).
- Missing manifests are not an error — absent sources are skipped silently.
- Registry is loaded once per process and shared by reference across
  `ToolManager.clone()` (spec §7); do not put per-session state on it.

### References in Codebase

- `parrot/tools/discovery.py:22-139` — the multi-source shape to mirror.
- `parrot/tools/registry.py:42` — registry naming/style in this package.

---

## Acceptance Criteria

- [ ] `from parrot.tools.compression import CompressorRegistry` works.
- [ ] With no manifest anywhere, `resolve(<any tool>)` falls back to the core
      default (wildcard → `json_compact`/`MINIMAL`) — the G2 "zero config is
      lossless" baseline.
- [ ] Unknown `codec` value → explicit error at `load()` naming file path and
      entry; NOT at first tool call.
- [ ] Malformed TOML → explicit error at `load()` naming the file path.
- [ ] Match precedence exact > glob > `"*"` verified; a shadowed built-in
      emits `logger.warning`.
- [ ] A fixture package under `tests/.../fixture_pkg/` contributes a
      compressor entry with **zero edits to core files** (G6).
- [ ] Registry is immutable after load (mutation attempt raises).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_registry.py
import pytest
from parrot.tools.compression import FilterLevel, CompressorRegistry


@pytest.fixture
def compressors_toml(tmp_path):
    """Project-level .parrot/compressors.toml with exact/glob/wildcard entries."""
    d = tmp_path / ".parrot"
    d.mkdir()
    (d / "compressors.toml").write_text(
        '[compressor."execute_database_query"]\n'
        'codec = "json_compact"\nlevel = "normal"\ntee = true\n'
        '[compressor."execute_db_*"]\ncodec = "json_compact"\nlevel = "minimal"\n'
        '[compressor."*"]\ncodec = "json_compact"\nlevel = "minimal"\n'
    )
    return tmp_path


class TestCompressorRegistry:
    def test_filterlevel_default_minimal(self, tmp_path):
        """No config anywhere → effective entry level is MINIMAL."""
        reg = CompressorRegistry.load(project_root=tmp_path)
        assert reg.resolve("anything").level is FilterLevel.MINIMAL

    def test_resolution_exact_over_glob_over_wildcard(self, compressors_toml):
        reg = CompressorRegistry.load(project_root=compressors_toml)
        assert reg.resolve("execute_database_query").level is FilterLevel.NORMAL
        assert reg.resolve("execute_db_other").level is FilterLevel.MINIMAL
        assert reg.resolve("unrelated_tool").level is FilterLevel.MINIMAL

    def test_toml_unknown_codec_fails_at_load(self, tmp_path):
        d = tmp_path / ".parrot"; d.mkdir()
        f = d / "compressors.toml"
        f.write_text('[compressor."x"]\ncodec = "colunmar"\n')
        with pytest.raises(ValueError) as exc:
            CompressorRegistry.load(project_root=tmp_path)
        assert str(f) in str(exc.value) and "colunmar" in str(exc.value)

    def test_malformed_toml_fails_at_load(self, tmp_path):
        d = tmp_path / ".parrot"; d.mkdir()
        (d / "compressors.toml").write_text("[compressor.\n")
        with pytest.raises(Exception):
            CompressorRegistry.load(project_root=tmp_path)

    def test_shadowing_builtin_warns(self, compressors_toml, caplog):
        CompressorRegistry.load(project_root=compressors_toml)
        assert any("shadow" in r.message.lower() for r in caplog.records)

    def test_registry_immutable_after_load(self, tmp_path):
        reg = CompressorRegistry.load(project_root=tmp_path)
        with pytest.raises(Exception):
            reg.entries["*"] = None


def test_third_party_package_manifest_no_core_edits(monkeypatch, tmp_path):
    """G6: a third-party package declares a compressor via its own TOML."""
    # point the discovery source list at tests/.../fixture_pkg and assert the
    # entry it declares is resolvable with zero edits to parrot core files.
    ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Data Models, §3 Module 1, §5 acceptance G6).
2. **Check dependencies** — TASK-1947 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-check `discovery.py` line anchors.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-07-27
**Notes**: Implemented `CompressorEntry`/`CompressorConfig` Pydantic schema
(`config.py`), immutable multi-source `CompressorRegistry` (`registry.py`,
project `.parrot/compressors.toml` > third-party package manifests via
`thirdparty_sources` > core defaults `compressors.toml`), match precedence
exact > glob (longest-first) > `"*"`, load-time codec validation with
file-path + entry-key error messages, shadow-warning logging, and a
third-party `fixture_pkg/` proving G6 with zero core edits. Exported
`CompressorRegistry`/`CompressorEntry`/`CompressorConfig` from
`compression/__init__.py`; added `"parrot.tools.compression" = ["*.toml"]`
to `pyproject.toml` package-data so the default manifest ships in the wheel.
Since the real `json_compact` codec is TASK-1949's deliverable, tests
register a stand-in codec under that name (autouse fixture) so the core
manifest validates without depending on TASK-1949. All 18 tests pass
(10 from TASK-1947 + 8 new); `ruff check` clean; `pyproject.toml` re-parses
as valid TOML after the edit.

**Deviations from spec**: none
