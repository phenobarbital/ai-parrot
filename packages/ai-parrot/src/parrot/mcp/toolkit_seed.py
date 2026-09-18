"""Seed `.parrot/mcp-toolkits.yaml` from packaged toolkit templates (FEAT-556, spec §3 M1)."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any, Sequence

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TEMPLATE_PACKAGE: str = "parrot.mcp"
TEMPLATE_DIR: str = "_toolkit_templates"
REPO_ROOT_PLACEHOLDER: str = "{{repo_root}}"
_META_PREFIX: str = "# parrot:"
# Section-level keys whose absence is a valid state, not drift: `enabled` is an
# on/off switch that templates seed as `false` and configured sections omit.
_DRIFT_IGNORED_KEYS: frozenset[str] = frozenset({"enabled"})


class ToolkitTemplate(BaseModel):
    """One packaged `.parrot/mcp-toolkits.yaml` section, ready to render."""

    name: str
    body: str
    requires_llm: bool = False
    summary: str = ""
    requires_dist: tuple[str, ...] = ()


class SeedResult(BaseModel):
    """Outcome of one seeding run."""

    created_file: bool = False
    added: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    # Skipped section name -> dotted template keys the existing section lacks
    # (e.g. `kwargs.complexity`). Reported only; an existing section is never rewritten.
    drift: dict[str, list[str]] = Field(default_factory=dict)


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
    requires_dist: tuple[str, ...] = ()
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
        elif meta_content.startswith("requires_dist:"):
            raw = meta_content[len("requires_dist:") :].strip()
            requires_dist = tuple(part.strip() for part in raw.split(",") if part.strip())

    # Extract body (remaining lines)
    body_lines = lines[body_start:]
    body = "\n".join(body_lines)

    return ToolkitTemplate(
        name=name, body=body, requires_llm=requires_llm, summary=summary, requires_dist=requires_dist
    )


def _missing_keys(template: Any, existing: Any, prefix: str = "") -> list[str]:
    """Return dotted mapping keys present in `template` but absent from `existing`.

    Recurses into nested mappings only; lists and scalars are compared by
    presence of their key, never by value.

    Args:
        template: The parsed template section (or sub-mapping).
        existing: The parsed on-disk section (or sub-mapping).
        prefix: Dotted path of the current mapping, used to build key names.

    Returns:
        Dotted key paths missing from `existing`, in template order.
    """
    if not isinstance(template, dict) or not isinstance(existing, dict):
        return []
    missing: list[str] = []
    for key, value in template.items():
        path = f"{prefix}{key}"
        if key not in existing:
            missing.append(path)
        else:
            missing.extend(_missing_keys(value, existing[key], f"{path}."))
    return missing


def template_drift(root: Path, name: str) -> list[str]:
    """Report template keys an existing `.parrot/mcp-toolkits.yaml` section lacks.

    Sections are seeded once and never rewritten, so keys a template gains in a
    later release (e.g. `kwargs.complexity` for `sdd-coder`) never reach an
    already-seeded file. This surfaces them so the operator can copy them in.

    Args:
        root: Project root containing `.parrot/mcp-toolkits.yaml`.
        name: Template / section name.

    Returns:
        Dotted template keys missing from the on-disk section; empty when the
        section, the file or the template cannot be parsed.
    """
    path = Path(root) / ".parrot" / "mcp-toolkits.yaml"
    try:
        template = load_template(name)
        rendered = template.body.replace(REPO_ROOT_PLACEHOLDER, str(root))
        template_section = (yaml.safe_load(f"toolkits:\n{rendered}") or {}).get("toolkits", {}).get(name)
        existing_section = ((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("toolkits") or {}).get(name)
    except (KeyError, OSError, AttributeError, yaml.YAMLError) as exc:
        logger.debug("cannot compare section %s with its template: %s", name, exc)
        return []
    return [key for key in _missing_keys(template_section, existing_section) if key not in _DRIFT_IGNORED_KEYS]


def _config_path(root: Path) -> Path:
    """Return `<root>/.parrot/mcp-toolkits.yaml`."""
    return Path(root) / ".parrot" / "mcp-toolkits.yaml"


def _atomic_write(path: Path, text: str) -> None:
    """Replace `path` with `text` atomically.

    Writes a temp file in the SAME directory (os.replace is only atomic within a
    filesystem), flushes and fsyncs it, then renames over the target.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".mcp-toolkits.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def preflight_seed(root: Path, names: Sequence[str]) -> None:
    """Validate a seeding request BEFORE anything is written.

    Raises:
        ValueError: any name has no packaged template (all-or-nothing — the
            pre-FEAT-570 behavior seeded the valid names anyway), or an existing
            `.parrot/mcp-toolkits.yaml` cannot be parsed (the pre-FEAT-570
            behavior swallowed this and appended to the malformed file).
    """
    from parrot.mcp.toolkit_config import load_toolkits_config  # local: keeps import cost off module load

    available = set(available_templates())
    unknown = [name for name in dict.fromkeys(names) if name not in available]
    if unknown:
        raise ValueError(
            f"No packaged template for: {', '.join(sorted(unknown))}. " f"Available: {', '.join(available_templates())}"
        )
    path = _config_path(root)
    if path.exists():
        load_toolkits_config(Path(root))  # raises ValueError naming file+section


def _find_section_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return the [start, end) line span of section `name`, including its leading comments.

    A section header is `  <name>:` at two-space indent; the body runs until the
    next line at that same indent that is not a comment, or EOF. Returns None when
    the section is absent.
    """
    header_pattern = re.compile(rf"^  {re.escape(name)}:\s*$")
    header_index = None
    for index, line in enumerate(lines):
        if header_pattern.match(line):
            header_index = index
            break
    if header_index is None:
        return None

    # A comment line immediately preceding the header (same two-space indent,
    # no blank-line gap) belongs to this section.
    start = header_index
    while start > 0 and re.match(r"^  #", lines[start - 1]):
        start -= 1

    # The body runs until the next sibling line at the same two-space indent
    # (another section header, or a comment leading the next one).
    end = header_index + 1
    while end < len(lines) and not re.match(r"^  \S", lines[end]):
        end += 1

    return start, end


def set_section_enabled(root: Path, name: str, enabled: bool) -> bool:
    """Flip (or insert) `enabled:` for one section, preserving comments and formatting.

    Lexical edit + atomic replace — never `yaml.safe_dump` of a parsed model, which
    would discard every operator comment (no round-trip parser is declared).

    Returns:
        False when the section is absent; True when the file was rewritten.
    """
    path = _config_path(root)
    if not path.exists():
        return False

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    span = _find_section_span(lines, name)
    if span is None:
        return False
    start, end = span

    header_pattern = re.compile(rf"^  {re.escape(name)}:\s*$")
    header_index = next(index for index in range(start, end) if header_pattern.match(lines[index]))

    value = "true" if enabled else "false"
    enabled_pattern = re.compile(r"^(?P<indent>[ \t]+)enabled:\s*\S.*$")
    for index in range(header_index + 1, end):
        match = enabled_pattern.match(lines[index])
        if match:
            lines[index] = f"{match.group('indent')}enabled: {value}\n"
            break
    else:
        lines.insert(header_index + 1, f"    enabled: {value}\n")

    _atomic_write(path, "".join(lines))
    return True


def remove_section(root: Path, name: str) -> bool:
    """Delete one section and its leading comment block; atomic replace.

    Returns:
        False when the section is absent; True when the file was rewritten.
    """
    path = _config_path(root)
    if not path.exists():
        return False

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    span = _find_section_span(lines, name)
    if span is None:
        return False
    start, end = span

    del lines[start:end]

    # Collapse any run of blank lines the removal left behind into one.
    collapsed: list[str] = []
    for line in lines:
        if line.strip() == "" and collapsed and collapsed[-1].strip() == "":
            continue
        collapsed.append(line)

    _atomic_write(path, "".join(collapsed))
    return True


def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:
    """Create/extend `<root>/.parrot/mcp-toolkits.yaml` with the named sections.

    Creates the file with a `toolkits:` root when absent; appends only sections
    whose key is not already present (an existing section is NEVER rewritten,
    but template keys it lacks are reported in `SeedResult.drift`); renders
    `REPO_ROOT_PLACEHOLDER` as `root`. The whole request is validated by
    `preflight_seed` before anything is written, the new text is assembled in
    memory, and the file is replaced with one atomic write — a failure anywhere
    leaves the original file byte-identical. Re-loads the result with
    `load_toolkits_config(root)` and raises if what it just wrote does not parse.

    Returns:
        SeedResult naming what was created, added and skipped (`unknown` is
        always empty now — an unknown name fails `preflight_seed` before this
        point).

    Raises:
        ValueError: any name has no packaged template, the existing file is
            malformed, or the rendered result fails to re-load.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config  # local: keeps import cost off module load

    root_path = Path(root)
    path = _config_path(root_path)

    preflight_seed(root_path, names)

    result = SeedResult(created_file=not path.exists())

    # Resolve requested names, deduping while preserving order — a caller
    # passing "foo,foo" (e.g. an un-deduped `--toolkits` value) must not queue
    # "foo" twice, which would otherwise write a literal duplicate `foo:` YAML
    # key. preflight_seed already proved every name has a packaged template.
    seen: set[str] = set()
    valid_names: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            valid_names.append(name)

    # Determine already-present section keys and the file's current text.
    existing_sections: set[str] = set()
    content = ""
    if path.exists():
        content = path.read_text(encoding="utf-8")
        config = load_toolkits_config(root_path)
        existing_sections = set(config.toolkits.keys())

    # Check which sections need to be added
    sections_to_add = []
    for name in valid_names:
        if name in existing_sections:
            result.skipped.append(name)
            drift = template_drift(root_path, name)
            if drift:
                result.drift[name] = drift
        else:
            sections_to_add.append(name)

    # If file doesn't exist or doesn't have toolkits root, create/add it
    needs_toolkits_root = not path.exists() or "toolkits:" not in content
    # A hand-edited file missing a trailing newline would otherwise have the
    # first appended section's key concatenated onto its last line (e.g.
    # "enabled: true  bounded-source:") — corrupting the file.
    needs_leading_newline = bool(content) and not content.endswith("\n")

    # Assemble the complete new file text in memory, then write it once.
    if sections_to_add:
        pieces = [content]
        if needs_toolkits_root:
            pieces.append("toolkits:\n")
        elif needs_leading_newline:
            pieces.append("\n")

        for name in sections_to_add:
            template = load_template(name)
            rendered_body = template.body.replace(REPO_ROOT_PLACEHOLDER, str(root))
            pieces.append(rendered_body)
            # Ensure exactly one trailing newline
            if not rendered_body.endswith("\n"):
                pieces.append("\n")
            result.added.append(name)

        _atomic_write(path, "".join(pieces))

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
        logger.info("seeded %s: added=%s skipped=%s drift=%s", path, result.added, result.skipped, result.drift)
    return result
