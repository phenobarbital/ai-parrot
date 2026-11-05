"""Documentation-chapter check for ``parrot sdd techwiki check``."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_VALID_POLICIES = ("required", "none")
_DOTTED_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


@dataclass
class DocsDecision:
    """Result of the documentation check."""

    policy: str
    status: str
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)


def resolve_docs_policy(spec_path: Path) -> tuple[str, list[str], list[str]]:
    """Return (policy, pages, api_modules) from the spec's ``docs:`` frontmatter.

    Absent ``docs`` key → ``("unset", [], [])``.
    Malformed → ``("invalid", [], [])``.
    Mirrors ``resolve_policy`` in ``check_e2e_closeout.py``: split on ``'---'``,
    ``yaml.safe_load``, never coerced.

    Args:
        spec_path: Path to the spec file.

    Returns:
        Tuple of (policy, pages list, api_modules list).
    """
    text = spec_path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ("unset", [], [])
    try:
        fm: dict[str, Any] = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return ("invalid", [], [])
    if not isinstance(fm, dict):
        return ("invalid", [], [])

    docs = fm.get("docs")
    if docs is None:
        return ("unset", [], [])
    if not isinstance(docs, dict):
        return ("invalid", [], [])

    policy = docs.get("policy", "unset")
    if policy not in _VALID_POLICIES and policy != "unset":
        return ("invalid", [], [])

    pages = docs.get("pages", [])
    if not isinstance(pages, list):
        return ("invalid", [], [])

    api_modules = docs.get("api_modules", [])
    if not isinstance(api_modules, list):
        api_modules = []

    return (policy, [str(p) for p in pages], [str(m) for m in api_modules])


def _outside_root(page: str, root: Path) -> bool:
    """Return True when ``page`` is absolute or resolves outside ``root``."""
    candidate = Path(page)
    if candidate.is_absolute() or ".." in candidate.parts:
        return True
    try:
        (root / candidate).resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False


def _has_title(text: str) -> bool:
    """Return True when the page has a frontmatter ``title:`` or a level-1 heading."""
    parts = text.split("---", 2)
    if text.startswith("---") and len(parts) >= 3:
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            fm = {}
        if isinstance(fm, dict) and fm.get("title"):
            return True
        text = parts[2]
    return any(line.startswith("# ") for line in text.splitlines())


def evaluate_docs(policy: str, pages: list[str], api_modules: list[str], root: Path) -> DocsDecision:
    """Evaluate the documentation state for a spec.

    The result is advisory: no status ever blocks closeout.

    Args:
        policy: Resolved policy string.
        pages: List of declared wiki page paths.
        api_modules: List of dotted module names.
        root: Repository root.

    Returns:
        DocsDecision with status and reason codes.
    """
    if policy == "invalid":
        return DocsDecision(policy=policy, status="invalid", reason_codes=["docs_invalid"])
    if policy == "none":
        return DocsDecision(policy=policy, status="skipped", reason_codes=["docs_policy_none"])
    if policy == "unset":
        return DocsDecision(policy=policy, status="skipped", reason_codes=["docs_unset"])

    decision = DocsDecision(policy=policy, status="ok")
    reasons: list[str] = []

    for page in pages:
        if _outside_root(page, root):
            decision.status = "invalid"
            reasons.append("docs_page_outside_root")
            continue
        path = root / page
        if not path.is_file():
            decision.missing.append(page)
            reasons.append("docs_page_missing")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            decision.empty.append(page)
            reasons.append("docs_page_empty")
            continue
        decision.present.append(page)
        if not _has_title(text):
            reasons.append("docs_page_no_title")

    if not pages:
        reasons.append("docs_no_pages")
    if any(not _DOTTED_MODULE.match(module) for module in api_modules):
        reasons.append("docs_api_module_syntax")

    decision.reason_codes = sorted(set(reasons))
    if decision.status != "invalid" and decision.reason_codes:
        decision.status = "warning"
    return decision
