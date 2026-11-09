"""Regression guard: a root test module may not leave a real parrot module stubbed.

FEAT-852 / issue:91822a3b8548 — the root-tree counterpart of
``packages/ai-parrot/tests/test_conftest_stub_isolation.py`` (FEAT-617).

Four modules under ``tests/knowledge/pageindex/`` registered a bare stub for
``parrot.knowledge.pageindex`` in ``sys.modules`` so the package ``__init__``
would not run, then loaded submodules by file path. With ``__init__`` suppressed,
the package's own relative imports re-entered ``embedding_store`` while it was
still executing, leaving a half-built module behind: 6 collection errors, 2 red
wiki tests, and four test files silently skipped on every CI run.

The tell is always the same: a ``types.ModuleType`` stand-in has no ``__file__``.
Do not delete this module.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).parent

# Modules that are genuinely importable and have been observed stubbed in this tree.
MUST_NOT_BE_SHADOWED: tuple[str, ...] = (
    "parrot.knowledge.pageindex",
    "parrot.knowledge.pageindex.embedding_store",
    "parrot.knowledge.pageindex.hybrid_search",
    "parrot.knowledge.pageindex.toolkit",
    "parrot.knowledge.pageindex.vector_walk",
)

# Scope: the `parrot.knowledge.*` namespace, where this defect class lives. Other
# stand-ins in tests/ (tests/examples/, tests/mcp/) are pre-existing and tracked as a
# follow-up in the spec; widening this scan to all of `parrot.*` is a separate change.
_STUB_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ModuleType\(\s*[\"']parrot\.knowledge"),
    re.compile(r"sys\.modules\.setdefault\(\s*[\"']parrot\.knowledge"),
)


@pytest.mark.parametrize("name", MUST_NOT_BE_SHADOWED)
def test_real_modules_are_not_shadowed(name: str) -> None:
    """A genuinely importable parrot module must resolve to a real file on disk.

    Runs in the live pytest process, so it sees whatever the modules collected
    before it have done to ``sys.modules``. A failure here names the poisoned module.
    """
    module = importlib.import_module(name)
    assert getattr(module, "__file__", None) is not None, (
        f"{name} resolved to a stand-in with no __file__ — a test module shadowed it and did "
        f"not restore it (see issue:91822a3b8548). Got {module!r}"
    )
    assert Path(module.__file__).exists(), f"{name}.__file__ does not exist on disk"


def test_no_test_module_registers_a_parrot_stub() -> None:
    """No file under tests/ may install a ModuleType stand-in for a parrot package.

    A static source scan: importing every test module to check would be both slow
    and unsafe. This file is skipped — the patterns appear in its own source.
    """
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _STUB_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(TESTS_ROOT.parent)}:{line_no}: {match.group(0)}")
    assert not offenders, (
        "A stub for a real parrot package skips its __init__, so the package's own relative "
        "imports re-enter a half-built module (issue:91822a3b8548). Import the module normally "
        "instead. Offenders:\n  " + "\n  ".join(offenders)
    )
