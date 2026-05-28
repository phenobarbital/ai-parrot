"""Unit tests for validate_enhanced_html (FEAT-197, TASK-1325)."""
from __future__ import annotations

import sys
import pytest

# Force real modules.
for _mod in (
    "parrot.models.infographic",
    "parrot.tools.infographic_toolkit",
    "parrot.tools._enhance_html_check",
):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _ri
sys.modules["parrot.models.infographic"] = _ri

import parrot.tools.infographic_toolkit as _rtk
sys.modules["parrot.tools.infographic_toolkit"] = _rtk

import parrot.tools._enhance_html_check as _rcheck
sys.modules["parrot.tools._enhance_html_check"] = _rcheck

from parrot.tools._enhance_html_check import validate_enhanced_html  # noqa: E402
from parrot.tools.infographic_toolkit import InfographicValidationError  # noqa: E402
from parrot.models.infographic import JSBundle  # noqa: E402


def _cdn_bundle(
    name: str = "echarts",
    url: str = "https://cdn.example/echarts.min.js",
    sri: str = "sha384-AAAA",
) -> JSBundle:
    return JSBundle(name=name, scope="cdn", url=url, sri_hash=sri)


class TestInlineResourcesAllowed:
    def test_inline_script_ok(self):
        """Inline <script> with no src is always allowed."""
        validate_enhanced_html("<script>alert(1)</script>", [])

    def test_inline_style_ok(self):
        """Inline <style> is always allowed."""
        validate_enhanced_html("<style>body{}</style>", [])

    def test_empty_html_ok(self):
        """Empty HTML doesn't raise."""
        validate_enhanced_html("", [])

    def test_html_without_external_resources_ok(self):
        """HTML with no external scripts or links is always accepted."""
        html = "<html><body><h1>Hello</h1></body></html>"
        validate_enhanced_html(html, [])


class TestWhitelistedCDNAllowed:
    def test_whitelisted_cdn_script_ok(self):
        """<script src> whose URL+SRI matches a CDN bundle is accepted."""
        html = (
            '<script src="https://cdn.example/echarts.min.js" '
            'integrity="sha384-AAAA"></script>'
        )
        validate_enhanced_html(html, [_cdn_bundle()])

    def test_whitelisted_with_other_attrs_ok(self):
        """Extra HTML attributes on the script tag are ignored."""
        html = (
            '<script src="https://cdn.example/echarts.min.js" '
            'integrity="sha384-AAAA" defer crossorigin="anonymous"></script>'
        )
        validate_enhanced_html(html, [_cdn_bundle()])


def _expect_enhance_invalid(fn, *args, **kwargs):
    """Helper: call fn and verify ENHANCE_OUTPUT_INVALID is raised.

    Uses attribute inspection rather than isinstance check to avoid
    class-identity issues when sys.modules is patched in multiple test files.
    """
    with pytest.raises(Exception) as ei:
        fn(*args, **kwargs)
    exc = ei.value
    assert getattr(exc, "code", None) == "ENHANCE_OUTPUT_INVALID", (
        f"Expected ENHANCE_OUTPUT_INVALID but got {exc!r}"
    )
    return exc


class TestBlockedResources:
    def test_external_script_blocked(self):
        """<script src> NOT in whitelist raises ENHANCE_OUTPUT_INVALID."""
        exc = _expect_enhance_invalid(
            validate_enhanced_html,
            '<script src="https://evil/x.js"></script>',
            [_cdn_bundle()],
        )
        assert "external script" in exc.detail["reason"]

    def test_wrong_sri_blocked(self):
        """Correct URL but wrong SRI hash is rejected."""
        html = (
            '<script src="https://cdn.example/echarts.min.js" '
            'integrity="sha384-BBBB"></script>'
        )
        _expect_enhance_invalid(validate_enhanced_html, html, [_cdn_bundle()])

    def test_missing_sri_blocked(self):
        """CDN script without integrity attribute is rejected."""
        html = '<script src="https://cdn.example/echarts.min.js"></script>'
        _expect_enhance_invalid(validate_enhanced_html, html, [_cdn_bundle()])

    def test_external_stylesheet_blocked(self):
        """<link rel=stylesheet href> NOT in whitelist raises."""
        exc = _expect_enhance_invalid(
            validate_enhanced_html,
            '<link rel="stylesheet" href="https://evil/x.css">',
            [_cdn_bundle()],
        )
        assert "stylesheet" in exc.detail["reason"]

    def test_no_bundles_blocks_any_cdn(self):
        """Empty whitelist blocks any external CDN reference."""
        _expect_enhance_invalid(
            validate_enhanced_html,
            '<script src="https://cdn.example/echarts.min.js" '
            'integrity="sha384-AAAA"></script>',
            [],
        )
