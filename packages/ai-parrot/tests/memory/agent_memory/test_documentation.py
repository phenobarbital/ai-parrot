"""Check the required FEAT-892 documentation through the registered pytest runner.

The techwiki check resolves pages against ``--root``. ``import parrot`` changes the process working directory, so every
path handed to the check here is absolute; a relative ``--root .`` silently points at another checkout and reports
every page as missing.
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SPEC = ROOT / "sdd" / "specs" / "agent-memory-mixin.spec.md"
REQUIRED_PAGES = [
    "wiki/memory/agent-memory.md",
    "wiki/memory/user-memory.md",
    "wiki/memory/memory-dynamics.md",
]
REQUIRED_SECTIONS = [
    "## Purpose",
    "## Public API",
    "## Configuration & Parameters",
    "## Usage Examples",
    "## Gotchas",
    "## Related",
]
_REF_LINK = re.compile(r"\]\(ref:([^)]+)\)")
_RELATIVE_LINK = re.compile(r"\]\((?!ref:|https?:|#)([^)#]+)")


def _resolve_reference(target: str) -> bool:
    """Return whether a dotted ``ref:`` target names an importable module, class or attribute."""
    parts = target.split(".")
    for split in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        try:
            for attribute in parts[split:]:
                obj = getattr(obj, attribute)
        except AttributeError:
            return False
        return True
    return False


@pytest.mark.parametrize("page", REQUIRED_PAGES)
def test_required_pages_follow_the_techwiki_template(page: str) -> None:
    """Each required page exists, has a title, every required section and at least one API reference."""
    content = (ROOT / page).read_text(encoding="utf-8")
    assert content.strip(), f"{page} is empty"
    assert "title:" in content[:200] or "# " in content[:200], f"{page} has no title"
    for section in REQUIRED_SECTIONS:
        assert section in content, f"{page} is missing {section}"
    assert _REF_LINK.search(content), f"{page} has no ref: API links"


@pytest.mark.parametrize("page", REQUIRED_PAGES)
def test_reference_links_point_at_real_public_symbols(page: str) -> None:
    """Every ``ref:`` link resolves to a module, class or attribute that exists."""
    content = (ROOT / page).read_text(encoding="utf-8")
    unresolved = sorted({target for target in _REF_LINK.findall(content) if not _resolve_reference(target)})
    assert not unresolved, f"{page} has unresolved ref: links: {unresolved}"


@pytest.mark.parametrize("page", REQUIRED_PAGES)
def test_relative_links_resolve_to_existing_files(page: str) -> None:
    """Relative markdown links do not point at files that are not in the repository."""
    page_path = ROOT / page
    content = page_path.read_text(encoding="utf-8")
    dead = sorted(
        target for target in set(_RELATIVE_LINK.findall(content)) if not (page_path.parent / target).resolve().exists()
    )
    assert not dead, f"{page} has dead relative links: {dead}"


def test_techwiki_decision_is_ok_for_the_spec() -> None:
    """The check logic reports every declared page present with status ok (absolute root)."""
    from parrot.sdd.techwiki.check import evaluate_docs, resolve_docs_policy

    policy, pages, api_modules = resolve_docs_policy(SPEC)
    decision = evaluate_docs(policy, pages, api_modules, ROOT)

    assert policy == "required"
    assert sorted(pages) == sorted(REQUIRED_PAGES)
    assert decision.status == "ok", decision
    assert sorted(decision.present) == sorted(REQUIRED_PAGES)
    assert decision.missing == [] and decision.empty == [], decision


def test_techwiki_check_command_reports_ok() -> None:
    """``parrot sdd techwiki check`` completes with a JSON report that is ok; a failure fails this test."""
    completed = subprocess.run(
        [
            "parrot",
            "sdd",
            "techwiki",
            "check",
            "--spec",
            str(SPEC),
            "--root",
            str(ROOT),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    json_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    assert json_lines, f"no JSON report in output (exit {completed.returncode}): {completed.stdout[-500:]}"
    report = json.loads(json_lines[-1])

    assert report["status"] == "ok", report
    assert sorted(report["present"]) == sorted(REQUIRED_PAGES), report
    assert report["missing"] == [] and report["empty"] == [], report
