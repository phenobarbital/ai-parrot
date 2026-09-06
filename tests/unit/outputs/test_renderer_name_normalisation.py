"""``get_a2ui_renderer`` must resolve hyphenated renderer ids (2026-09-05).

``recipe.render.profile`` is ``"interactive-html"`` while the satellite module is
``parrot.outputs.a2ui_renderers.interactive_html``; before the fix the resolver
imported the literal name and every replay from a host that had not imported the
module by other means failed with ``ModuleNotFoundError``.
"""

from __future__ import annotations

import importlib.util

import pytest

from parrot.outputs.a2ui.renderers import get_a2ui_renderer

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.a2ui_renderers") is None,
    reason="ai-parrot-visualizations not installed",
)


def test_hyphenated_renderer_id_resolves_to_underscored_module():
    cls = get_a2ui_renderer("interactive-html")
    assert cls.__module__ == "parrot.outputs.a2ui_renderers.interactive_html"


def test_unknown_renderer_still_raises_import_error():
    with pytest.raises(ImportError, match="Cannot import A2UI renderer"):
        get_a2ui_renderer("no-such-renderer")
