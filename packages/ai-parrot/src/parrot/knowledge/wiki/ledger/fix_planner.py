"""Pure fix planner for the SDD work ledger (FEAT-572 Module 1).

No I/O, no async, no store access, no clock except an injectable ``generated_at``:
every filesystem fact reaches this module as an argument. Ordering, grouping and
lane rules live here and ONLY here — the ``/sdd-fix`` twins execute
``wikitoolkit ledger plan-fix --json`` and never re-implement them.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.events import SEVERITY_ORDER, IssueKind, IssueSeverity

PLANNER_VERSION: Final[str] = "1"  # S2 — bump on ANY change to the contract shape or the ordering/lane rules
FAST_LANE_MAX_FILES: Final[int] = 1
FAST_LANE_KINDS: Final[frozenset[str]] = frozenset({"tech_debt"})
FAST_LANE_SEVERITIES: Final[frozenset[str]] = frozenset({"minor", "low"})
ALWAYS_SDD_KINDS: Final[frozenset[str]] = frozenset({"vulnerability"})
CODE_PATH_EXCLUDE_PREFIXES: Final[tuple[str, ...]] = ("sdd/", "docs/")
_SYM_PREFIX: Final[str] = "sym:"

Lane = Literal["fast", "sdd"]


class FixIssue(BaseModel):
    """One ledger issue as the planner sees it (a projection of ``_issue_dict``)."""

    issue_id: str
    title: str
    kind: IssueKind
    severity: IssueSeverity
    discovered_from: str | None = None
    about: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class ParentFeature(BaseModel):
    """A feature that discovered issues in this group, and whether it is still open.

    ``completed_at`` is the per-spec index's stamp, NOT the spec's ``**Status**``.
    ``open`` is exactly ``completed_at is None`` AND the parent was present in the
    caller-supplied mapping — unknown is never treated as open.
    """

    feature_id: str
    completed_at: str | None = None
    open: bool = False


class FixGroup(BaseModel):
    """A connected component of issues sharing at least one code file."""

    group_id: str
    issues: list[FixIssue]
    files: list[str]
    max_severity: IssueSeverity
    lane: Lane = "sdd"  # filled by decide_lane (TASK-3390); "sdd" is the safe default
    lane_reason: str = ""
    suggested_slug: str = ""  # filled by suggest_slug (TASK-3390)
    parents: list[ParentFeature] = Field(default_factory=list)


class FixPlan(BaseModel):
    """The full, ordered plan the twins render and execute (S2: ``groups`` is deterministic)."""

    planner_version: str = PLANNER_VERSION
    generated_at: str
    total_open: int
    groups: list[FixGroup]
    filters: dict[str, str | None] = Field(default_factory=dict)


def files_for(about: Sequence[str]) -> list[str]:
    """Extract sorted, de-duplicated repo-relative code paths from ``about`` symbol ids.

    ``sym:<path>#<qualname>`` → ``<path>``; bare ``sym:<path>`` → ``<path>``. Ids without
    the ``sym:`` prefix are ignored; paths under ``CODE_PATH_EXCLUDE_PREFIXES`` are dropped
    (a spec or doc is context, never a grouping edge). This is the ONLY grouping contract
    (S1) — ``LedgerService.get_context()`` substring matching must never be used for it.
    """
    paths: set[str] = set()
    for item in about:
        if not item.startswith(_SYM_PREFIX):
            continue
        rest = item[len(_SYM_PREFIX) :]
        path = rest.split("#", 1)[0]
        if path.startswith(CODE_PATH_EXCLUDE_PREFIXES):
            continue
        paths.add(path)
    return sorted(paths)


def group_issues(issues: Sequence[FixIssue]) -> list[FixGroup]:
    """Partition issues into connected components of the issue↔file graph.

    Two issues share a component when they share at least one file, directly or
    transitively. An issue with no files is its own singleton. Issues inside a group are
    sorted by ``(SEVERITY_ORDER, issue_id)``; groups by
    ``(SEVERITY_ORDER[max_severity], -len(issues), group_id)``. ``lane``/``lane_reason``/
    ``suggested_slug`` are left at their defaults for ``decide_lane``/``suggest_slug``.
    """
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        root = node
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(node, node) != root:
            parent[node], node = root, parent.get(node, node)
        return root

    def union(a: str, b: str) -> None:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for issue in issues:
        node = f"issue:{issue.issue_id}"
        parent.setdefault(node, node)
        for file_path in issue.files:
            file_node = f"file:{file_path}"
            union(node, file_node)

    components: dict[str, list[FixIssue]] = {}
    for issue in issues:
        node = f"issue:{issue.issue_id}"
        root = find(node)
        components.setdefault(root, []).append(issue)

    groups: list[FixGroup] = []
    for members in components.values():
        issue_ids = sorted(issue.issue_id for issue in members)
        sorted_issues = sorted(members, key=lambda issue: (SEVERITY_ORDER[issue.severity], issue.issue_id))
        member_files: set[str] = set()
        for issue in members:
            member_files.update(issue.files)
        max_severity = min((issue.severity for issue in members), key=lambda severity: SEVERITY_ORDER[severity])
        group_id = "fixgroup:" + hashlib.sha1("|".join(issue_ids).encode("utf-8")).hexdigest()[:12]
        groups.append(
            FixGroup(
                group_id=group_id,
                issues=sorted_issues,
                files=sorted(member_files),
                max_severity=max_severity,
            )
        )

    groups.sort(key=lambda group: (SEVERITY_ORDER[group.max_severity], -len(group.issues), group.group_id))
    return groups


_SPEC_PARENT_RE = re.compile(r"^spec:(FEAT-\d+)$")


def decide_lane(group: FixGroup, *, override: Lane | None = None) -> tuple[Lane, str]:
    """Return the lane for one group plus a one-line reason (spec §2 predicate on ``max_severity``).

    ``override`` short-circuits the heuristic ("forced by --lane") but is never a safety
    bypass (S7): ``override == "fast"`` raises ``ValueError`` when ``max_severity`` is
    ``critical`` or any issue is a ``vulnerability``.
    """
    kinds = {issue.kind for issue in group.issues}
    if override == "fast" and (group.max_severity == "critical" or kinds & ALWAYS_SDD_KINDS):
        raise ValueError(
            f"--lane fast refused for {group.group_id}: critical or vulnerability groups always take the SDD lane"
        )
    if override is not None:
        return override, "forced by --lane"
    if group.max_severity in ("critical", "major"):
        return "sdd", f"max_severity is {group.max_severity}"
    if kinds & ALWAYS_SDD_KINDS:
        return "sdd", "group contains a vulnerability issue"
    if not group.files:
        return "sdd", "group has no file scope"
    severities = {issue.severity for issue in group.issues}
    if severities <= FAST_LANE_SEVERITIES and kinds <= FAST_LANE_KINDS and len(group.files) <= FAST_LANE_MAX_FILES:
        return "fast", "minor/low tech_debt confined to a single file"
    return "sdd", "does not meet fast-lane criteria"


def suggest_slug(group: FixGroup) -> str:
    """Deterministic kebab-case slug from the group's dominant file (pure; NOT unique — the CLI de-duplicates)."""
    if not group.files:
        return group.group_id.replace(":", "-")
    file_counts: dict[str, int] = {}
    for issue in group.issues:
        for file_path in issue.files:
            file_counts[file_path] = file_counts.get(file_path, 0) + 1
    max_count = max(file_counts.values())
    dominant_file = min(path for path, count in file_counts.items() if count == max_count)
    path_obj = PurePosixPath(dominant_file)
    parent_dir_name = path_obj.parent.name
    stem = path_obj.stem
    base = f"{parent_dir_name}-{stem}".replace("_", "-")

    kind_counts: dict[str, int] = {}
    for issue in group.issues:
        kind_counts[issue.kind] = kind_counts.get(issue.kind, 0) + 1
    max_kind_count = max(kind_counts.values())
    dominant_kind = min(kind for kind, count in kind_counts.items() if count == max_kind_count)
    suffix = "-tech-debt" if dominant_kind == "tech_debt" else "-fixes"
    return base + suffix


def _parents_for(group: FixGroup, status: Mapping[str, str | None]) -> list[ParentFeature]:
    """Parents from ``spec:FEAT-<NNN>`` ``discovered_from`` only; absent from ``status`` ⇒ ``open=False``."""
    ids = sorted(
        {
            m.group(1)
            for issue in group.issues
            if issue.discovered_from and (m := _SPEC_PARENT_RE.match(issue.discovered_from))
        }
    )
    return [
        ParentFeature(feature_id=fid, completed_at=status.get(fid), open=(fid in status and status[fid] is None))
        for fid in ids
    ]


def plan_fix_batch(
    issues: Sequence[Mapping[str, Any]],
    *,
    kind: IssueKind | None = None,
    severity: IssueSeverity | None = None,
    lane_override: Lane | None = None,
    parent_index_status: Mapping[str, str | None] | None = None,
    generated_at: str | None = None,
) -> FixPlan:
    """Build the ordered, lane-labelled plan from ``ready_work()`` rows (see spec §3 M1 for the full contract)."""
    status = dict(parent_index_status or {})
    parsed: list[FixIssue] = []
    valid_kinds = set(get_args(IssueKind))
    for row in issues:
        issue_id = row.get("issue_id")
        row_kind = row.get("kind")
        row_severity = row.get("severity")
        if not issue_id or row_kind not in valid_kinds or row_severity not in SEVERITY_ORDER:
            continue
        about = row.get("about") or []
        parsed.append(
            FixIssue(
                issue_id=issue_id,
                title=row.get("title", ""),
                kind=row_kind,
                severity=row_severity,
                discovered_from=row.get("discovered_from"),
                about=about,
                files=files_for(about),
            )
        )
    selected = [i for i in parsed if (kind is None or i.kind == kind) and (severity is None or i.severity == severity)]
    groups = group_issues(selected)
    for group in groups:
        group.lane, group.lane_reason = decide_lane(group, override=lane_override)
        group.suggested_slug = suggest_slug(group)
        group.parents = _parents_for(group, status)
    return FixPlan(
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
        total_open=len(parsed),
        groups=groups,
        filters={"kind": kind, "severity": severity, "lane": lane_override},
    )
