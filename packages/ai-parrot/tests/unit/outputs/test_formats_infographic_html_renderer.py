"""``get_infographic_html_renderer()`` no longer emits a DeprecationWarning.

FEAT-527 amends FEAT-273 G7: the infographic-HTML lane is a permanent HTML
sibling emission of the A2UI Infographic lane, not a deprecated path.
"""

from __future__ import annotations

import warnings

import pytest

pytest.importorskip("parrot.outputs.formats.infographic_html")


def test_get_infographic_html_renderer_no_deprecation_warning():
    from parrot.outputs.formats import get_infographic_html_renderer

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cls = get_infographic_html_renderer()

    assert cls.__name__ == "InfographicHTMLRenderer"
    assert not [w for w in caught if issubclass(w.category, DeprecationWarning)]
