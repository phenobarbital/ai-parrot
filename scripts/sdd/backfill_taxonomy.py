"""Infer ``projects`` frontmatter for existing SDD docs (FEAT-576). Dry-run by default.

Usage::

    python -m scripts.sdd.backfill_taxonomy [--root .] [--kind spec|brainstorm|proposal|all]
        [--limit N] [--apply]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from scripts.sdd.sdd_meta import KNOWN_PROJECTS, parse_taxonomy

logger = logging.getLogger(__name__)

_GLOBS: dict[str, str] = {
    "spec": "sdd/specs/*.spec.md",
    "brainstorm": "sdd/proposals/*.brainstorm.md",
    "proposal": "sdd/proposals/*.proposal.md",
}

#: A ``packages/<dist>/`` mention. Only kept when ``<dist>`` is in ``KNOWN_PROJECTS``.
_DIST_RE = re.compile(r"packages/([A-Za-z0-9_-]+)/")

#: Top-level ``parrot_*`` distributions imported without the ``packages/`` prefix.
_TOOLS_PKG_RE = re.compile(r"\b(parrot_tools|parrot_loaders|parrot_pipelines)\b")
_TOOLS_PKG_PROJECT: dict[str, str] = {
    "parrot_tools": "ai-parrot-tools",
    "parrot_loaders": "ai-parrot-loaders",
    "parrot_pipelines": "ai-parrot-pipelines",
}

#: SDD tooling paths that aren't under any ``packages/`` distribution.
_SDD_TOOLING_RE = re.compile(r"scripts/sdd/|\.claude/commands/|sdd/templates/")

_DEV_LOOP_RE = re.compile(r"flows/dev_loop")

#: A bare ``parrot/<x>`` mention, i.e. NOT the ``src/parrot/`` tail of a ``packages/<dist>/`` path.
_BARE_PARROT_RE = re.compile(r"(?<!src/)parrot/(?=[A-Za-z0-9_])")


def infer_projects(text: str) -> list[str]:
    """Map code paths mentioned in ``text`` to canonical projects, ordered by first mention.

    Only values in ``KNOWN_PROJECTS`` are returned.
    """
    events: list[tuple[int, str]] = []

    for match in _DIST_RE.finditer(text):
        dist = match.group(1)
        if dist not in KNOWN_PROJECTS:
            continue
        offset = match.start()
        events.append((offset, dist))
        if dist == "ai-parrot-server" and text[match.end() : match.end() + 3] == "ui/":
            events.append((offset, "admin-ui"))

    for match in _TOOLS_PKG_RE.finditer(text):
        events.append((match.start(), _TOOLS_PKG_PROJECT[match.group(1)]))

    for match in _SDD_TOOLING_RE.finditer(text):
        events.append((match.start(), "sdd-tooling"))

    for match in _DEV_LOOP_RE.finditer(text):
        events.append((match.start(), "dev-loop"))

    for match in _BARE_PARROT_RE.finditer(text):
        events.append((match.start(), "ai-parrot"))

    events.sort(key=lambda event: event[0])

    result: list[str] = []
    for _, project in events:
        if project not in result:
            result.append(project)
    return result


_EMPTY_PROJECTS_RE = re.compile(r"^projects:\s*\[\s*\]\s*$")
_TAGS_KEY_RE = re.compile(r"^tags:\s*")


def plan_edit(doc_path: Path) -> str | None:
    """Return the new file text, or ``None`` when no change is needed.

    ``None`` when ``projects`` is already non-empty or nothing was inferred. Inserts lines as
    text before the closing ``---``; never rewrites any other byte.
    """
    text = doc_path.read_text(encoding="utf-8")
    try:
        taxonomy = parse_taxonomy(doc_path)
    except ValidationError as exc:
        logger.warning("Skipping %s: invalid taxonomy frontmatter (%s)", doc_path, exc)
        return None
    if taxonomy.projects:
        return None

    inferred = infer_projects(text)
    if not inferred:
        return None
    projects_line = f"projects: [{', '.join(inferred)}]\n"

    # Same byte-0 '---' rule as parse()/parse_taxonomy(): a real block needs a leading '---'
    # AND a closing '---' later in the file.
    has_block = text.startswith("---") and len(text.split("---", 2)) == 3
    if not has_block:
        prefix = "---\ntype: feature\nbase_branch: dev\n" + projects_line + "tags: []\n---\n"
        return prefix + text

    _, block_body, rest = text.split("---", 2)
    lines = block_body.split("\n")

    new_lines: list[str] = []
    replaced = False
    has_tags = False
    for line in lines:
        stripped = line.strip()
        if _EMPTY_PROJECTS_RE.match(stripped):
            new_lines.append(projects_line.rstrip("\n"))
            replaced = True
            continue
        if _TAGS_KEY_RE.match(stripped):
            has_tags = True
        new_lines.append(line)

    new_block_body = "\n".join(new_lines)
    if not replaced:
        if not new_block_body.endswith("\n"):
            new_block_body += "\n"
        new_block_body += projects_line
    if not has_tags:
        if not new_block_body.endswith("\n"):
            new_block_body += "\n"
        new_block_body += "tags: []\n"

    return "---" + new_block_body + "---" + rest


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns 0. Writes only with ``--apply``; never commits."""
    parser = argparse.ArgumentParser(prog="python -m scripts.sdd.backfill_taxonomy", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--kind", choices=["spec", "brainstorm", "proposal", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0, help="stop after N proposed edits (0 = no limit)")
    parser.add_argument("--apply", action="store_true", help="write the edits (default: dry run)")
    args = parser.parse_args(argv)

    kinds = list(_GLOBS) if args.kind == "all" else [args.kind]
    doc_paths: list[Path] = []
    for kind in kinds:
        doc_paths.extend(sorted(args.root.glob(_GLOBS[kind])))

    changed = 0
    for doc_path in doc_paths:
        if args.limit and changed >= args.limit:
            break
        original_text = doc_path.read_text(encoding="utf-8")
        new_text = plan_edit(doc_path)
        if new_text is None:
            continue
        inferred = infer_projects(original_text)
        try:
            rel = doc_path.relative_to(args.root)
        except ValueError:
            rel = doc_path
        sys.stdout.write(f"{rel}: projects = [{', '.join(inferred)}]\n")
        if args.apply:
            doc_path.write_text(new_text, encoding="utf-8")
        changed += 1

    verb = "changed" if args.apply else "would change"
    sys.stdout.write(f"{changed} docs {verb}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
