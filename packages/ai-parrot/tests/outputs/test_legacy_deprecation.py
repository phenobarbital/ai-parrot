"""Legacy format deprecation-warning tests (TASK-1740 / Module 12, G7)."""

import warnings

import pytest

from parrot.models.outputs import OutputMode
from parrot.outputs.formats import (
    _A2UI_REPLACEMENTS,
    get_infographic_html_renderer,
    get_renderer,
)

_REPLACED = [
    OutputMode.ECHARTS,
    OutputMode.MAP,
    OutputMode.HTML,
    OutputMode.TABLE,
    OutputMode.CARD,
    OutputMode.JINJA2,
    OutputMode.TEMPLATE_REPORT,
    OutputMode.STRUCTURED_CHART,
    OutputMode.STRUCTURED_TABLE,
    OutputMode.STRUCTURED_MAP,
    OutputMode.APPLICATION,
]

_KEPT = [
    OutputMode.JSON,
    OutputMode.YAML,
    OutputMode.MARKDOWN,
    OutputMode.SLACK,
    OutputMode.WHATSAPP,
    OutputMode.TERMINAL,
]


class TestLegacyDeprecationWarnings:
    @pytest.mark.parametrize("mode", _REPLACED)
    def test_replaced_mode_warning_matrix(self, mode):
        """Each replaced mode emits a DeprecationWarning naming the A2UI replacement."""
        with pytest.warns(DeprecationWarning, match="A2UI"):
            with contextlib_suppress_value_error():
                get_renderer(mode)

    @pytest.mark.parametrize("mode", _KEPT)
    def test_kept_modes_no_warning(self, mode):
        """Kept modes emit no FEAT-273/A2UI DeprecationWarning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with contextlib_suppress_value_error():
                get_renderer(mode)
        a2ui_warnings = [
            w for w in caught
            if issubclass(w.category, DeprecationWarning) and "A2UI" in str(w.message)
        ]
        assert a2ui_warnings == []

    def test_infographic_html_path_only_warns(self):
        # HTML path warns...
        with pytest.warns(DeprecationWarning, match="A2UI"):
            with contextlib_suppress_import_error():
                get_infographic_html_renderer()
        # ...JSON path does not (INFOGRAPHIC not in the replacement table).
        assert OutputMode.INFOGRAPHIC not in _A2UI_REPLACEMENTS

    def test_infographic_html_missing_satellite_actionable_error(self, monkeypatch):
        """Without ai-parrot-visualizations installed, the accessor names the fix."""
        import sys
        # None in sys.modules makes the import raise ModuleNotFoundError with
        # exc.name set — the same failure mode as the satellite not installed.
        monkeypatch.setitem(
            sys.modules, "parrot.outputs.formats.infographic_html", None
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pytest.raises(ImportError, match="ai-parrot-visualizations"):
                get_infographic_html_renderer()

    def test_unregistered_mode_error_unchanged(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pytest.raises(ValueError, match="No renderer registered for mode"):
                get_renderer(OutputMode.CHART)

    def test_replacements_cover_only_replaced_modes(self):
        assert set(_A2UI_REPLACEMENTS) == set(_REPLACED)


# -- small helpers (avoid importing heavy modules that legacy renderers may need) --

import contextlib


@contextlib.contextmanager
def contextlib_suppress_value_error():
    """Legacy renderer modules may not import in a bare env; ignore that here."""
    try:
        yield
    except (ValueError, ImportError, ModuleNotFoundError):
        pass


@contextlib.contextmanager
def contextlib_suppress_import_error():
    try:
        yield
    except (ImportError, ModuleNotFoundError):
        pass
