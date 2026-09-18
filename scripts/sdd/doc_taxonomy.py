"""List SDD docs by ``projects``/``tags`` frontmatter (FEAT-576).

Usage::

    python -m scripts.sdd.doc_taxonomy [--root .] [--kind spec|brainstorm|proposal|all]
        [--project P ...] [--tag T ...] [--paths-only | --json | --summary]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from scripts.sdd.sdd_meta import normalize_project, normalize_tag, parse_taxonomy

logger = logging.getLogger(__name__)

DocKind = Literal["spec", "brainstorm", "proposal", "all"]

_GLOBS: dict[str, str] = {
    "spec": "sdd/specs/*.spec.md",
    "brainstorm": "sdd/proposals/*.brainstorm.md",
    "proposal": "sdd/proposals/*.proposal.md",
}


class TaxonomyRow(BaseModel):
    """One SDD document and its taxonomy."""

    path: str
    kind: DocKind
    projects: list[str]
    tags: list[str]


def collect(root: Path, kind: DocKind = "all") -> list[TaxonomyRow]:
    """Scan sdd/specs/*.spec.md and sdd/proposals/*.{brainstorm,proposal}.md under ``root``.

    A doc whose frontmatter fails validation is skipped with a logged warning.
    """
    doc_kinds = _GLOBS.keys() if kind == "all" else [kind]
    rows: list[TaxonomyRow] = []
    for doc_kind in doc_kinds:
        pattern = _GLOBS[doc_kind]
        for path in root.glob(pattern):
            try:
                taxonomy = parse_taxonomy(path)
            except ValidationError as exc:
                logger.warning("Skipping %s: invalid taxonomy (%s)", path, exc)
                continue
            rows.append(
                TaxonomyRow(
                    path=path.relative_to(root).as_posix(),
                    kind=doc_kind,
                    projects=taxonomy.projects,
                    tags=taxonomy.tags,
                )
            )
    rows.sort(key=lambda row: row.path)
    return rows


def filter_rows(rows: list[TaxonomyRow], projects: list[str], tags: list[str]) -> list[TaxonomyRow]:
    """AND across the two flags, OR within each; filter values are normalized first."""
    norm_projects = {normalize_project(value) for value in projects}
    norm_tags = {normalize_tag(value) for value in tags}
    return [
        row
        for row in rows
        if (not norm_projects or norm_projects & set(row.projects)) and (not norm_tags or norm_tags & set(row.tags))
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 on a successful scan, 2 on bad arguments."""
    parser = argparse.ArgumentParser(prog="python -m scripts.sdd.doc_taxonomy", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--kind", choices=["spec", "brainstorm", "proposal", "all"], default="all")
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--paths-only", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    rows = collect(args.root, args.kind)
    try:
        rows = filter_rows(rows, args.project, args.tag)
    except ValueError as exc:
        sys.stderr.write(f"error: invalid --project/--tag value: {exc}\n")
        return 2

    if args.paths_only:
        for row in rows:
            sys.stdout.write(f"{row.path}\n")
    elif args.json:
        sys.stdout.write(json.dumps([row.model_dump() for row in rows], indent=2) + "\n")
    elif args.summary:
        project_counts: Counter[str] = Counter(project for row in rows for project in row.projects)
        tag_counts: Counter[str] = Counter(tag for row in rows for tag in row.tags)
        sys.stdout.write(f"{len(rows)} docs\n\n")
        sys.stdout.write("PROJECTS\n")
        for value, count in sorted(project_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            sys.stdout.write(f"{count}\t{value}\n")
        sys.stdout.write("\nTAGS\n")
        for value, count in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            sys.stdout.write(f"{count}\t{value}\n")
    else:
        for row in rows:
            sys.stdout.write(f"{row.path}\t{row.kind}\t{','.join(row.projects)}\t{','.join(row.tags)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
