"""G1 regression guard (spec §4 `test_no_exec_in_a2ui_subtree`).

Static check: no ``exec(`` / ``eval(`` appears anywhere under the A2UI subtrees in either
package. This is the whole point of FEAT-273 — envelopes are data, never code — so a
future change that reintroduces the `BaseRenderer.execute_code` vulnerability class must
fail CI here.

Coverage over the COMPLETE tree (TASK-2548, spec §7 "test_no_exec sobre el
árbol completo"): ``_python_files()``'s ``rglob("*.py")`` was already
recursive over the full ``a2ui``/``a2ui_renderers`` package trees before this
task — including every module TASK-2532 through TASK-2547 added
(``catalog/basic/``, ``catalog/parrot/``, ``compat.py``, ``recipes/migrate.py``,
``renderers/degrade.py``, ``catalog/export.py``, ...). What was missing was a
guard that the scan actually REACHES all of them (a future path move/rename
could silently narrow coverage without failing here) — added below as an
explicit membership check, alongside a file-count floor raised from the
original placeholder ``10`` to reflect the tree's real size (47 files as of
this task, verified via ``find ... -name '*.py' | wc -l``).
"""

from pathlib import Path

import pytest

_PACKAGES = Path(__file__).resolve().parents[4]
_SUBTREES = [
    _PACKAGES / "ai-parrot" / "src" / "parrot" / "outputs" / "a2ui",
    _PACKAGES / "ai-parrot-visualizations" / "src" / "parrot" / "outputs" / "a2ui_renderers",
]

_FORBIDDEN = ("exec(", "eval(")

#: A representative sample of modules added across TASK-2532-2547 — an
#: explicit presence check (not just a raw count) that the recursive scan
#: below still reaches every one of them.
_EXPECTED_MODULES = (
    "a2ui/compat.py",
    "a2ui/catalog/basic/__init__.py",
    "a2ui/catalog/basic/functions.py",
    "a2ui/catalog/basic/inputs.py",
    "a2ui/catalog/basic/layout.py",
    "a2ui/catalog/basic/media.py",
    "a2ui/catalog/parrot/__init__.py",
    "a2ui/catalog/parrot/chart.py",
    "a2ui/catalog/parrot/datatable.py",
    "a2ui/catalog/parrot/form.py",
    "a2ui/catalog/parrot/infocard.py",
    "a2ui/catalog/parrot/infographic.py",
    "a2ui/catalog/parrot/kpicard.py",
    "a2ui/catalog/parrot/map.py",
    "a2ui/catalog/parrot/report.py",
    "a2ui/catalog/parrot/timeline.py",
    "a2ui/catalog/export.py",
    "a2ui/recipes/migrate.py",
    "a2ui/renderers/degrade.py",
    "a2ui_renderers/ssr_html.py",
    "a2ui_renderers/pdf.py",
    "a2ui_renderers/interactive_html.py",
    "a2ui_renderers/echarts.py",
    "a2ui_renderers/folium_map.py",
    "a2ui_renderers/adaptive_cards.py",
)


def _python_files():
    for subtree in _SUBTREES:
        if subtree.is_dir():
            yield from subtree.rglob("*.py")


@pytest.mark.parametrize("forbidden", _FORBIDDEN)
def test_no_exec_in_a2ui_subtree(forbidden):
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if forbidden in line:
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, (
        f"G1 violation — {forbidden!r} found under the A2UI subtrees:\n"
        + "\n".join(offenders)
    )


def test_subtrees_exist_and_are_scanned():
    # Guard against the check silently scanning nothing (e.g. path drift).
    scanned = list(_python_files())
    assert len(scanned) >= 40, f"expected to scan the full a2ui subtrees, found {len(scanned)} files"


def test_subtrees_include_every_task_2532_2547_module():
    # Guard against the scan silently narrowing (e.g. a future rglob pattern
    # change) while still passing the raw count above.
    scanned = [str(p).replace("\\", "/") for p in _python_files()]
    missing = [m for m in _EXPECTED_MODULES if not any(s.endswith(m) for s in scanned)]
    assert not missing, f"a2ui subtree scan is missing expected modules: {missing}"
