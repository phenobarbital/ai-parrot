"""No live doc or prompt teaches `/sdd-spec --type hotfix` after FEAT-698 — TASK-4439."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_INVOCATION = re.compile(r"[/$]sdd-spec\s+\S+.*--type hotfix")
_SCAN = (".claude", ".agents", ".agent", "scripts", "docs", "sdd/templates")
_SKIP_PARTS = {"worktrees", "__pycache__"}
_SKIP_SUFFIXES = {".pyc", ".so", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2"}


def _hits() -> list[str]:
    roots = [_ROOT / s for s in _SCAN] + sorted(_ROOT.glob("packages/*/src/parrot/flows"))
    found: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(_ROOT)
            if not path.is_file() or path.suffix in _SKIP_SUFFIXES or _SKIP_PARTS & set(rel.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _INVOCATION.search(line):
                    found.append(f"{rel.as_posix()}:{lineno}")
    return found


def test_no_live_type_hotfix_references() -> None:
    hits = _hits()
    assert not hits, f"--type hotfix is still taught in: {hits} (FEAT-698 removed it; use /sdd-brief)"
