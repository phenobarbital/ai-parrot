"""Tests for scripts/generate_a2ui_css.py's `--check` behavior + the
vendored-asset freshness check TASK-2791 wired into CI (FEAT-522 TASK-2794).

Location mirrors `tests/scripts/test_generate_tool_registry.py`'s own
precedent exactly (same repo, same "script under scripts/, tests under
tests/scripts/" convention) — `scripts/generate_a2ui_css.py`'s own Test
Specification section deferred these to this task rather than sketching
placeholders as real tests.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: `generate_a2ui_css.py` shells out to the Tailwind v4 CLI (`npm install`
#: into an isolated temp dir — see the script's own `_run_tailwind_cli()`
#: docstring). Skip the CLI-invoking tests with a clear reason rather than
#: failing/hanging if `npm`/`node` aren't present in the test environment
#: (Key Constraints: "no reliance on a developer's local Tailwind CLI
#: installation path").
_HAS_NPM = shutil.which("npm") is not None

pytestmark = pytest.mark.skipif(not _HAS_NPM, reason="npm not available — cannot invoke the Tailwind v4 CLI")


def _generate_a2ui_css_module():
    """Import `scripts/generate_a2ui_css.py` as a module (not subprocess) —
    faster, and gives precise assertions on WHAT drifted, not just the exit
    code (Implementation Notes: "Prefer testing the script's internal
    functions directly ... over subprocess")."""
    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import generate_a2ui_css

    return generate_a2ui_css


def test_generate_a2ui_css_check_mode_clean(monkeypatch):
    """On the real, just-generated checkout (interactive_html.py and the
    committed tailwind.generated.css are in sync), `--check` exits 0."""
    gen = _generate_a2ui_css_module()
    monkeypatch.setattr(sys, "argv", ["generate_a2ui_css.py", "--check"])
    assert gen.main() == 0


def test_generate_a2ui_css_check_mode_stale(tmp_path, monkeypatch):
    """Simulates adding a new literal class string WITHOUT regenerating —
    `--check` must exit 1. Uses a TEMP COPY of the scanned source (seeded
    from the real file's current content) plus a temp copy of the committed
    generated CSS (seeded from the real, fresh committed content) — the
    real, committed `interactive_html.py`/`tailwind.generated.css` are never
    mutated. `generate_a2ui_css.py` hardcodes `INTERACTIVE_HTML_PATH`/
    `OUTPUT_CSS_PATH` as module-level constants with no CLI override flag;
    since Python function bodies resolve module globals dynamically at call
    time (not bound at def-time), monkeypatching those two module
    attributes redirects `main()`'s I/O to the temp copies without needing
    such a flag.
    """
    gen = _generate_a2ui_css_module()
    real_interactive_html_path = gen.INTERACTIVE_HTML_PATH

    stale_source = real_interactive_html_path.read_text(encoding="utf-8")
    stale_source += '\n_TASK_2794_TEST_MARKER = "a2ui-test-stale-marker"\n'
    tmp_source = tmp_path / "interactive_html.py"
    tmp_source.write_text(stale_source, encoding="utf-8")

    # Seed with the CURRENT (real, fresh) committed content, so the only
    # drift `--check` should detect is the one new class added above.
    tmp_output = tmp_path / "tailwind.generated.css"
    tmp_output.write_text(gen.OUTPUT_CSS_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(gen, "INTERACTIVE_HTML_PATH", tmp_source)
    monkeypatch.setattr(gen, "OUTPUT_CSS_PATH", tmp_output)
    # main()'s own status messages call `OUTPUT_CSS_PATH.relative_to(WORKSPACE_ROOT)`
    # purely for display — repoint WORKSPACE_ROOT too so that call doesn't
    # raise ValueError against a path outside the real repo (tmp_path).
    monkeypatch.setattr(gen, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["generate_a2ui_css.py", "--check"])

    assert gen.main() == 1
    # The real, committed files were never touched.
    assert "a2ui-test-stale-marker" not in real_interactive_html_path.read_text(encoding="utf-8")


def test_generate_a2ui_css_vendor_check():
    """FEAT-522 spec §3 Module 6's vendored-asset freshness check.

    TASK-2791 implemented this as "a second, adjacent CI step" — a raw
    inline Python block in `.github/workflows/ci.yml` (per its own
    Completion Note), deliberately NOT folded into `generate_a2ui_css.py
    --check` nor exposed as an importable function anywhere. There is
    therefore no single production function this test can import and call
    with a monkeypatched failure case. Instead, this test exercises the
    SAME detection logic the CI step performs (introspect the installed
    `folium`/`MarkerCluster` package's live `default_js`/`default_css`
    names against `_map_vendor.VENDORED_ASSET_PATHS`) against a
    deliberately-corrupted COPY of that mapping, confirming the check
    correctly flags both failure modes it is designed to catch: a missing
    name mapping, and a mapped-but-missing-on-disk file. This is the
    positive-and-negative-case complement to TASK-2785's
    `test_all_folium_default_resources_have_a_vendored_path` (which only
    asserts the CURRENT, correct mapping — never exercises a broken one).
    """
    import folium
    import folium.plugins as fp

    sys.path.insert(
        0,
        str(REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"),
    )
    from parrot.outputs.a2ui_renderers._map_vendor import VENDORED_ASSET_PATHS

    m = folium.Map()
    mc = fp.MarkerCluster()
    names = {n for n, _ in m.default_js} | {n for n, _ in m.default_css}
    names |= {n for n, _ in mc.default_js} | {n for n, _ in mc.default_css}

    def _check(paths: dict[str, Path]) -> tuple[list[str], list[str]]:
        missing_names = sorted(names - set(paths))
        missing_files = sorted(n for n in names if n in paths and not paths[n].exists())
        return missing_names, missing_files

    # Positive case: the REAL, current mapping has no gaps (mirrors
    # TASK-2785's own unit test).
    missing_names, missing_files = _check(VENDORED_ASSET_PATHS)
    assert not missing_names
    assert not missing_files

    # Negative case 1: simulate a future folium resource with no vendored
    # mapping at all.
    corrupted_missing_name = {k: v for k, v in VENDORED_ASSET_PATHS.items() if k != "leaflet"}
    missing_names, missing_files = _check(corrupted_missing_name)
    assert missing_names == ["leaflet"]
    assert not missing_files

    # Negative case 2: simulate a mapped name whose vendored file was
    # deleted from disk without updating the mapping.
    corrupted_missing_file = dict(VENDORED_ASSET_PATHS)
    corrupted_missing_file["leaflet"] = Path("/nonexistent/leaflet-does-not-exist.js")
    missing_names, missing_files = _check(corrupted_missing_file)
    assert not missing_names
    assert missing_files == ["leaflet"]
