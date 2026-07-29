"""G1 regression guard (spec §4 `test_no_exec_in_a2ui_subtree`).

Static check: no ``exec(`` / ``eval(`` appears anywhere under the A2UI subtrees in either
package. This is the whole point of FEAT-273 — envelopes are data, never code — so a
future change that reintroduces the `BaseRenderer.execute_code` vulnerability class must
fail CI here.
"""

from pathlib import Path

import pytest

_PACKAGES = Path(__file__).resolve().parents[4]
_SUBTREES = [
    _PACKAGES / "ai-parrot" / "src" / "parrot" / "outputs" / "a2ui",
    _PACKAGES / "ai-parrot-visualizations" / "src" / "parrot" / "outputs" / "a2ui_renderers",
]

_FORBIDDEN = ("exec(", "eval(")


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
    assert len(scanned) >= 10, f"expected to scan the a2ui subtrees, found {len(scanned)} files"
