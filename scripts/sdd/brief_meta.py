"""Brief frontmatter model and worktree/index planning for ``/sdd-brief`` (FEAT-698).

Briefs never go through ``FlowMeta``: it ships in the wikitoolkit wheel and its
``hotfix => main`` validator cannot represent a dev-based ledger brief. This
module therefore builds ``WorktreePlan`` directly and owns the brief's identity.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from scripts.sdd.sdd_meta import WORKTREE_ROOT, WorktreePlan

logger = logging.getLogger(__name__)

#: Repo-relative home of every brief artifact, inside a worktree only.
BRIEFS_DIR: str = "sdd/briefs"
#: Prefix of the per-brief index ``feature_id`` — non-empty, never ``FEAT-<NNN>``.
BRIEF_ID_PREFIX: str = "BRIEF-"
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

SourceType = Literal["code-scanning", "github-issue", "jira", "ledger", "text", "file"]


class BriefSource(BaseModel):
    """Where a brief came from."""

    type: SourceType
    ref: str = Field(..., min_length=1)
    url: str | None = None


class BriefMeta(BaseModel):
    """Frontmatter of ``sdd/briefs/<slug>.brief.md``."""

    kind: Literal["brief"]
    slug: str
    key: str
    base_branch: str = "main"
    source: BriefSource
    jira_issue_key: str | None = None
    ledger_issue: str | None = None
    created: str

    @field_validator("slug", "key")
    @classmethod
    def _branch_safe(cls, value: str) -> str:
        """Reject values that cannot appear in a git branch / worktree dir name."""
        value = value.strip()
        if not _SAFE_REF_RE.fullmatch(value):
            raise ValueError("must be safe for a git branch and worktree directory name")
        return value

    @model_validator(mode="after")
    def _ledger_implies_dev(self) -> "BriefMeta":
        """A ledger-sourced brief always bases on dev (binding brainstorm decision)."""
        if self.source.type == "ledger" and self.base_branch != "dev":
            raise ValueError("ledger-sourced briefs require base_branch='dev'")
        return self

    @property
    def feature_id(self) -> str:
        """Index identity: ``BRIEF-<KEY>``."""
        return f"{BRIEF_ID_PREFIX}{self.key}"

    @property
    def brief_path(self) -> str:
        """Repo-relative path of the brief document."""
        return f"{BRIEFS_DIR}/{self.slug}.brief.md"

    @property
    def index_path(self) -> str:
        """Repo-relative path of the per-brief index."""
        return f"{BRIEFS_DIR}/{self.slug}.index.json"

    @property
    def tasks_dir(self) -> str:
        """Repo-relative directory holding the materialized task files."""
        return f"{BRIEFS_DIR}/{self.slug}/tasks"


def parse_brief(doc_path: Path) -> BriefMeta:
    """Parse a brief's leading YAML frontmatter.

    Raises:
        ValueError: When the file has no frontmatter block at byte 0.
        pydantic.ValidationError: When the block does not validate as ``BriefMeta``.
    """
    text = doc_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"brief {doc_path} has no leading frontmatter block")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"brief {doc_path} has an unterminated frontmatter block")

    block = yaml.safe_load(parts[1]) or {}
    if not isinstance(block, dict):
        raise ValueError(f"brief {doc_path} frontmatter must be a YAML mapping")
    return BriefMeta.model_validate(block)


def emit_brief_frontmatter(meta: BriefMeta) -> str:
    """Render ``meta`` as a ``---``-delimited YAML block ending in a newline."""
    body = yaml.safe_dump(meta.model_dump(), sort_keys=False).rstrip()
    return f"---\n{body}\n---\n"


def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:
    """Build a brief worktree plan using its base branch and safe identity fields."""
    if not _SAFE_REF_RE.fullmatch(slug) or not _SAFE_REF_RE.fullmatch(key):
        raise ValueError("slug and key must be safe for a git branch and worktree directory name")

    prefix = "hotfix" if base_branch == "main" else "fix"
    name = f"{prefix}-{key}-{slug}"
    return WorktreePlan(
        name=name,
        path=f"{WORKTREE_ROOT}/{name}",
        base_ref=f"origin/{base_branch}",
    )


def plan_brief_worktree(meta: BriefMeta) -> WorktreePlan:
    """Plan the worktree for an already-validated brief."""
    return brief_worktree_plan(slug=meta.slug, key=meta.key, base_branch=meta.base_branch)


def brief_task_id(meta: BriefMeta, n: int) -> str:
    """Local, unreserved task id ``HOTFIX-<KEY>-<n>`` (n >= 1)."""
    if n < 1:
        raise ValueError(f"task number must be >= 1, got {n}")
    return f"HOTFIX-{meta.key}-{n}"


def write_brief_index(meta: BriefMeta, tasks: list[dict[str, Any]], worktree_root: Path) -> Path:
    """Write ``sdd/briefs/<slug>.index.json`` and return its path.

    Args:
        meta: Validated metadata which supplies the index header.
        tasks: Partial task records containing ``id``, ``slug``, ``title``, and ``file``.
        worktree_root: Root directory in which the brief artifacts are written.
    """
    header: dict[str, Any] = {
        "feature": meta.slug,
        "feature_id": meta.feature_id,
        "spec": meta.brief_path,
        "type": "brief",
        "base_branch": meta.base_branch,
        "created_at": meta.created,
        "completed_at": None,
        "parallel_semantics": "exclusive",
        "validation_contract": "required",
        "tasks": [],
    }
    for task in tasks:
        entry = {
            "id": task["id"],
            "slug": task["slug"],
            "title": task["title"],
            "feature_id": header["feature_id"],
            "feature": header["feature"],
            "spec": header["spec"],
            "status": task.get("status", "pending"),
            "priority": task.get("priority", "high"),
            "effort": task.get("effort", "S"),
            "depends_on": task.get("depends_on", []),
            "parallel": task.get("parallel", True),
            "parallelism_notes": task.get("parallelism_notes", ""),
            "assigned_to": task.get("assigned_to", None),
            "started_at": task.get("started_at", None),
            "completed_at": task.get("completed_at", None),
            "file": task["file"],
        }
        header["tasks"].append(entry)

    path = Path(worktree_root) / meta.index_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(header, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote brief index %s (%d task(s))", path, len(header["tasks"]))
    return path
