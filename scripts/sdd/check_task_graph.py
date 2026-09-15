"""``check_task_graph.py`` — deterministic lint for a per-spec task graph.

``depends_on`` is the ONLY thing that orders tasks; ``parallel: false`` marks a
task as *exclusive* (never dispatched alongside another task). Both are written
by an LLM in ``/sdd-task``, which is how querysource FEAT-147 shipped 18 tasks
chained 1→2→…→18 with one copy-pasted rationale, so the sdd-coder engine ran a
parallelizable feature strictly in series. This script checks the graph against
what the task files actually declare, instead of trusting the prose:

Errors (exit 1):
  * ``unknown-dependency`` — a ``depends_on`` id that is not in the index.
  * ``cycle`` — the ``depends_on`` graph has a cycle.
  * ``file-overlap`` — two tasks declare the same file and neither depends
    (transitively) on the other, so they could run concurrently and conflict.

Warnings (exit 0):
  * ``unjustified-edge`` — B depends on A, but they share no file, B's task
    file never references a file A declares (by path or dotted module), and
    B's ``parallelism_notes`` do not name A.
  * ``possible-missing-dependency`` — B references a file A creates, yet B does
    not depend on A.
  * ``duplicate-notes`` — the same ``parallelism_notes`` on 3+ tasks.
  * ``exclusive-without-notes`` — ``parallel: false`` with no named resource.
  * ``legacy-semantics`` — the header lacks ``"parallel_semantics":
    "exclusive"``, so the engine ignores every ``parallel`` flag.

Usage:
    python -m scripts.sdd.check_task_graph sdd/tasks/index/<feature>.json [--root .] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

PARALLEL_SEMANTICS = "exclusive"

_HEADING = re.compile(r"^## Files to Create ?/ ?Modify\s*$", re.M)
_NEXT_HEADING = re.compile(r"^## ", re.M)
_BACKTICK_PATH = re.compile(r"`([^`\s]+)`")
_SEPARATOR_ROW = re.compile(r"^\|?[\s|:-]+\|?$")
_CREATE = re.compile(r"\bcreate\b", re.I)


class Finding(BaseModel):
    """One graph problem."""

    level: str  # "error" | "warning"
    code: str
    tasks: list[str] = Field(default_factory=list)
    message: str


class GraphReport(BaseModel):
    """Result of checking one per-spec index."""

    index: str
    task_count: int
    waves: list[list[str]] = Field(default_factory=list)
    exclusive: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        """Findings that fail the check."""
        return [f for f in self.findings if f.level == "error"]


class _Task(BaseModel):
    id: str
    depends_on: list[str] = Field(default_factory=list)
    parallel: bool = True
    notes: str = ""
    text: str = ""
    files: dict[str, bool] = Field(default_factory=dict)  # path -> is CREATE


def parse_declared_files(task_md: str) -> dict[str, bool]:
    """Map each path under '## Files to Create / Modify' to whether its row says CREATE.

    Args:
        task_md: The task markdown.

    Returns:
        ``{path: is_create}`` in declaration order.
    """
    m = _HEADING.search(task_md)
    if not m:
        return {}
    body = task_md[m.end() :]
    n = _NEXT_HEADING.search(body)
    body = body[: n.start()] if n else body
    files: dict[str, bool] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith(("|", "-")) or _SEPARATOR_ROW.match(line):
            continue
        match = _BACKTICK_PATH.search(line)
        if match and match.group(1) not in files:
            files[match.group(1)] = bool(_CREATE.search(line[match.end() :]))
    return files


def module_of(path: str) -> str | None:
    """Dotted import path of a ``.py`` file (src-layout aware), or None when too generic to match."""
    p = PurePosixPath(path)
    if p.suffix != ".py":
        return None
    parts = list(p.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if len(parts) >= 2 else None


def _references(text: str, path: str) -> bool:
    if path in text:
        return True
    module = module_of(path)
    return bool(module and re.search(rf"(?<![\w.]){re.escape(module)}(?![\w])", text))


def _read_task_text(root: Path, file: str) -> str:
    candidates = [root / file] if file else []
    if file:
        name = PurePosixPath(file).name
        candidates += [root / "sdd/tasks/active" / name, root / "sdd/tasks/completed" / name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return ""


def _ancestors(tasks: dict[str, _Task]) -> dict[str, set[str]]:
    """Transitive ``depends_on`` closure per task (unknown ids and cycles tolerated)."""
    memo: dict[str, set[str]] = {}

    def visit(tid: str, stack: frozenset[str]) -> set[str]:
        if tid in memo:
            return memo[tid]
        acc: set[str] = set()
        for dep in tasks[tid].depends_on:
            if dep in tasks and dep not in stack:
                acc.add(dep)
                acc |= visit(dep, stack | {dep})
        memo[tid] = acc
        return acc

    for tid in tasks:
        visit(tid, frozenset({tid}))
    return memo


def _waves(tasks: dict[str, _Task]) -> tuple[list[list[str]], list[str]]:
    """Kahn levels; returns (waves, ids stuck in a cycle)."""
    remaining = {tid: {d for d in t.depends_on if d in tasks} for tid, t in tasks.items()}
    waves: list[list[str]] = []
    while remaining:
        ready = sorted(tid for tid, deps in remaining.items() if not deps)
        if not ready:
            return waves, sorted(remaining)
        waves.append(ready)
        for tid in ready:
            del remaining[tid]
        for deps in remaining.values():
            deps.difference_update(ready)
    return waves, []


def check_graph(index_path: Path, root: Path) -> GraphReport:
    """Check one per-spec index against its task files.

    Args:
        index_path: ``sdd/tasks/index/<feature>.json``.
        root: Repository root the index's ``file`` paths are relative to.

    Returns:
        The graph report.
    """
    data = json.loads(index_path.read_text(encoding="utf-8"))
    tasks: dict[str, _Task] = {}
    for entry in data.get("tasks", []):
        text = _read_task_text(root, entry.get("file", ""))
        tasks[entry["id"]] = _Task(
            id=entry["id"],
            depends_on=list(entry.get("depends_on") or []),
            parallel=bool(entry.get("parallel", True)),
            notes=(entry.get("parallelism_notes") or "").strip(),
            text=text,
            files=parse_declared_files(text),
        )
    report = GraphReport(index=str(index_path), task_count=len(tasks))
    add = report.findings.append
    exclusive_semantics = data.get("parallel_semantics") == PARALLEL_SEMANTICS
    if not exclusive_semantics:
        add(
            Finding(
                level="warning",
                code="legacy-semantics",
                message='index header lacks "parallel_semantics": "exclusive" — the engine ignores `parallel` flags',
            )
        )
    else:
        report.exclusive = sorted(tid for tid, t in tasks.items() if not t.parallel)

    for tid, task in tasks.items():
        for dep in task.depends_on:
            if dep not in tasks:
                add(
                    Finding(
                        level="error",
                        code="unknown-dependency",
                        tasks=[tid, dep],
                        message=f"{tid} depends on unknown {dep}",
                    )
                )

    report.waves, cyclic = _waves(tasks)
    if cyclic:
        add(Finding(level="error", code="cycle", tasks=cyclic, message="depends_on cycle among " + ", ".join(cyclic)))
    ancestors = _ancestors(tasks)
    ids = sorted(tasks)

    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            shared = sorted(set(tasks[a].files) & set(tasks[b].files))
            if shared and a not in ancestors[b] and b not in ancestors[a]:
                add(
                    Finding(
                        level="error",
                        code="file-overlap",
                        tasks=[a, b],
                        message=f"{a} and {b} both declare {', '.join(shared)} but neither depends on the other",
                    )
                )

    for tid, task in tasks.items():
        direct = [d for d in task.depends_on if d in tasks]
        for dep in direct:
            if any(dep in ancestors[other] for other in direct if other != dep):
                continue  # implied by another path: harmless, and already justified (or not) there
            shares = set(task.files) & set(tasks[dep].files)
            cites = any(_references(task.text, path) for path in tasks[dep].files)
            # A rationale that names the dependency ("needs the accessors from TASK-734") is
            # evidence too: some real dependencies (a Cython rebuild, a doc of a finished
            # surface) are not visible as shared or referenced files.
            argued = re.search(rf"\b{re.escape(dep)}\b", task.notes) is not None
            if not shares and not cites and not argued and task.text and tasks[dep].text:
                add(
                    Finding(
                        level="warning",
                        code="unjustified-edge",
                        tasks=[tid, dep],
                        message=f"{tid} → {dep}: no shared file and {tid} never references a file {dep} declares",
                    )
                )
        for other_id, other in tasks.items():
            if other_id == tid or other_id in ancestors[tid] or tid in ancestors.get(other_id, set()):
                continue
            created = [p for p, is_create in other.files.items() if is_create and p not in task.files]
            cited = [p for p in created if _references(task.text, p)]
            if cited:
                add(
                    Finding(
                        level="warning",
                        code="possible-missing-dependency",
                        tasks=[tid, other_id],
                        message=f"{tid} references {', '.join(cited)} created by {other_id} but does not depend on it",
                    )
                )

    for notes, count in Counter(t.notes for t in tasks.values() if t.notes).items():
        if count >= 3:
            same = sorted(tid for tid, t in tasks.items() if t.notes == notes)
            add(
                Finding(
                    level="warning",
                    code="duplicate-notes",
                    tasks=same,
                    message=f"{count} tasks share one parallelism_notes — rationale must be per task",
                )
            )
    if exclusive_semantics:
        for tid in report.exclusive:
            if not tasks[tid].notes:
                add(
                    Finding(
                        level="warning",
                        code="exclusive-without-notes",
                        tasks=[tid],
                        message=f"{tid} is exclusive but names no resource",
                    )
                )
    return report


def format_report(report: GraphReport) -> str:
    """Human-readable rendering of a report."""
    width = max((len(w) for w in report.waves), default=0)
    lines = [
        f"{report.index}: {report.task_count} tasks, {len(report.waves)} waves, max width {width}",
    ]
    for n, wave in enumerate(report.waves, 1):
        lines.append(f"  wave {n}: {', '.join(wave)}")
    if report.exclusive:
        lines.append(f"  exclusive: {', '.join(report.exclusive)}")
    for finding in sorted(report.findings, key=lambda f: (f.level != "error", f.code)):
        lines.append(f"  {finding.level.upper():7} {finding.code}: {finding.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: exit 1 when any index has errors."""
    parser = argparse.ArgumentParser(description="Lint per-spec task graphs (depends_on / parallel).")
    parser.add_argument("indexes", nargs="+", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true", help="Emit JSON reports instead of text.")
    args = parser.parse_args(argv)
    reports = [check_graph(path, args.root) for path in args.indexes]
    if args.json:
        print(json.dumps([r.model_dump() for r in reports], indent=2))  # noqa: T201 - CLI output
    else:
        print("\n\n".join(format_report(r) for r in reports))  # noqa: T201 - CLI output
    return 1 if any(r.errors for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
