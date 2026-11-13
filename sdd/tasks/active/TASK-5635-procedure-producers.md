# TASK-5635: Manifest and skill producers

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5633, TASK-5634
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and §2 "One model, two producers". The manifest producer reads
`sdd/procedures/*.yaml`; the skill producer turns a skill's optional `procedure` mapping into a
node. Both return `ProcedureSpec` records with ids namespaced by producer.

---

## Scope

- Implement `MANIFEST_DIR`, `load_manifest`, `manifest_specs`, `skill_spec`, `skill_specs` in
  `producers.py` with the signatures of spec §3 Module 2.
- Prefix ids: a manifest node `task` in graph `sdd` becomes `sdd:task`; a skill node is
  `skill:<name>`.
- Apply the overlay rules: files merged in name order, `exclude` removed after the merge, a
  duplicate id across files is an error naming both files.
- Force a learned skill's node to `mode="advisory"` and `confirm=False`.

**NOT in scope**: graph validation (TASK-5636), the SDD manifest itself (TASK-5647), any store.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/producers.py` | CREATE | The two producers |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_producers.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). `ProcedureSpec` / `ProcedureManifest` come from TASK-5633 and
> `SkillDefinition.procedure` from TASK-5634 — re-check both after they land.

### Verified Imports
```python
import yaml                                                        # PyYAML, existing dependency (spec §7)
from parrot.skills.models import SkillDefinition, SkillSource      # skills/models.py:68, :53
from parrot.skills.parsers import discover_skills_in_dir           # skills/parsers.py:181 — import it LAZILY (it loads tiktoken)
from parrot.knowledge.wiki.procedure.models import EDGE_FIELDS, ProcedureManifest, ProcedureSpec   # TASK-5633
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/models.py
class SkillSource(str, Enum): AUTHORED = "authored"; LEARNED = "learned"     # :53
class SkillDefinition(BaseModel):                                            # :68
    name: str; description: str                                              # :75-:76
    source: SkillSource = SkillSource.AUTHORED                               # :78
    template_body: str                                                       # :82
    file_path: Path                                                          # :84
    procedure: dict[str, Any] | None                                         # added by TASK-5634

# packages/ai-parrot/src/parrot/skills/parsers.py
def discover_skills_in_dir(directory: Path, logger=_LOGGER, exclude_names=()) -> List[SkillDefinition]: ...   # :181
```

### Does NOT Exist
- ~~`sdd/procedures/`~~ — the directory does not exist in the repo yet; `manifest_specs` must return
  `([], [])` when it is absent.
- ~~A manifest loader anywhere else in the repo~~ — `parrot.sdd.installer.load_manifest` is the
  *asset* manifest (`_assets/manifest.json`), unrelated; do not import it.
- ~~`SkillDefinition.mode` / `.intents`~~ — graph fields live only inside `skill.procedure`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/producers.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_producers.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/models.py#SkillDefinition",
    "sym:packages/ai-parrot/src/parrot/skills/models.py#SkillSource",
    "sym:packages/ai-parrot/src/parrot/skills/parsers.py#discover_skills_in_dir"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Id prefixing rule** (applies to manifests): the node `id`, every entry of `exclude`, and every
  target in `requires_procedures`, `next`, `alternative_to`, `escalates_to`, `on_failure` gets
  `"<graph>:"` prepended **when it contains no `:`**. A target that already has a prefix is a
  cross-graph reference and is kept. `applies_to` and `learned_from` are never prefixed.
- `origin_path` is the source file relative to `root`, POSIX form (absolute when not under `root`).
- Tests build manifests and skills in `tmp_path`; they must not read the repository's own files.
- Fixtures are local to the test file (no `conftest.py`).

---

## Implementation Blueprint

### Steps (in order)
1. Write `load_manifest` — *why*: one file, one schema error message naming it.
2. Write `manifest_specs` on top of it — *why*: merge, prefix, exclude and duplicate detection are
   properties of the set of files.
3. Write `skill_spec` / `skill_specs` — *why*: the second producer of the same model.
4. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/producers.py` (CREATE)
```python
"""Producers of ProcedureSpec records: SDD manifests and skill frontmatter (FEAT-891)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import ValidationError

from parrot.knowledge.wiki.procedure.models import ProcedureManifest, ProcedureSpec
from parrot.skills.models import SkillDefinition, SkillSource

MANIFEST_DIR = Path("sdd") / "procedures"
_PREFIXED_FIELDS = ("requires_procedures", "next", "alternative_to", "escalates_to", "on_failure")
_LOGGER = logging.getLogger(__name__)


def _relative(path: Path, root: Path | None) -> str:
    """POSIX path of ``path`` relative to ``root`` when it is inside it, else absolute."""
    # FILL IN: try path.resolve().relative_to(root.resolve()).as_posix(); fall back to path.as_posix()


def load_manifest(path: Path, *, root: Path) -> ProcedureManifest:
    """Parse one YAML manifest; raise ValueError naming the file on a schema error."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifest = ProcedureManifest.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"{_relative(path, root)}: invalid procedure manifest: {exc}") from exc
    for spec in manifest.procedures:
        spec.origin_path = _relative(path, root)
    return manifest


def manifest_specs(root: Path) -> tuple[list[ProcedureSpec], list[Path]]:
    """Merge every sdd/procedures/*.yaml under root (sorted by name); return (specs, source files).

    Ids get the manifest's graph prefix; every ``exclude`` id is removed after the merge; a
    duplicate id across files raises ValueError naming both files.
    """
    files = sorted((root / MANIFEST_DIR).glob("*.yaml"))
    # FILL IN: for each file load_manifest(); apply the id prefixing rule (Implementation Notes) to a
    # copy of each spec; detect a duplicate id (ValueError naming both origin_path values); collect
    # the prefixed `exclude` ids of every manifest; return ([spec for spec in merged if spec.id not in
    # excluded], files). No directory -> ([], []).


def skill_spec(skill: SkillDefinition, *, root: Path | None = None) -> ProcedureSpec | None:
    """Return the skill's node (id 'skill:<name>', kind 'skill', body = template_body), or None
    when ``skill.procedure`` is None. Source 'learned' forces mode 'advisory' and confirm False."""
    if skill.procedure is None:
        return None
    data = {
        "title": skill.description,
        **skill.procedure,
        "id": f"skill:{skill.name}",
        "kind": "skill",
        "body": skill.template_body,
        "source": skill.source.value,
        "origin_path": _relative(skill.file_path, root),
    }
    if skill.source is SkillSource.LEARNED:
        data.update(mode="advisory", confirm=False)
    try:
        return ProcedureSpec.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"{data['origin_path']}: invalid 'procedure' frontmatter: {exc}") from exc


def skill_specs(directories: Sequence[Path], *, root: Path | None = None) -> tuple[list[ProcedureSpec], list[Path]]:
    """skill_spec over discover_skills_in_dir for each directory; return (specs, skill files)."""
    from parrot.skills.parsers import discover_skills_in_dir  # lazy: it loads the tokenizer module

    # FILL IN: iterate directories in order; keep (spec, skill.file_path) for non-None specs;
    # a duplicate 'skill:<name>' id raises ValueError naming both files.
```
**Why this shape**: signatures are fixed by spec §3 M2. Prefixing lives in `manifest_specs`, not in
`load_manifest`, so a single manifest can still be inspected as written. A learned skill is
downgraded here (never an error) because spec §2 says the producer forces it; the validator
(TASK-5636) is the second line for hand-built specs.

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_producers.py` (CREATE)
```python
"""Tests for the procedure producers (FEAT-891)."""

from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure.producers import load_manifest, manifest_specs, skill_spec, skill_specs
from parrot.skills.models import SkillDefinition, SkillSource


def _write_manifest(root: Path, name: str, text: str) -> Path:
    """Write sdd/procedures/<name> under root and return its path."""
    # FILL IN


def test_manifest_merge_prefix_exclude(tmp_path: Path) -> None:
    """Ids and edge targets are prefixed; an overlay `exclude` removes a node; a duplicate id raises."""
    # FILL IN: base file with a, b (b requires a, next: [a]); overlay with c and exclude: [a];
    # assert ids == ["sdd:b", "sdd:c"], b.requires_procedures == ["sdd:a"], sources == both files;
    # then a third file re-declaring b -> pytest.raises(ValueError) naming both file names.


def test_manifest_dir_absent(tmp_path: Path) -> None:
    """No sdd/procedures directory yields no specs and no sources."""
    assert manifest_specs(tmp_path) == ([], [])


def test_manifest_schema_error_names_file(tmp_path: Path) -> None:
    """An unknown key raises ValueError naming the manifest file."""
    # FILL IN


def test_skill_without_procedure_returns_none(tmp_path: Path) -> None:
    """A skill with procedure=None is not a node."""
    # FILL IN: build SkillDefinition(...) directly; skill_spec(skill) is None


def test_learned_skill_never_mandatory(tmp_path: Path) -> None:
    """A learned skill's node is advisory with confirm false, whatever its frontmatter says."""
    # FILL IN: source=SkillSource.LEARNED, procedure={"mode": "mandatory", "confirm": True}


def test_skill_spec_fields(tmp_path: Path) -> None:
    """An authored skill maps to id skill:<name>, kind skill, body = template_body."""
    # FILL IN
```

### FILL IN checklist
- [ ] `producers.py::_relative`, `manifest_specs`, `skill_specs` — bounded by the docstrings and the prefixing rule
- [ ] `test_producers.py` — six test bodies

---

## Acceptance Criteria

- [ ] `manifest_specs` prefixes ids and in-graph edge targets, applies `exclude`, and raises on a duplicate id naming both files.
- [ ] `skill_spec` returns `None` for a skill without `procedure`; a learned skill is always advisory with `confirm` false.
- [ ] A schema error raises `ValueError` whose message contains the file path.
- [ ] `producers.py` imports `parrot.skills.parsers` only inside `skill_specs`.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_producers.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5633 and TASK-5634 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`; never change a signature the blueprint fixes.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5635 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
