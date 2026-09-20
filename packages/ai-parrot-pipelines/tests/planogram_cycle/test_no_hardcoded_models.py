"""Guard: no hard-coded model literal and no Google-only client under parrot_pipelines (FEAT-574, spec Module 6)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import List

import parrot_pipelines
from parrot_pipelines.abstract import AbstractPipeline

_ROOT = Path(parrot_pipelines.__file__).parent

#: Spec §5: zero matches for these three. (`llm.detect_objects` and `no_memory` are legitimate.)
_FORBIDDEN = re.compile(r'model="gemini|roi_client|GoogleGenAIClient')

#: handlers/ was excluded until TASK-3447 removed its GoogleGenAIClient; only caches are skipped now.
_EXCLUDED_DIRS = {"__pycache__"}


def _offenders() -> List[str]:
    """Return 'relative/path.py:LINE: text' for every forbidden line outside the excluded folders."""
    found: List[str] = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT)
        if _EXCLUDED_DIRS.intersection(rel.parts):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _FORBIDDEN.search(line):
                found.append(f"{rel}:{number}: {line.strip()}")
    return found


def test_no_hardcoded_models_or_roi_client() -> None:
    offenders = _offenders()
    assert not offenders, "Provider-neutrality violations (FEAT-574):\n" + "\n".join(offenders)


def test_scan_root_is_the_package_under_test() -> None:
    """Guards against a vacuous pass: the scan must actually see the planogram sources."""
    assert (_ROOT / "planogram" / "plan.py").is_file()
    assert (_ROOT / "abstract.py").is_file()


def test_abstract_pipeline_has_no_roi_client_attribute() -> None:
    """'roi_client' is not built (nor mentioned) by AbstractPipeline.__init__."""
    source = inspect.getsource(AbstractPipeline.__init__)
    assert "roi_client" not in source
    assert "parrot.clients.google" not in source
