"""Seed `.parrot/mcp-toolkits.yaml` from packaged toolkit templates (FEAT-556, spec §3 M1)."""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field

from parrot.mcp.toolkit_config import BUILTIN_TOOLKITS

logger = logging.getLogger(__name__)

TEMPLATE_PACKAGE: str = "parrot.mcp"
TEMPLATE_DIR: str = "_toolkit_templates"
REPO_ROOT_PLACEHOLDER: str = "{{repo_root}}"
_META_PREFIX: str = "# parrot:"


class ToolkitTemplate(BaseModel):
    """One packaged `.parrot/mcp-toolkits.yaml` section, ready to render."""

    name: str
    body: str
    requires_llm: bool = False
    summary: str = ""


class SeedResult(BaseModel):
    """Outcome of one seeding run."""

    created_file: bool = False
    added: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)


def available_templates() -> tuple[str, ...]:
    """Return the packaged template names (file stems), sorted."""
    template_dir = files(TEMPLATE_PACKAGE) / TEMPLATE_DIR
    if not template_dir.is_dir():
        return ()

    templates = []
    for resource in template_dir.iterdir():
        if resource.name.endswith(".yaml"):
            templates.append(resource.name[:-5])  # Remove .yaml extension

    return tuple(sorted(templates))


def load_template(name: str) -> ToolkitTemplate:
    """Read one packaged template.

    Raises:
        KeyError: no template named `name` ships with this wheel.
    """
    template_dir = files(TEMPLATE_PACKAGE) / TEMPLATE_DIR
    template_path = template_dir / f"{name}.yaml"

    if not template_path.is_file():
        raise KeyError(f"No template named {name!r} found in {template_dir}")

    content = template_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Parse metadata from header lines
    summary = ""
    requires_llm = False
    body_start = 0

    for i, line in enumerate(lines):
        if not line.startswith(_META_PREFIX):
            body_start = i
            break

        # Parse metadata
        meta_content = line[len(_META_PREFIX) :].strip()
        if meta_content.startswith("summary:"):
            summary = meta_content[8:].strip()  # Remove "summary:" prefix
        elif meta_content.startswith("requires_llm:"):
            requires_llm_str = meta_content[13:].strip()  # Remove "requires_llm:" prefix
            requires_llm = requires_llm_str.lower() == "true"

    # Extract body (remaining lines)
    body_lines = lines[body_start:]
    body = "\n".join(body_lines)

    return ToolkitTemplate(name=name, body=body, requires_llm=requires_llm, summary=summary)


def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:
    """Create/extend `<root>/.parrot/mcp-toolkits.yaml` with the named sections.

    Creates the file with a `toolkits:` root when absent; appends only sections
    whose key is not already present (an existing section is NEVER rewritten);
    renders `REPO_ROOT_PLACEHOLDER` as `root`. Re-loads the result with
    `load_toolkits_config(root)` and raises if what it just wrote does not parse.

    Returns:
        SeedResult naming what was created, added, skipped and unknown.

    Raises:
        ValueError: the existing file is malformed, or the rendered result fails
            to re-load.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config  # local: keeps import cost off module load

    root_path = Path(root)
    path = root_path / ".parrot" / "mcp-toolkits.yaml"
    result = SeedResult(created_file=not path.exists())

    # Resolve requested names against available templates, deduping while
    # preserving order — a caller passing "foo,foo" (e.g. an un-deduped
    # `--toolkits` value) must not queue "foo" twice, which would otherwise
    # write a literal duplicate `foo:` YAML key.
    available = set(available_templates())
    seen: set[str] = set()
    deduped_names: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped_names.append(name)
    result.unknown = [name for name in deduped_names if name not in available]
    valid_names = [name for name in deduped_names if name in available]

    # Determine already-present section keys
    existing_sections = set()
    if path.exists():
        try:
            config = load_toolkits_config(root_path)
            # Get sections that are actually declared in the file (not built-ins)
            if path.exists():
                existing_sections = set(config.toolkits.keys())
                # Remove built-in sections that aren't actually in the file
                for builtin_name in BUILTIN_TOOLKITS:
                    if builtin_name in existing_sections:
                        # Check if this section is actually in the file or just a built-in
                        # We need to check the raw file content
                        file_content = path.read_text(encoding="utf-8")
                        if f"{builtin_name}:" not in file_content:
                            existing_sections.discard(builtin_name)
        except ValueError:
            # If the file is malformed, we'll handle it when we try to re-load after writing
            pass

    # Ensure .parrot directory exists
    parrot_dir = root_path / ".parrot"
    parrot_dir.mkdir(exist_ok=True)

    # Check which sections need to be added
    sections_to_add = []
    for name in valid_names:
        if name in existing_sections:
            result.skipped.append(name)
        else:
            sections_to_add.append(name)

    # If file doesn't exist or doesn't have toolkits root, create/add it
    needs_toolkits_root = not path.exists()
    needs_leading_newline = False
    if path.exists():
        content = path.read_text(encoding="utf-8")
        needs_toolkits_root = "toolkits:" not in content
        # A hand-edited file missing a trailing newline would otherwise have
        # the first appended section's key concatenated onto its last line
        # (e.g. "enabled: true  bounded-source:") before re-load validation
        # even runs — corrupting the file with no rollback on failure.
        needs_leading_newline = bool(content) and not content.endswith("\n")

    # Write/append sections
    if sections_to_add:
        with open(path, "a" if path.exists() else "w", encoding="utf-8") as f:
            if needs_toolkits_root:
                f.write("toolkits:\n")
            elif needs_leading_newline:
                f.write("\n")

            for name in sections_to_add:
                template = load_template(name)
                rendered_body = template.body.replace(REPO_ROOT_PLACEHOLDER, str(root))
                f.write(rendered_body)
                # Ensure exactly one trailing newline
                if not rendered_body.endswith("\n"):
                    f.write("\n")
                result.added.append(name)

    # Re-load with load_toolkits_config(root) and raise ValueError if seeded names are not all present
    if result.added:
        try:
            config = load_toolkits_config(root_path)
            missing = set(result.added) - set(config.toolkits.keys())
            if missing:
                raise ValueError(f"Failed to load seeded sections {missing} from {path}")
        except Exception as e:
            raise ValueError(f"Failed to re-load seeded config from {path}: {e}") from e

    if result.added or result.skipped:
        logger.info("seeded %s: added=%s skipped=%s", path, result.added, result.skipped)
    return result
