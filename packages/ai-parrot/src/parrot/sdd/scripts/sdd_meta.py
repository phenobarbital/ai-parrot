"""Re-export of :mod:`parrot.knowledge.wiki.ledger.sdd_meta` for in-package SDD helpers (FEAT-633).

Same names as the repo-local ``scripts/sdd/sdd_meta.py`` shim, so moved helpers import
``from parrot.sdd.scripts.sdd_meta import …`` without touching the repo-local ``scripts`` package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401
    KNOWN_BRANCHES,
    KNOWN_PROJECTS,
    PROJECT_ALIASES,
    WORK_KIND_FLOW,
    WORKTREE_ROOT,
    DocTaxonomy,
    FlowMeta,
    WorktreePlan,
    emit,
    normalize_project,
    normalize_tag,
    parse,
    parse_taxonomy,
    plan_worktree,
    resolve_flow,
)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI for shell callers: ``parse``, ``taxonomy`` and ``resolve-flow`` subcommands."""
    parser = argparse.ArgumentParser(prog="sdd_meta", description="SDD flow metadata helpers.")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_p = sub.add_parser("parse", help="Print '<type> <base_branch>' for a document.")
    parse_p.add_argument("doc")

    tax_p = sub.add_parser("taxonomy", help="Print the document's projects/tags as JSON.")
    tax_p.add_argument("doc")

    flow_p = sub.add_parser("resolve-flow", help="Print the resolved flow type and base branch as JSON.")
    flow_p.add_argument("--kind")
    flow_p.add_argument("--doc")
    flow_p.add_argument("--type", dest="type_override", choices=["feature", "hotfix"])
    flow_p.add_argument("--base", dest="base_override")

    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    try:
        if args.command == "parse":
            meta = parse(Path(args.doc))
            print(f"{meta.type} {meta.base_branch}")
        elif args.command == "taxonomy":
            tax = parse_taxonomy(Path(args.doc))
            print(json.dumps({"projects": tax.projects, "tags": tax.tags}))
        else:
            meta = resolve_flow(
                kind=args.kind,
                doc_path=Path(args.doc) if args.doc else None,
                type_override=args.type_override,
                base_branch_override=args.base_override,
                config=None,
            )
            print(json.dumps({"type": meta.type, "base_branch": meta.base_branch}))
    except Exception as exc:  # CLI boundary: report and exit non-zero
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
