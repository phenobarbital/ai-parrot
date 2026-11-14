"""Tests for the procedure producers (FEAT-891)."""

from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure.producers import load_manifest, manifest_specs, skill_spec, skill_specs
from parrot.skills.models import SkillDefinition, SkillSource


def _write_manifest(root: Path, name: str, text: str) -> Path:
    """Write sdd/procedures/<name> under root and return its path."""
    manifest_dir = root / "sdd" / "procedures"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def _skill(tmp_path: Path, **overrides: object) -> SkillDefinition:
    """Build a minimally valid skill definition for producer tests."""
    defaults: dict[str, object] = {
        "name": "review",
        "description": "Review a change.",
        "triggers": ["review"],
        "template_body": "Review the supplied change.",
        "token_count": 1,
        "file_path": tmp_path / "review.md",
    }
    defaults.update(overrides)
    return SkillDefinition.model_validate(defaults)


def test_manifest_merge_prefix_exclude(tmp_path: Path) -> None:
    """Ids and edge targets are prefixed; an overlay `exclude` removes a node; a duplicate id raises."""
    base = _write_manifest(
        tmp_path,
        "01-base.yaml",
        """graph: sdd
procedures:
  - id: a
    title: A
    kind: command
  - id: b
    title: B
    kind: command
    requires_procedures: [a]
    next: [a]
""",
    )
    overlay = _write_manifest(
        tmp_path,
        "02-overlay.yaml",
        """graph: sdd
exclude: [a]
procedures:
  - id: c
    title: C
    kind: command
""",
    )

    specs, sources = manifest_specs(tmp_path)

    assert [spec.id for spec in specs] == ["sdd:b", "sdd:c"]
    assert specs[0].requires_procedures == ["sdd:a"]
    assert specs[0].next == ["sdd:a"]
    assert sources == [base, overlay]

    duplicate = _write_manifest(
        tmp_path,
        "03-duplicate.yaml",
        """graph: sdd
procedures:
  - id: b
    title: Duplicate B
    kind: command
""",
    )
    with pytest.raises(ValueError, match=r"01-base\.yaml.*03-duplicate\.yaml"):
        manifest_specs(tmp_path)
    assert duplicate.exists()


def test_manifest_dir_absent(tmp_path: Path) -> None:
    """No sdd/procedures directory yields no specs and no sources."""
    assert manifest_specs(tmp_path) == ([], [])


def test_manifest_schema_error_names_file(tmp_path: Path) -> None:
    """An unknown key raises ValueError naming the manifest file."""
    path = _write_manifest(tmp_path, "bad.yaml", "graph: sdd\nunknown: value\n")

    with pytest.raises(ValueError, match=r"sdd/procedures/bad\.yaml"):
        load_manifest(path, root=tmp_path)


def test_skill_without_procedure_returns_none(tmp_path: Path) -> None:
    """A skill with procedure=None is not a node."""
    assert skill_spec(_skill(tmp_path, procedure=None), root=tmp_path) is None


def test_learned_skill_never_mandatory(tmp_path: Path) -> None:
    """A learned skill's node is advisory with confirm false, whatever its frontmatter says."""
    spec = skill_spec(
        _skill(
            tmp_path,
            source=SkillSource.LEARNED,
            procedure={"mode": "mandatory", "confirm": True},
        ),
        root=tmp_path,
    )

    assert spec is not None
    assert spec.mode == "advisory"
    assert spec.confirm is False


def test_skill_spec_fields(tmp_path: Path) -> None:
    """An authored skill maps to id skill:<name>, kind skill, body = template_body."""
    skill = _skill(tmp_path, procedure={"intents": ["review_change"]})

    spec = skill_spec(skill, root=tmp_path)

    assert spec is not None
    assert spec.id == "skill:review"
    assert spec.kind == "skill"
    assert spec.body == skill.template_body
    assert spec.title == skill.description
    assert spec.origin_path == "review.md"

    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    skill_file = skill_dir / "discoverable.md"
    skill_file.write_text(
        """---
name: discoverable
description: Discoverable skill.
triggers: [discover]
procedure:
  intents: [discover]
---
Discover the procedure.
""",
        encoding="utf-8",
    )
    specs, files = skill_specs([skill_dir], root=tmp_path)
    assert [item.id for item in specs] == ["skill:discoverable"]
    assert files == [skill_file]
