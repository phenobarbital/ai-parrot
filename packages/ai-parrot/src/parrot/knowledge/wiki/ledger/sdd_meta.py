"""SDD flow-type frontmatter parser shared across SDD commands and agents.

This module is the single source of truth for reading and emitting the
YAML frontmatter block that brainstorm/proposal/spec documents carry to
declare their SDD flow type and base branch.

The contract is intentionally tiny: a Pydantic model with a cross-field
validator, a forgiving ``parse`` that returns sensible defaults when no
frontmatter is present (so legacy specs keep working), and a symmetric
``emit`` used by generation commands when scaffolding new documents.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from parrot.sdd.config import SddConfig, find_repo_root, load_sdd_config

logger = logging.getLogger(__name__)


#: Canonical long-lived branches in the Git Parrot Flow (FEAT-187).
#: Commands use this for a soft warning when ``base_branch`` falls
#: outside the set; ``FlowMeta`` itself accepts any string so
#: sub-feature branches keep working (see CLAUDE.md).
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})

#: Default base branch for feature work and the mandatory base for hotfixes
#: (Git Parrot Flow, FEAT-187). TASK-4299 makes them configurable per repo.
DEFAULT_FEATURE_BASE: str = "dev"
DEFAULT_HOTFIX_BASE: str = "main"

#: WorkKind -> (flow type, base branch). A bugfix is a hotfix and lands on
#: main; everything else is a feature and lands on dev. This mapping used to
#: live only as prose in .claude/agents/sdd-research.md (FEAT-466).
WORK_KIND_FLOW: dict[str, tuple[str, str]] = {
    "bug": ("hotfix", DEFAULT_HOTFIX_BASE),
    "enhancement": ("feature", DEFAULT_FEATURE_BASE),
    "new_feature": ("feature", DEFAULT_FEATURE_BASE),
}


#: Canonical ``projects`` values for SDD docs (FEAT-576): every ``packages/<dist>``
#: directory name plus non-package areas. Soft vocabulary — like
#: ``KNOWN_BRANCHES``, an unknown value logs a warning and is kept, never rejected.
KNOWN_PROJECTS: frozenset[str] = frozenset(
    {
        "ai-parrot",
        "ai-parrot-advisors",
        "ai-parrot-client-amazon",
        "ai-parrot-client-anthropic",
        "ai-parrot-client-gemma4",
        "ai-parrot-client-google",
        "ai-parrot-client-grok",
        "ai-parrot-client-groq",
        "ai-parrot-client-hf",
        "ai-parrot-client-jev",
        "ai-parrot-client-local",
        "ai-parrot-client-meta",
        "ai-parrot-client-moonshot",
        "ai-parrot-client-nvidia",
        "ai-parrot-client-openai",
        "ai-parrot-client-openrouter",
        "ai-parrot-client-vllm",
        "ai-parrot-client-zai",
        "ai-parrot-embeddings",
        "ai-parrot-integrations",
        "ai-parrot-loaders",
        "ai-parrot-openlit-bridge",
        "ai-parrot-pipelines",
        "ai-parrot-server",
        "ai-parrot-tools",
        "ai-parrot-visualizations",
        "navrules",
        "parrot-formdesigner",
        "sdd-tooling",
        "dev-loop",
        "admin-ui",
        "docs",
        "ci",
    }
)

#: alias -> canonical project name, applied after tag-style normalization.
PROJECT_ALIASES: dict[str, str] = {
    "parrot-core": "ai-parrot",
    "core": "ai-parrot",
    "parrot": "ai-parrot",
    "formdesigner": "parrot-formdesigner",
    "server": "ai-parrot-server",
    "tools": "ai-parrot-tools",
    "parrot-tools": "ai-parrot-tools",
    "sdd": "sdd-tooling",
    "ui": "admin-ui",
}

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class FlowMeta(BaseModel):
    """SDD flow metadata derived from a doc's YAML frontmatter."""

    type: Literal["feature", "hotfix"]
    base_branch: str
    #: Configured hotfix lane (``SddConfig.hotfix_base``); policy input only, never emitted.
    hotfix_base: str = Field(default=DEFAULT_HOTFIX_BASE, exclude=True)

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":
        if self.type == "hotfix" and self.base_branch != self.hotfix_base:
            raise ValueError(
                f"type='hotfix' requires base_branch={self.hotfix_base!r} (got base_branch={self.base_branch!r})"
            )
        return self


def _config_for(doc_path: Path | None, config: SddConfig | None) -> SddConfig:
    """Return ``config`` when given, else the config of the repository holding ``doc_path`` (or cwd)."""
    if config is not None:
        return config
    return load_sdd_config(find_repo_root(doc_path.parent) if doc_path is not None else None)


def _read_frontmatter(doc_path: Path) -> dict[str, Any] | None:
    """Return the leading YAML frontmatter of ``doc_path`` as a dict.

    Same rules as :func:`parse`: the block must start at byte 0 with ``---``.
    Returns ``None`` when there is no usable block (no leading ``---``, an
    unterminated block, or a non-mapping body) and ``{}`` for an empty block.
    """
    text = doc_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    block = yaml.safe_load(parts[1]) or {}
    return block if isinstance(block, dict) else None


def read_declared_base_branch(doc_path: Path) -> str | None:
    """Return the ``base_branch`` a document's YAML frontmatter declares, or ``None``.

    ``None`` means "nothing declared": the file is missing or unreadable, has no leading
    frontmatter block, the YAML is malformed, the block is not a mapping, or
    ``base_branch`` is absent, not a string, or blank. Callers decide the default —
    this function never does and never raises.
    """
    try:
        block = _read_frontmatter(doc_path)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    if not block:
        return None
    value = block.get("base_branch")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def parse(doc_path: Path, *, config: SddConfig | None = None) -> FlowMeta:
    """Parse YAML frontmatter from a brainstorm/proposal/spec markdown file.

    The frontmatter block, when present, must be the first thing in the
    file: a line containing only ``---``, the YAML body, and a closing
    ``---`` line. Anything before the opening ``---`` (including a UTF-8
    BOM or leading whitespace) means the file is treated as having no
    frontmatter and the defaults are returned.

    Args:
        doc_path: Path to the markdown file to inspect.
        config: SDD configuration; ``None`` loads ``sdd/config.json`` of the document's repository.

    Returns:
        ``FlowMeta(type="feature", base_branch=<configured base>)`` when no
        frontmatter is present (backwards-compat for in-flight specs);
        otherwise a fully-validated ``FlowMeta``.

    Raises:
        pydantic.ValidationError: When frontmatter is present but
            invalid (e.g. ``type: hotfix`` without ``base_branch: main``).
    """
    cfg = _config_for(doc_path, config)
    block = _read_frontmatter(doc_path)
    if block is None:
        return FlowMeta(type="feature", base_branch=cfg.base_branch, hotfix_base=cfg.hotfix_base)
    block = {k: v for k, v in block.items() if k != "hotfix_base"}
    return FlowMeta(**block, hotfix_base=cfg.hotfix_base)


def emit(meta: FlowMeta) -> str:
    """Render a ``FlowMeta`` as a Jekyll-style frontmatter block.

    The returned string is suitable for prepending to a brainstorm,
    proposal, or spec markdown file. It always ends with a newline so
    the existing document body can be concatenated directly.

    Args:
        meta: The flow metadata to serialize.

    Returns:
        A string of the form ``"---\\n<yaml>\\n---\\n"``.
    """
    body = yaml.safe_dump(meta.model_dump(), sort_keys=False).rstrip()
    return f"---\n{body}\n---\n"


def normalize_tag(raw: str) -> str:
    """Normalize a tag: lowercase, trim, whitespace/underscore runs -> '-', collapse '--', strip '-'.

    Raises:
        ValueError: when the result does not match ``^[a-z0-9][a-z0-9-]{0,39}$``.
    """
    value = raw.strip().lower()
    value = re.sub(r"[\s_]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-")
    if not _TAG_RE.match(value):
        raise ValueError(f"Invalid tag/project {raw!r}: normalized to {value!r}, " f"must match {_TAG_RE.pattern!r}")
    return value


def normalize_project(raw: str, *, known: frozenset[str] | None = None) -> str:
    """Normalize like a tag, then map through ``PROJECT_ALIASES``.

    Logs a warning (never raises) when the canonical value is not in ``known``
    (``None`` means ``KNOWN_PROJECTS``).

    Raises:
        ValueError: only when the value is malformed (see :func:`normalize_tag`).
    """
    value = normalize_tag(raw)
    value = PROJECT_ALIASES.get(value, value)
    if value not in (KNOWN_PROJECTS if known is None else known):
        logger.warning("Unknown SDD project %r (not in KNOWN_PROJECTS); keeping it", value)
    return value


def _as_list(value: Any) -> list[Any]:
    """Coerce a frontmatter value into a list: ``None`` -> ``[]``, ``str`` -> ``[str]``.

    Raises:
        ValueError: when ``value`` is neither ``None``, a string, nor a list.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    raise ValueError(f"Expected a string or list of strings, got {type(value).__name__}: {value!r}")


class DocTaxonomy(BaseModel):
    """Organizational metadata of an SDD doc: the projects it concerns and its tags."""

    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("projects", mode="before")
    @classmethod
    def _norm_projects(cls, value: Any, info: ValidationInfo) -> list[str]:
        """Coerce None/str to a list, normalize each entry, dedupe preserving order."""
        result: list[str] = []
        for item in _as_list(value):
            normalized = normalize_project(item, known=(info.context or {}).get("known_projects"))
            if normalized not in result:
                result.append(normalized)
        return result

    @field_validator("tags", mode="before")
    @classmethod
    def _norm_tags(cls, value: Any) -> list[str]:
        """Same as projects, with :func:`normalize_tag` and no vocabulary check."""
        result: list[str] = []
        for item in _as_list(value):
            normalized = normalize_tag(item)
            if normalized not in result:
                result.append(normalized)
        return result


def parse_taxonomy(doc_path: Path, *, config: SddConfig | None = None) -> DocTaxonomy:
    """Parse ``projects``/``tags`` from a brainstorm/proposal/spec frontmatter (FEAT-576).

    Args:
        doc_path: Markdown document to inspect.
        config: SDD configuration; ``None`` loads the document's repository config. A configured
            ``projects`` list replaces ``KNOWN_PROJECTS`` as the (warn-only) vocabulary.

    Returns:
        A ``DocTaxonomy``; empty lists when the doc has no frontmatter or no keys.

    Raises:
        pydantic.ValidationError: when a tag/project is malformed.
    """
    cfg = _config_for(doc_path, config)
    known = frozenset(cfg.projects) if cfg.projects else KNOWN_PROJECTS
    block = _read_frontmatter(doc_path) or {}
    return DocTaxonomy.model_validate(
        {"projects": block.get("projects"), "tags": block.get("tags")},
        context={"known_projects": known},
    )


def resolve_flow(
    *,
    kind: str | None = None,
    doc_path: Path | None = None,
    type_override: str | None = None,
    base_branch_override: str | None = None,
    config: SddConfig | None = None,
) -> FlowMeta:
    """Resolve the SDD flow type and base branch for a run.

    Precedence, highest first:
      1. ``type_override`` / ``base_branch_override`` (explicit caller intent)
      2. ``doc_path`` frontmatter, when the path is given AND exists
      3. ``WORK_KIND_FLOW[kind]``
      4. ``("feature", <configured base_branch>)``

    Levels 1 and 2/3 compose: an explicit ``base_branch_override`` with no
    ``type_override`` keeps the type resolved from the lower level, and vice
    versa. This is what lets the console override only the base branch.

    Args:
        kind: A ``WorkKind`` value (``"bug"``/``"enhancement"``/
            ``"new_feature"``). Unknown or ``None`` falls through to the
            default.
        doc_path: Optional brainstorm/proposal/spec whose frontmatter should
            be consulted. A path that does not exist is treated as "no
            document", NOT as an error.
        type_override: Explicit ``"feature"``/``"hotfix"``.
        base_branch_override: Explicit branch name.
        config: SDD configuration; ``None`` loads ``sdd/config.json`` of the repository holding
            ``doc_path`` (or the cwd). Absent file means today's ``dev``/``main`` defaults.

    Returns:
        A validated ``FlowMeta``.

    Raises:
        ValueError: When the resolved combination is invalid — e.g.
            ``type="hotfix"`` with a base branch other than the configured hotfix base. Raised
            by ``FlowMeta``'s own validator, not re-implemented here.
    """
    cfg = _config_for(doc_path, config)
    resolved_type: str | None = None
    resolved_base: str | None = None

    if doc_path is not None and doc_path.exists():
        from_doc = parse(doc_path, config=cfg)
        resolved_type, resolved_base = from_doc.type, from_doc.base_branch
    elif kind in WORK_KIND_FLOW:
        resolved_type = WORK_KIND_FLOW[kind][0]
        resolved_base = cfg.hotfix_base if resolved_type == "hotfix" else cfg.base_branch

    final_type = type_override or resolved_type or "feature"
    final_base = base_branch_override or resolved_base or cfg.base_branch

    known = KNOWN_BRANCHES | {b for b in (cfg.base_branch, cfg.hotfix_base, cfg.staging_branch) if b}
    if final_base not in known:
        logger.warning(
            "base_branch %r is not one of the canonical branches %s; " "assuming a sub-feature branch.",
            final_base,
            sorted(known),
        )
    return FlowMeta(type=final_type, base_branch=final_base, hotfix_base=cfg.hotfix_base)


#: Every SDD worktree lives directly under this repo-relative directory.
WORKTREE_ROOT: str = ".claude/worktrees"

#: A reserved feature id, e.g. ``FEAT-552``. Bare numbers are rejected.
_FEATURE_ID_RE = re.compile(r"^FEAT-\d+$")


class WorktreePlan(BaseModel):
    """Where a feature/hotfix worktree goes and what it branches from."""

    name: str
    path: str
    base_ref: str


def plan_worktree(
    meta: FlowMeta,
    *,
    slug: str,
    feature_id: str | None = None,
    jira_key: str | None = None,
) -> WorktreePlan:
    """Resolve the canonical worktree name, path and base ref for a run.

    Naming (confirmed canonical 2026-09-11 — it is what /sdd-done greps on):
      * ``type == "feature"`` -> ``feat-<feature_id>-<slug>``, e.g.
        ``feat-FEAT-552-worktree-creation-ownership``. The doubled
        ``feat-FEAT-`` prefix is intentional, not a bug.
      * ``type == "hotfix"``  -> ``hotfix-<jira_key>-<slug>`` (FEAT-466: a
        hotfix reserves no FEAT-<NNN>; its identity is the Jira key).

    ``base_ref`` is always ``origin/<meta.base_branch>`` so a worktree can
    never inherit an unpushed local HEAD. For a hotfix that is ``origin/main``
    by construction — ``FlowMeta`` already refuses any other base branch for
    a hotfix (see ``_hotfix_implies_main``).

    Args:
        meta: Resolved flow metadata.
        slug: Feature slug, kebab-case.
        feature_id: ``FEAT-<NNN>``; required when ``meta.type == "feature"``.
        jira_key: Jira issue key; required when ``meta.type == "hotfix"``.

    Returns:
        A ``WorktreePlan`` whose ``path`` is repo-relative.

    Raises:
        ValueError: When ``slug`` is empty or blank; when a feature run has no
            ``feature_id`` or one not matching ``^FEAT-\\d+$``; when a hotfix
            run has no ``jira_key``.
    """
    if not slug or not slug.strip():
        raise ValueError("slug cannot be empty or blank")

    if meta.type == "feature":
        if not feature_id:
            raise ValueError("feature_id is required for feature runs")
        if not _FEATURE_ID_RE.match(feature_id):
            raise ValueError(f"feature_id must match ^FEAT-\\d+$, got {feature_id!r}")
        name = f"feat-{feature_id}-{slug}"
    elif meta.type == "hotfix":
        if not jira_key or not jira_key.strip():
            raise ValueError("jira_key is required for hotfix runs")
        name = f"hotfix-{jira_key}-{slug}"
    else:
        raise ValueError(f"Unsupported flow type: {meta.type}")

    path = f"{WORKTREE_ROOT}/{name}"
    base_ref = f"origin/{meta.base_branch}"

    return WorktreePlan(name=name, path=path, base_ref=base_ref)
