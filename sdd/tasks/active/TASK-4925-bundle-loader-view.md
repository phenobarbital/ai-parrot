# TASK-4925: Bundle loader, `ExpertView` overlay and reserved tenant names

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4914, TASK-4915
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (loader + view part), G1, U2, §8 Q7(a), Q8, codex S1/S3. Parse a bundle directory into an
`ExpertBundle`, discover bundles non-recursively (mirror of `discover_skills_in_dir`), and overlay bundle sets
with `ExpertView` (SkillView semantics: the narrower set shadows by name unless the wider bundle is
`global_only`). The view is applied twice by the registry (TASK-4926): bundled → workspace, then → tenant.

This task also creates the package marker `parrot/experts/bundled/__init__.py`, because the loader resolves
`BUNDLED_EXPERTS_DIR` through `importlib.resources.files("parrot.experts.bundled")` at import time. The bundle
**contents** arrive in TASK-4930/TASK-4931; the wheel package-data entry in TASK-4932.

---

## Scope

- Create `experts/loader.py`: `EXPERTS_DIRNAME`, `MANIFEST_FILENAME`, `BUNDLED_EXPERTS_DIR`, `parse_expert_bundle`,
  `discover_expert_bundles`.
- Create `experts/view.py`: `ExpertView`.
- Create `experts/bundled/__init__.py` (docstring only).
- Add `"experts"`, `"knowledge"`, `"governance"` to `RESERVED_TENANT_NAMES` in `skills/tenancy.py`.
- Write `test_loader_view.py`.

**NOT in scope**: building agents or registering anything (TASK-4926); any bundle content (TASK-4930/TASK-4931).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/loader.py` | CREATE | Parse + discover |
| `packages/ai-parrot/src/parrot/experts/view.py` | CREATE | Overlay with shadowing report |
| `packages/ai-parrot/src/parrot/experts/bundled/__init__.py` | CREATE | Package marker for shipped bundles |
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | MODIFY | Three reserved names |
| `packages/ai-parrot/tests/experts/test_loader_view.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.identity import load_identity, IDENTITY_FILES   # verified: bots/prompts/identity.py:51,27
from parrot.skills.tenancy import RESERVED_TENANT_NAMES, TENANTS_DIRNAME, validate_tenant_id   # verified: tenancy.py:23,38,42
from parrot.utils.paths import secure_path                               # verified: imported by skills/tenancy.py:16
from parrot.experts.models import ExpertBundle, ExpertBundleError, ExpertManifest   # TASK-4914
from parrot.experts.rules import parse_rules                             # TASK-4915
import yaml                                                              # pyyaml — already a dependency
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/identity.py
IDENTITY_FILES: tuple[str, ...] = ("role", "goal", "capabilities", "backstory", "rationale")   # lines 27-29
def load_identity(directory: Union[str, Path], *, escape_placeholders: bool = False, ...)      # line 51
# packages/ai-parrot/src/parrot/skills/tenancy.py
RESERVED_TENANT_NAMES: frozenset[str] = frozenset({"skills", "learned", "tenants", "prompts", "queries", "kb",
    "documents", "flows", "routes", "_drafts", "_shared"})   # lines 23-37; "_shared" at line 35
def validate_tenant_id(value: str) -> str                    # line 42 — raises ValueError when reserved
class SkillView                                              # line 164 — semantics to mirror (not subclassed)
# packages/ai-parrot/src/parrot/skills/parsers.py
def discover_skills_in_dir(directory: Path, logger=_LOGGER, exclude_names=()) -> List[SkillDefinition]   # line 181 — pattern
```

### Does NOT Exist
- ~~`parrot.experts.bundled`~~ — created here (marker only).
- ~~`SkillView` reuse for experts~~ — experts are not skills; copy the semantics, do not subclass (spec §7).
- ~~an identity parser for `persona.md`~~ — `persona.md` is only recorded as `persona_doc`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/loader.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/view.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/bundled/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/skills/tenancy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/experts/test_loader_view.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/prompts/identity.py#load_identity",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#RESERVED_TENANT_NAMES",
    "sym:packages/ai-parrot/src/parrot/skills/tenancy.py#validate_tenant_id",
    "sym:packages/ai-parrot/src/parrot/skills/parsers.py#discover_skills_in_dir"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `parse_expert_bundle` raises `ExpertBundleError` when: `expert.yaml` missing or invalid; `manifest.name !=
  bundle_dir.name`; `identity/` has no readable field; any identity file contains a `$` placeholder (S3 — the
  identity layer is template-substituted). A missing `rules/governance.md` is NOT an error: `rules=None` plus
  exactly one WARNING `"expert <name>: no rules/governance.md — org/team/project rules still apply"` (AC25).
- `discover_expert_bundles`: sorted, non-recursive; a subdir without `expert.yaml` (or starting with `.` or `_`)
  is ignored silently; a malformed bundle is logged at WARNING and skipped — the function never raises for one
  bad bundle. It returns `(bundles, skipped)` where `skipped` is `[{"path", "reason"}]` for `report()`.
- `ExpertView.shadowing` labels: `"workspace"` or `f"tenant:{id}"`.

---

## Implementation Blueprint

### Steps (in order)
1. Reserved names (one-line edit) — *why*: `validate_tenant_id` must reject the new top-level dir names (AC13).
2. `bundled/__init__.py`, then `loader.py`, then `view.py`.

### `packages/ai-parrot/src/parrot/skills/tenancy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "_shared",' packages/ai-parrot/src/parrot/skills/tenancy.py)
# AFTER — insert below `        "_shared",` (verified: tenancy.py:35)
        "experts",  # FEAT-778: AGENTS_DIR/experts bundles
        "knowledge",  # FEAT-778: AGENTS_DIR/knowledge Tier-2 shared knowledge
        "governance",  # FEAT-778: AGENTS_DIR/governance rules chain
```

### `packages/ai-parrot/src/parrot/experts/bundled/__init__.py` (CREATE)
```python
"""Package-bundled domain experts shipped in the ai-parrot wheel (FEAT-778 §8 Q7). Data only."""
```

### `packages/ai-parrot/src/parrot/experts/loader.py` (CREATE)
```python
"""Discover and parse expert bundles (FEAT-778 M2)."""
from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from parrot.bots.prompts.identity import IDENTITY_FILES, load_identity
from parrot.experts.models import ExpertBundle, ExpertBundleError, ExpertManifest
from parrot.experts.rules import parse_rules

EXPERTS_DIRNAME: Final[str] = "experts"
MANIFEST_FILENAME: Final[str] = "expert.yaml"
BUNDLED_EXPERTS_DIR: Final[Path] = Path(str(importlib.resources.files("parrot.experts.bundled")))
_LOGGER = logging.getLogger(__name__)


def parse_expert_bundle(bundle_dir: Path, *, tenant: str | None = None,
                        origin: Literal["bundled", "workspace"] = "workspace") -> ExpertBundle:
    """Parse one bundle; ExpertBundleError on any invariant violation (see Key Constraints)."""
    manifest_path = bundle_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ExpertBundleError(f"{bundle_dir}: missing {MANIFEST_FILENAME}")
    try:
        manifest = ExpertManifest.model_validate(yaml.safe_load(manifest_path.read_text()) or {})
    except Exception as exc:  # pydantic.ValidationError, yaml.YAMLError
        raise ExpertBundleError(f"{manifest_path}: {exc}") from exc
    # FILL IN: name == dir; identity checks (load_identity + "$" scan over IDENTITY_FILES); knowledge files
    # (sorted knowledge/*.md); rules (parse_rules(..., layer="expert") or None + WARNING); persona/adr paths;
    # return ExpertBundle(..., tenant=tenant, origin=origin) — bounded by AC2, AC17, AC25
    raise NotImplementedError


def discover_expert_bundles(directory: Path, *, origin: Literal["bundled", "workspace"] = "workspace",
                            logger: logging.Logger = _LOGGER) -> tuple[list[ExpertBundle], list[dict[str, Any]]]:
    """Non-recursive, sorted; skip malformed bundles with a WARNING; return (bundles, skipped)."""
    bundles: list[ExpertBundle] = []
    skipped: list[dict[str, Any]] = []
    if not directory.is_dir():
        return bundles, skipped
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")) or not (entry / MANIFEST_FILENAME).is_file():
            continue
        try:
            bundles.append(parse_expert_bundle(entry, origin=origin))
        except ExpertBundleError as exc:
            logger.warning("Skipping expert bundle %s: %s", entry, exc)
            skipped.append({"path": str(entry), "reason": str(exc)})
    return bundles, skipped
```

### `packages/ai-parrot/src/parrot/experts/view.py` (CREATE)
```python
"""Name-based overlay of expert bundle sets with SkillView semantics (FEAT-778 M2)."""
from __future__ import annotations

import logging
from typing import Sequence

from parrot.experts.models import ExpertBundle

_LOGGER = logging.getLogger(__name__)


class ExpertView:
    """`overlay` shadows `base` by name unless the base bundle is global_only (then the overlay copy is dropped)."""

    def __init__(self, base: Sequence[ExpertBundle], overlay: Sequence[ExpertBundle], *, label: str,
                 logger: logging.Logger = _LOGGER) -> None:
        self.label = label
        self.logger = logger
        self._by_name: dict[str, ExpertBundle] = {b.manifest.name: b for b in base}
        self._shadowing: dict[str, str] = {}
        # FILL IN: for each overlay bundle: global_only base -> WARNING + drop; else replace and record
        # self._shadowing[name] = str(bundle.root) — bounded by AC7, AC22

    def resolve(self, name: str) -> ExpertBundle | None:
        return self._by_name.get(name)

    def bundles(self) -> list[ExpertBundle]:
        return [self._by_name[name] for name in sorted(self._by_name)]

    @property
    def shadowing(self) -> dict[str, str]:
        return dict(self._shadowing)
```

### FILL IN checklist
- [ ] `parse_expert_bundle` — all invariants; AC2, AC17, AC25.
- [ ] `ExpertView.__init__` — overlay loop; AC7, AC22.

---

## Acceptance Criteria

- [ ] AC1 (loader part) — malformed bundles are skipped with a warning; `name != dir` is a skip.
- [ ] AC13 — `validate_tenant_id("experts" | "knowledge" | "governance")` raises `ValueError`.
- [ ] AC17 (loader part) — an identity file containing `$role` makes the bundle fail with a clear error.
- [ ] AC25 (loader part) — no `rules/governance.md` → `rules is None` and exactly one WARNING.
- [ ] `BUNDLED_EXPERTS_DIR` resolves to the package directory.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_loader_view.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_loader_view.py — expert_bundle fixture
def test_discover_ignores_dirs_without_manifest(tmp_path): ...       # FILL IN
def test_bundle_name_must_match_dir(tmp_path): ...                   # FILL IN
def test_identity_dollar_placeholder_rejected(expert_bundle): ...    # FILL IN
def test_bundle_without_rules_loads_with_warning(expert_bundle, caplog): ...   # FILL IN
def test_tenant_shadows_global_unless_global_only(): ...             # FILL IN
def test_reserved_names_include_experts(): ...                       # FILL IN
def test_bundled_dir_resolves(): ...                                 # FILL IN
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4925 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
