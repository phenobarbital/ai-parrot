"""Pure fix planner for the SDD work ledger (FEAT-572 Module 1).

No I/O, no async, no store access, no clock except an injectable ``generated_at``:
every filesystem fact reaches this module as an argument. Ordering, grouping and
lane rules live here and ONLY here — the ``/sdd-fix`` twins execute
``wikitoolkit ledger plan-fix --json`` and never re-implement them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Final, Literal

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
