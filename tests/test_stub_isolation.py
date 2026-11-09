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

**Coverage (issue:aaa24154d0c2).** The guard now spans the whole ``parrot*``
namespace — but through the runtime check, not the source scan. The two halves
below are deliberately scoped differently, and the note above ``_STUB_PATTERNS``
records why a textual rule is the half that cannot be widened safely.
"""
from __future__ import annotations

import importlib
import re
import sys
import warnings
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

# Every way a test file puts a `parrot*` name into sys.modules. Used only to HARVEST
# candidate names for the runtime check below, so a loose match is the right trade:
# a false positive (a name quoted in a comment) costs one dictionary lookup, while a
# miss costs a silently-poisoned module. Correctness is decided at runtime, not here.
_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""sys\.modules\[\s*["'](parrot[\w.]*)["']"""),
    re.compile(r"""sys\.modules\.setdefault\(\s*["'](parrot[\w.]*)["']"""),
    re.compile(r"""monkeypatch\.setitem\(\s*sys\.modules\s*,\s*["'](parrot[\w.]*)["']"""),
    re.compile(r"""ModuleType\(\s*["'](parrot[\w.]*)["']"""),
)

# Known offenders of test_no_harvested_name_is_shadowed, each with the issue that owns it.
# A name listed here is reported but does not fail the suite. Add to this dict ONLY with a
# filed issue id, and delete the entry in the same change that fixes the site.
_QUARANTINED: dict[str, str] = {
    # tests/unit/conftest_db.py:127 stands in for the real parrot/bots/database/toolkits/
    # package to skip its __init__, then loads submodules by file path and re-exports by
    # hand — the FEAT-852 shape, in a conftest, so the stand-in outlives its module.
    "parrot.bots.database.toolkits": "issue:e9c4b6ebef31",
}

# Scope: `parrot.knowledge.*`, and NOT widened to `parrot.*` — verified under
# issue:aaa24154d0c2, which asked for exactly that widening. A source scan cannot
# distinguish the defect from the four legitimate shapes this tree actually uses:
# prose in a comment (tests/auth/test_policy_rules_integration.py, tests/bots/
# test_abstractbot_policy.py, tests/knowledge/wiki/test_cli.py), a save/restore in a
# `finally` (tests/conf/test_aws_credentials_security.py, tests/loaders/
# test_ocr_paddle.py), a stand-in installed in a SUBPROCESS only on ImportError
# (tests/mcp/test_mcp_local_e2e.py, tests/mcp/test_stdio_auth_required_e2e.py), and a
# monkeypatch.setitem the fixture teardown undoes (tests/examples/
# test_a2ui_finance_server_routes.py). Widening the regex would red the suite on all
# four. `parrot.knowledge` stays because it is the one prefix with no such shapes.
# The namespace-wide coverage lives in test_no_harvested_name_is_shadowed instead.
_STUB_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ModuleType\(\s*[\"']parrot\.knowledge"),
    re.compile(r"sys\.modules\.setdefault\(\s*[\"']parrot\.knowledge"),
)


def _iter_test_sources() -> list[Path]:
    """Every .py under tests/ except this file, whose own source holds the patterns."""
    here = Path(__file__).resolve()
    return [p for p in sorted(TESTS_ROOT.rglob("*.py")) if p.resolve() != here]


def _harvest_stubbed_names() -> dict[str, str]:
    """Map each `parrot*` name any test file registers to the first site that does.

    Returns ``{module_name: "<repo-relative path>:<line>"}``.
    """
    sites: dict[str, str] = {}
    for path in _iter_test_sources():
        text = path.read_text(encoding="utf-8")
        for pattern in _NAME_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1)
                if name not in sites:
                    line_no = text.count("\n", 0, match.start()) + 1
                    sites[name] = f"{path.relative_to(TESTS_ROOT.parent)}:{line_no}"
    return sites


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


def test_no_harvested_name_is_shadowed() -> None:
    """No `parrot*` name that tests/ stubs may be left as a stand-in in sys.modules.

    The namespace-wide half of this guard (issue:aaa24154d0c2). It imports nothing:
    it inspects only names already loaded, so it is free of side effects and sees
    exactly what the modules collected *before* it left behind. Names absent from
    ``sys.modules`` are skipped — nothing installed a stand-in for them.

    A conditional stand-in (the FEAT-617 ``_stub_if_absent`` pattern) installs only
    when the real module will not import, so it never reaches this check in an
    environment where the real module exists. If one legitimately does — a
    deliberately unbuilt Cython extension, say — install it conditionally rather
    than unconditionally, and this guard will stay quiet on its own.

    Names in ``_QUARANTINED`` are reported as warnings instead of failures; each one
    carries the ledger issue that owns its fix.
    """
    offenders: list[str] = []
    quarantined: list[str] = []
    for name, site in sorted(_harvest_stubbed_names().items()):
        module = sys.modules.get(name)
        if module is None:
            continue
        file = getattr(module, "__file__", None)
        if file is None:
            problem = f"{name}: stand-in with no __file__, registered at {site}"
        elif not Path(file).exists():
            problem = f"{name}: __file__ {file} does not exist, registered at {site}"
        else:
            continue
        if name in _QUARANTINED:
            quarantined.append(f"{problem} — tracked as {_QUARANTINED[name]}")
        else:
            offenders.append(problem)
    for known in quarantined:
        warnings.warn(f"known stub-isolation offender: {known}", stacklevel=1)
    assert not offenders, (
        "A stub for a real parrot module suppresses its __init__, so the package's own "
        "relative imports re-enter a half-built module (issue:91822a3b8548). Import the "
        "module normally, or install the stand-in only when the real one is absent. "
        "Offenders:\n  " + "\n  ".join(offenders)
    )


def test_no_test_module_registers_a_parrot_stub() -> None:
    """No file under tests/ may install a ModuleType stand-in for a parrot package.

    A static source scan: importing every test module to check would be both slow
    and unsafe. This file is skipped — the patterns appear in its own source.
    """
    offenders: list[str] = []
    for path in _iter_test_sources():
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
