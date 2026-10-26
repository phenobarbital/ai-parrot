"""Brief frontmatter model and worktree/index planning for ``/sdd-brief`` (FEAT-698).

Briefs never go through ``FlowMeta``: it ships in the wikitoolkit wheel and its
``hotfix => main`` validator cannot represent a dev-based ledger brief. This
module therefore builds ``WorktreePlan`` directly and owns the brief's identity.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Literal, Sequence

import yaml
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from parrot.sdd.config import SddConfig, load_sdd_config
from parrot.sdd.scripts.sdd_meta import WORKTREE_ROOT, WorktreePlan

logger = logging.getLogger(__name__)

#: Repo-relative home of every brief artifact, inside a worktree only.
BRIEFS_DIR: str = "sdd/briefs"
#: Prefix of the per-brief index ``feature_id`` — non-empty, never ``FEAT-<NNN>``.
BRIEF_ID_PREFIX: str = "BRIEF-"
#: Long-lived branches a brief may base on when no ``sdd/config.json`` exists (CLAUDE.md "Git Configuration").
BRIEF_BASE_BRANCHES: frozenset[str] = frozenset({"main", "dev", "staging"})


def brief_base_branches(config: SddConfig) -> frozenset[str]:
    """Return the branches a brief may base on: the configured hotfix, base and (if set) staging branches."""
    branches = {config.hotfix_base, config.base_branch}
    if config.staging_branch:
        branches.add(config.staging_branch)
    return frozenset(branches)
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _is_safe_ref(value: str) -> bool:
    """Whether ``value`` is usable as a single ``git check-ref-format`` component.

    ``_SAFE_REF_RE`` alone still admits sequences git rejects, so an invalid
    brief key would surface late — inside ``git worktree add`` — instead of at
    parse time. Reject them here: ``..`` anywhere, a trailing ``.``, and the
    reserved ``.lock`` suffix.
    """
    if not _SAFE_REF_RE.fullmatch(value):
        return False
    return ".." not in value and not value.endswith(".") and not value.endswith(".lock")


def _check_base_branch(base_branch: str, config: SddConfig | None = None) -> str:
    """Return ``base_branch`` when it is one of the configured long-lived branches.

    Args:
        base_branch: Candidate branch name.
        config: SDD configuration; ``None`` loads the current repository's.

    Raises:
        ValueError: When the branch is not a configured long-lived branch.
    """
    allowed = brief_base_branches(config or load_sdd_config())
    value = base_branch.strip()
    if value not in allowed:
        raise ValueError(f"base_branch must be one of {sorted(allowed)}, got {base_branch!r}")
    return value


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
    base_branch: str
    source: BriefSource
    jira_issue_key: str | None = None
    ledger_issue: str | None = None
    created: str

    @field_validator("slug", "key")
    @classmethod
    def _branch_safe(cls, value: str) -> str:
        """Reject values that cannot appear in a git branch / worktree dir name."""
        value = value.strip()
        if not _is_safe_ref(value):
            raise ValueError("must be safe for a git branch and worktree directory name")
        return value

    @model_validator(mode="before")
    @classmethod
    def _default_base_branch(cls, data: Any, info: ValidationInfo) -> Any:
        """Fill a missing ``base_branch`` with the configured hotfix base (``"main"`` by default)."""
        if isinstance(data, dict) and "base_branch" not in data:
            cfg = (info.context or {}).get("sdd_config") or load_sdd_config()
            data = {**data, "base_branch": cfg.hotfix_base}
        return data

    @field_validator("base_branch")
    @classmethod
    def _known_base_branch(cls, value: str, info: ValidationInfo) -> str:
        """Reject base branches outside the configured long-lived set."""
        return _check_base_branch(value, (info.context or {}).get("sdd_config"))

    @model_validator(mode="after")
    def _ledger_implies_dev(self, info: ValidationInfo) -> "BriefMeta":
        """A ledger-sourced brief always bases on the configured base branch (``dev`` by default)."""
        if self.source.type == "ledger":
            cfg = (info.context or {}).get("sdd_config") or load_sdd_config()
            if self.base_branch != cfg.base_branch:
                raise ValueError(f"ledger-sourced briefs require base_branch={cfg.base_branch!r}")
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


def parse_brief(doc_path: Path, *, config: SddConfig | None = None) -> BriefMeta:
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
    cfg = config or load_sdd_config()
    return BriefMeta.model_validate(block, context={"sdd_config": cfg})


def emit_brief_frontmatter(meta: BriefMeta) -> str:
    """Render ``meta`` as a ``---``-delimited YAML block ending in a newline."""
    body = yaml.safe_dump(meta.model_dump(), sort_keys=False).rstrip()
    return f"---\n{body}\n---\n"


def brief_worktree_plan(*, slug: str, key: str, base_branch: str, config: SddConfig | None = None) -> WorktreePlan:
    """Build a brief worktree plan using its base branch and safe identity fields.

    Re-checks the ``BriefMeta`` invariants for callers that never build one —
    notably ``ensure_worktree --brief-key``, which plans straight from raw CLI
    strings. ``config=None`` loads the current repository's ``sdd/config.json``. The ``ledger => dev`` rule stays on ``BriefMeta`` alone: the
    source type is not derivable from these arguments.

    Raises:
        ValueError: When ``slug``/``key`` are not safe ref components, or
            ``base_branch`` is not one of the configured long-lived branches.
    """
    if not _is_safe_ref(slug) or not _is_safe_ref(key):
        raise ValueError("slug and key must be safe for a git branch and worktree directory name")
    cfg = config or load_sdd_config()
    base_branch = _check_base_branch(base_branch, cfg)

    prefix = "hotfix" if base_branch == cfg.hotfix_base else "fix"
    name = f"{prefix}-{key}-{slug}"
    return WorktreePlan(
        name=name,
        path=f"{WORKTREE_ROOT}/{name}",
        base_ref=f"origin/{base_branch}",
    )


def plan_brief_worktree(meta: BriefMeta, *, config: SddConfig | None = None) -> WorktreePlan:
    """Plan the worktree for an already-validated brief."""
    return brief_worktree_plan(slug=meta.slug, key=meta.key, base_branch=meta.base_branch, config=config)


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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI for installed flows: ``plan`` prints a worktree plan, ``write-index`` writes the brief index."""
    parser = argparse.ArgumentParser(prog="brief_meta", description="Brief helpers for /sdd-brief (FEAT-698).")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="Print the brief worktree plan as JSON.")
    plan_p.add_argument("--slug", required=True)
    plan_p.add_argument("--key", required=True)
    plan_p.add_argument("--base-branch", required=True)

    index_p = sub.add_parser("write-index", help="Write the per-brief index and print its path.")
    index_p.add_argument("brief", help="Path to the brief markdown file.")
    index_p.add_argument("--tasks", required=True, help="JSON file with the partial task records.")
    index_p.add_argument("--worktree-root", required=True, help="Directory the artifacts are written under.")

    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    try:
        if args.command == "plan":
            plan = brief_worktree_plan(slug=args.slug, key=args.key, base_branch=args.base_branch)
            print(json.dumps(plan.model_dump()))
        else:
            meta = parse_brief(Path(args.brief))
            tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
            print(str(write_brief_index(meta, tasks, Path(args.worktree_root))))
    except Exception as exc:  # CLI boundary: report and exit non-zero
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
