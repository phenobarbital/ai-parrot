"""File-fidelity gate for coder branches (spec G7/AC-7, design research S5)."""
from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field

_HEADING = re.compile(r"^## Files to Create ?/ ?Modify\s*$", re.M)  # sdd/templates/task.md:33
_NEXT_HEADING = re.compile(r"^## ", re.M)
_BACKTICK_PATH = re.compile(r"`([^`\s]+)`")
_SEPARATOR_ROW = re.compile(r"^\|?[\s|:-]+\|?$")


class FidelityReport(BaseModel):
    """Result of comparing a task's declared files against what a coder branch actually changed."""

    ok: bool
    expected: List[str] = Field(default_factory=list)
    changed: List[str] = Field(default_factory=list)
    unexpected: List[str] = Field(default_factory=list)
    sdd_touched: List[str] = Field(default_factory=list)


def parse_task_files(task_md: str) -> List[str]:
    """Paths listed under '## Files to Create / Modify' — first backticked token of each table row or bullet."""
    m = _HEADING.search(task_md)
    if not m:
        return []
    body = task_md[m.end() :]
    n = _NEXT_HEADING.search(body)
    body = body[: n.start()] if n else body

    paths: List[str] = []
    seen: set[str] = set()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or not (line.startswith("|") or line.startswith("-")):
            continue
        if _SEPARATOR_ROW.match(line):
            continue
        match = _BACKTICK_PATH.search(line)
        if not match:
            continue
        path = match.group(1)
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport:
    """ok ⇔ changed ⊆ expected and no changed path starts with 'sdd/'."""
    exp = set(expected)
    unexpected = [p for p in changed if p not in exp]
    sdd_touched = [p for p in changed if p.startswith("sdd/")]
    return FidelityReport(
        ok=not unexpected and not sdd_touched,
        expected=list(expected),
        changed=list(changed),
        unexpected=unexpected,
        sdd_touched=sdd_touched,
    )
