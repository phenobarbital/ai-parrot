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
    resolved_path = path.resolve()
    if root is not None:
        try:
            return resolved_path.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return resolved_path.as_posix()


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
    files = sorted((root / MANIFEST_DIR).glob("*.yaml"), key=lambda path: path.name)
    merged: list[ProcedureSpec] = []
    excluded: set[str] = set()
    origins_by_id: dict[str, str] = {}

    for path in files:
        manifest = load_manifest(path, root=root)

        def prefixed(value: str, graph: str = manifest.graph) -> str:
            """Add the manifest graph to an unqualified procedure id."""
            return value if ":" in value else f"{graph}:{value}"

        excluded.update(prefixed(procedure_id) for procedure_id in manifest.exclude)
        for raw_spec in manifest.procedures:
            spec = raw_spec.model_copy(deep=True)
            spec.id = prefixed(spec.id)
            for field_name in _PREFIXED_FIELDS:
                setattr(spec, field_name, [prefixed(target) for target in getattr(spec, field_name)])

            previous_origin = origins_by_id.get(spec.id)
            if previous_origin is not None:
                raise ValueError(f"duplicate procedure id '{spec.id}' in {previous_origin} and {spec.origin_path}")
            origins_by_id[spec.id] = spec.origin_path
            merged.append(spec)

    return [spec for spec in merged if spec.id not in excluded], files


def skill_spec(skill: SkillDefinition, *, root: Path | None = None) -> ProcedureSpec | None:
    """Return the skill's node (id 'skill:<name>', kind 'skill', body = template_body), or None
    when ``skill.procedure`` is None. Source 'learned' forces mode 'advisory' and confirm False.
    """
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
    from parrot.skills.parsers import discover_skills_in_dir

    specs: list[ProcedureSpec] = []
    files: list[Path] = []
    origins_by_id: dict[str, Path] = {}
    for directory in directories:
        for skill in discover_skills_in_dir(directory, logger=_LOGGER):
            spec = skill_spec(skill, root=root)
            if spec is None:
                continue
            previous_path = origins_by_id.get(spec.id)
            if previous_path is not None:
                raise ValueError(f"duplicate procedure id '{spec.id}' in {previous_path} and {skill.file_path}")
            origins_by_id[spec.id] = skill.file_path
            specs.append(spec)
            files.append(skill.file_path)
    return specs, files
