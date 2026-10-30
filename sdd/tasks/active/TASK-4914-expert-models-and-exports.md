# TASK-4914: Expert models, errors and package export map

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models and §3 Module 1. Every other FEAT-778 task imports the Pydantic models defined here
(`ExpertManifest`, `KnowledgeLayer`, `KnowledgeContext`, `ExpertBundle`, `RuleSet`) and the error classes.
This task also creates the three package `__init__.py` files of `parrot.experts` with a **pre-declared lazy
export map** covering every public name the feature will add, so no later task ever edits an `__init__.py`
(spec §Worktree Strategy: "let M1 pre-declare the export list"). Shared test fixtures land in a conftest here
for the same reason.

---

## Scope

- Create `parrot/experts/models.py` with the enums, models, manifest validators and the error hierarchy.
- Create `parrot/experts/__init__.py`, `parrot/experts/knowledge/__init__.py` and
  `parrot/experts/knowledge/sources/__init__.py`, each a lazy `__getattr__` export map (names → module).
- Create `packages/ai-parrot/tests/experts/__init__.py` (empty) and `conftest.py` with the `expert_bundle` and
  `governance_dir` fixtures from spec §4 Test Data.
- Write `test_models.py`: manifest invariants (AC2), `KnowledgeContext.inline_text` / `retrieval_handles`.

**NOT in scope**: parsing files from disk (TASK TASK-4925), rules grammar (TASK-4915), any resolver logic (TASK-4919).
Do not import anything from `parrot.bots`, `parrot.registry` or `parrot_tools` in `models.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/__init__.py` | CREATE | Lazy export map for the whole feature |
| `packages/ai-parrot/src/parrot/experts/models.py` | CREATE | Enums, models, validators, errors |
| `packages/ai-parrot/src/parrot/experts/knowledge/__init__.py` | CREATE | Lazy export map for the resolver package |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/__init__.py` | CREATE | Lazy export map for the source adapters |
| `packages/ai-parrot/tests/experts/__init__.py` | CREATE | Test package marker (repo tests use packages) |
| `packages/ai-parrot/tests/experts/conftest.py` | CREATE | `expert_bundle`, `governance_dir` fixtures |
| `packages/ai-parrot/tests/experts/test_models.py` | CREATE | Unit tests for this task |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator   # pydantic v2 (core dependency)
from parrot.tools.spawn import SpawnSubAgentTool   # verified: parrot/tools/spawn.py:88 — tests only, to assert the name
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/spawn.py:88-128
class SpawnSubAgentTool(AbstractTool):
    name: str = "spawn_sub_agent"   # line 114 — SPAWN_TOOL_NAME must equal this literal
```

### Does NOT Exist
- ~~`parrot.experts`~~ — the package does not exist yet; this task creates it (verified: `ls packages/ai-parrot/src/parrot/experts` fails at `9d5a6476b8`).
- ~~`AgentKind.EXPERT`~~ — no new `AgentKind` (spec Non-Goals, AC16).
- ~~`tools_deny` / `disallowed_tools`~~ — no deny-list field anywhere; the manifest has `tools_allow` only.
- ~~`ExpertManifest.model`~~ — a manifest never names a model; `tier` is an enum.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/conftest.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/spawn.py#SpawnSubAgentTool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2 only; `ExpertManifest` and `KnowledgeSourceSpec` use `ConfigDict(extra="forbid")`.
- `models.py` must import with nothing but pydantic and the stdlib, so the manifest can be validated without the
  LLM stack (spec M1 "Depends on").
- The lazy export maps must list names that later tasks create; importing `parrot.experts` must NOT import those
  modules eagerly (they do not exist until their task lands, and some pull the bot stack).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:1-12` — the repo's lazy `_EXPORTS` + `__getattr__` pattern to copy.

---

## Implementation Blueprint

### Steps (in order)
1. Write `models.py` — *why*: every other module types against these models.
2. Write the three `__init__.py` export maps — *why*: later tasks then never touch an `__init__.py`, so no two
   parallel tasks edit the same file.
3. Write the conftest fixtures and `test_models.py`, run them.

### `packages/ai-parrot/src/parrot/experts/models.py` (CREATE)
```python
"""Domain-expert data models, manifest invariants and errors (FEAT-778, spec §2/M1)."""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPAWN_TOOL_NAME: Final[str] = "spawn_sub_agent"  # verified: parrot/tools/spawn.py:114
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

LayerName = Literal["rules", "tier1_shared", "tier1_expert", "tier2_shared", "tier2_expert", "adr", "stage_input", "retrieval"]


class ExpertError(Exception):
    """Base class for every domain-expert error."""


class ExpertBundleError(ExpertError):
    """A bundle directory is malformed (manifest, identity, `$` placeholder…)."""


class DuplicateExpertError(ExpertError):
    """Two bundles in the same root declare the same name."""


class ExpertKnowledgeError(ExpertError):
    """A knowledge source cannot be resolved (e.g. empty or unwritable wiki namespace)."""


class ExpertPolicyError(ExpertError):
    """A policy invariant would be violated (e.g. spawn tool in the allowlist)."""


class ExpertCapabilityError(ExpertError):
    """A tool needs a capability the manifest does not declare."""


class RuleSyntaxError(ExpertError):
    """A governance rules file contains a line outside the ALWAYS/NEVER grammar."""


class KnowledgeMode(str, Enum):
    INLINE = "inline"
    RETRIEVAL = "retrieval"


class KnowledgeSourceKind(str, Enum):
    BUNDLED = "bundled"
    WORKSPACE = "workspace"
    WIKI = "wiki"
    BOOKSTORE = "bookstore"
    GRAPHINDEX = "graphindex"
    ADR = "adr"
    KB = "kb"


class ExpertTier(str, Enum):
    JUDGMENT = "judgment"
    BALANCED = "balanced"
    TEMPLATED = "templated"
```
**Why this shape**: enum and error names are fixed by the spec and imported by every later task — do not rename.
Errors live here (not in a separate module) because the spec gives M1 no `errors.py`.

### `packages/ai-parrot/src/parrot/experts/models.py` (CREATE, continued — append below the block above)
```python
class KnowledgeSourceSpec(BaseModel):
    """One `knowledge:` entry of expert.yaml."""
    model_config = ConfigDict(extra="forbid")
    source: KnowledgeSourceKind
    mode: KnowledgeMode
    scope: dict[str, list[str]] = Field(default_factory=dict)
    filter: dict[str, list[str]] = Field(default_factory=dict)


class ExpertManifest(BaseModel):
    """Machine-read expert.yaml."""
    model_config = ConfigDict(extra="forbid")
    name: str
    display_name: str
    description: str
    tier: ExpertTier = ExpertTier.BALANCED
    toolkits: list[str] = Field(default_factory=list)
    tools_allow: list[str] = Field(default_factory=list)
    knowledge: list[KnowledgeSourceSpec]
    capabilities: list[Literal["validate", "write", "review"]] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    global_only: bool = False

    @field_validator("name")
    @classmethod
    def _kebab(cls, v: str) -> str:
        """kebab-case, 2-64 chars."""
        # FILL IN: raise ValueError unless 2 <= len(v) <= 64 and _KEBAB.match(v) — bounded by AC2
        return v

    @model_validator(mode="after")
    def _invariants(self) -> "ExpertManifest":
        """No wiki source, or SPAWN_TOOL_NAME in toolkits/tools_allow -> ValueError (AC2)."""
        # FILL IN: the two checks; the tier check is done by the enum already — bounded by AC2
        return self

```

### `packages/ai-parrot/src/parrot/experts/models.py` (CREATE, continued — append below the block above)
```python
class RuleSet(BaseModel):
    layer: Literal["org", "team", "project", "expert", "stage"]
    source: Path
    revision: str
    mandated: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class KnowledgeLayer(BaseModel):
    layer: LayerName
    source: str
    mode: KnowledgeMode
    revision: str
    tokens: int = 0
    content: str | None = None
    handle: dict[str, Any] | None = None


class KnowledgeContext(BaseModel):
    expert: str
    stage: str | None = None
    budget_tokens: int
    layers: list[KnowledgeLayer] = Field(default_factory=list)
    trimmed: list[KnowledgeLayer] = Field(default_factory=list)

    def inline_text(self, layer: str) -> str:
        """Concatenate `content` of INLINE layers named `layer` ('' when none), joined by a blank line."""
        # FILL IN: keep layer order; skip None content
        return ""

    def retrieval_handles(self) -> list[KnowledgeLayer]:
        """Layers whose mode is RETRIEVAL, in order."""
        return [layer for layer in self.layers if layer.mode is KnowledgeMode.RETRIEVAL]


class ExpertBundle(BaseModel):
    manifest: ExpertManifest
    root: Path
    identity_dir: Path
    persona_doc: Path | None = None
    knowledge_files: list[Path] = Field(default_factory=list)
    rules: RuleSet | None = None
    adr_dir: Path | None = None
    tenant: str | None = None
    origin: Literal["bundled", "workspace"] = "workspace"
```
**Why**: field names, defaults and the `Literal` layer names are the spec §2 contract; `rules` is `Optional`
because `rules/governance.md` is optional (§8 Q8, AC25).

### `packages/ai-parrot/src/parrot/experts/__init__.py` (CREATE)
```python
"""Domain experts: declarative bundles, knowledge resolver and governance (FEAT-778)."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    **{name: "parrot.experts.models" for name in (
        "SPAWN_TOOL_NAME", "ExpertError", "ExpertBundleError", "DuplicateExpertError", "ExpertKnowledgeError",
        "ExpertPolicyError", "ExpertCapabilityError", "RuleSyntaxError", "KnowledgeMode", "KnowledgeSourceKind",
        "ExpertTier", "KnowledgeSourceSpec", "ExpertManifest", "RuleSet", "KnowledgeLayer", "KnowledgeContext",
        "ExpertBundle",
    )},
    **{name: "parrot.experts.rules" for name in ("parse_rules", "resolve_chain", "rules_to_layer")},
    **{name: "parrot.experts.policy" for name in (
        "model_config_for", "effective_toolkits", "effective_allowlist", "expert_policy_rules")},
    "KnowledgeResolver": "parrot.experts.knowledge.resolver",
    "knowledge_budget": "parrot.experts.knowledge.budget",
    "ExpertAgent": "parrot.experts.agent",
    "activate_expert": "parrot.experts.activation",
    "parse_expert_bundle": "parrot.experts.loader",
    "discover_expert_bundles": "parrot.experts.loader",
    "ExpertView": "parrot.experts.view",
    "ExpertRegistry": "parrot.experts.registry",
    "load_experts": "parrot.experts.bootstrap",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import the owning module on first access (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'parrot.experts' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)
```
**Why**: later modules (agent, registry, bootstrap) import the bot stack; eager imports here would make
`import parrot.experts.models` pay for it and would break while those modules do not exist yet.

### `packages/ai-parrot/src/parrot/experts/knowledge/__init__.py` (CREATE)
```python
"""Knowledge resolution for domain experts (FEAT-778 M4–M6)."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "KnowledgeResolver": "parrot.experts.knowledge.resolver",
    "LAYER_ORDER": "parrot.experts.knowledge.resolver",
    "TRIM_ORDER": "parrot.experts.knowledge.resolver",
    "KNOWLEDGE_FRACTION": "parrot.experts.knowledge.budget",
    "knowledge_budget": "parrot.experts.knowledge.budget",
    "sha256_revision": "parrot.experts.knowledge.budget",
    "render_rules": "parrot.experts.knowledge.render",
    "render_knowledge": "parrot.experts.knowledge.render",
    "install_layers": "parrot.experts.knowledge.render",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import the owning module on first access (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'parrot.experts.knowledge' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)
```

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/__init__.py` (CREATE)
```python
"""Knowledge source adapters, one per KnowledgeSourceKind (FEAT-778 M5)."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "KnowledgeSource": "parrot.experts.knowledge.sources.base",
    "BundledSource": "parrot.experts.knowledge.sources.bundled",
    "WorkspaceSource": "parrot.experts.knowledge.sources.workspace",
    "ADRSource": "parrot.experts.knowledge.sources.adr",
    "WikiSource": "parrot.experts.knowledge.sources.wiki",
    "BookstoreSource": "parrot.experts.knowledge.sources.bookstore",
    "GraphIndexSource": "parrot.experts.knowledge.sources.graphindex",
    "LegacyKBSource": "parrot.experts.knowledge.sources.kb",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import the owning module on first access (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'parrot.experts.knowledge.sources' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)
```

### `packages/ai-parrot/tests/experts/conftest.py` (CREATE)
```python
"""Shared fixtures for FEAT-778 tests (spec §4 Test Data). Pure files — no network, no LLM."""
from __future__ import annotations

from pathlib import Path

import pytest

MANIFEST = """\
name: sample-expert
display_name: Sample Expert
description: Sample expert used by the FEAT-778 tests
tier: balanced
knowledge:
  - {source: wiki, mode: retrieval}
  - {source: bundled, mode: inline}
  - {source: adr, mode: inline, filter: {status: [accepted]}}
"""


@pytest.fixture
def expert_bundle(tmp_path: Path) -> Path:
    """AGENTS_DIR/experts/sample-expert with manifest, identity/{role,goal}.md, knowledge/method.md,
    rules/governance.md, persona.md and tenants/acme/knowledge/method.md. Returns the AGENTS_DIR root."""
    root = tmp_path / "experts" / "sample-expert"
    # FILL IN: write the files listed in the docstring; rules file content is exactly
    # "## Mandated\nALWAYS cite sources\n## Forbidden\nNEVER delegate\n" (spec §4 Test Data)
    return tmp_path


@pytest.fixture
def governance_dir(tmp_path: Path) -> Path:
    """AGENTS_DIR/governance/{org,team,project}.md, one ALWAYS + one NEVER each; org repeats a project rule."""
    # FILL IN: write the three files; return tmp_path (the AGENTS_DIR root)
    return tmp_path
```
**Why**: fixtures sit in a conftest owned by this task so later tasks reuse them without editing a shared file.

### FILL IN checklist
- [ ] `ExpertManifest._kebab` — length and regex check; bounded by AC2.
- [ ] `ExpertManifest._invariants` — wiki-required and spawn-forbidden checks; bounded by AC2.
- [ ] `KnowledgeContext.inline_text` — join order and None handling.
- [ ] conftest fixtures — exact file contents from spec §4 Test Data.

---

## Acceptance Criteria

- [ ] AC2 — a manifest without `source: wiki`, with `spawn_sub_agent` in `toolkits`/`tools_allow`, or with
      `tier: gpt-x` raises a Pydantic `ValidationError`.
- [ ] `import parrot.experts` and `import parrot.experts.models` do not import `parrot.experts.agent`,
      `parrot.experts.registry` or `parrot_tools` (test asserts via `sys.modules`; `import parrot` itself may load
      other packages, so assert only on these names).
- [ ] `parrot.experts.ExpertManifest` resolves through the lazy map; an unknown name raises `AttributeError`.
- [ ] `ruff check` passes on every created file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_models.py
import sys

import pytest
from pydantic import ValidationError

from parrot.experts.models import ExpertManifest, KnowledgeContext, KnowledgeLayer, KnowledgeMode, SPAWN_TOOL_NAME

BASE = {"name": "cve-analyst", "display_name": "CVE", "description": "d",
        "knowledge": [{"source": "wiki", "mode": "retrieval"}]}


def test_manifest_requires_wiki_source(): ...          # FILL IN: knowledge without wiki -> ValidationError
def test_manifest_rejects_spawn_tool(): ...            # FILL IN: toolkits=[SPAWN_TOOL_NAME] and tools_allow=[...] both raise
def test_manifest_tier_rejects_model_id(): ...         # FILL IN: tier="gpt-x" raises
def test_manifest_name_must_be_kebab(): ...            # FILL IN: "CVE_Analyst" raises, "cve-analyst" passes
def test_spawn_tool_name_matches_spawn_tool(): ...     # FILL IN: SpawnSubAgentTool.name == SPAWN_TOOL_NAME
def test_inline_text_and_retrieval_handles(): ...      # FILL IN
def test_models_import_is_light(): ...                 # FILL IN: "parrot.experts.agent"/"parrot.experts.registry" not in sys.modules after import
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4914 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
