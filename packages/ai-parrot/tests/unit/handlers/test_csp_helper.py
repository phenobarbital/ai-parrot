"""Unit tests for the CSP header builder (FEAT-197, TASK-1322)."""
from __future__ import annotations

import sys

# Force real handlers.csp module.
sys.modules.pop("parrot.handlers.csp", None)
import parrot.handlers.csp as _real_csp
sys.modules["parrot.handlers.csp"] = _real_csp

from parrot.handlers.csp import build_csp_headers, frame_ancestors_from_env  # noqa: E402


class TestBuildCSPHeaders:
    """Tests for build_csp_headers()."""

    def test_default_frame_ancestors_self(self):
        """With no js_bundles and default frame_ancestors, CSP should include frame-ancestors 'self'."""
        hdrs = build_csp_headers()
        assert "frame-ancestors 'self'" in hdrs["Content-Security-Policy"]

    def test_env_provided_ancestors(self):
        """Custom frame_ancestors string is included verbatim."""
        hdrs = build_csp_headers(frame_ancestors="https://a.example https://b.example")
        csp = hdrs["Content-Security-Policy"]
        assert "frame-ancestors https://a.example https://b.example" in csp

    def test_cdn_origin_added_to_script_src(self):
        """CDN bundle origin should appear in script-src."""
        # Use plain object with the required attributes.
        class _FakeBundle:
            scope = "cdn"
            url = "https://cdn.example/echarts.min.js"

        hdrs = build_csp_headers(js_bundles=[_FakeBundle()])
        assert "https://cdn.example" in hdrs["Content-Security-Policy"]

    def test_inline_bundle_not_added_to_script_src(self):
        """Inline bundles should NOT add any origin to script-src."""
        class _FakeBundle:
            scope = "inline"
            url = None

        hdrs = build_csp_headers(js_bundles=[_FakeBundle()])
        csp = hdrs["Content-Security-Policy"]
        # Only 'self' and 'unsafe-inline' in script-src
        assert "script-src 'self' 'unsafe-inline'" in csp

    def test_static_headers_present(self):
        """X-Content-Type-Options and Referrer-Policy must always be present."""
        hdrs = build_csp_headers()
        assert hdrs["X-Content-Type-Options"] == "nosniff"
        assert hdrs["Referrer-Policy"] == "no-referrer"

    def test_default_src_self_present(self):
        """default-src 'self' must be in the policy."""
        hdrs = build_csp_headers()
        assert "default-src 'self'" in hdrs["Content-Security-Policy"]

    def test_style_src_unsafe_inline(self):
        """style-src 'self' 'unsafe-inline' must be in the policy."""
        hdrs = build_csp_headers()
        assert "style-src 'self' 'unsafe-inline'" in hdrs["Content-Security-Policy"]

    def test_img_src_data(self):
        """img-src must allow 'self' and data: URIs."""
        hdrs = build_csp_headers()
        assert "img-src 'self' data:" in hdrs["Content-Security-Policy"]

    def test_multiple_cdn_origins_deduplicated(self):
        """Multiple bundles from the same origin should produce one entry."""
        class _FakeBundle:
            scope = "cdn"
            url = "https://cdn.example/a.js"

        hdrs = build_csp_headers(js_bundles=[_FakeBundle(), _FakeBundle()])
        csp = hdrs["Content-Security-Policy"]
        # Count occurrences — should be exactly one
        assert csp.count("https://cdn.example") == 1


class TestFrameAncestorsFromEnv:
    """Tests for frame_ancestors_from_env()."""

    def test_default_when_unset(self, monkeypatch):
        """Returns default ''self'' when env var is absent."""
        monkeypatch.delenv("INFOGRAPHIC_FRAME_ANCESTORS", raising=False)
        assert frame_ancestors_from_env() == "'self'"

    def test_csv_env_converted_to_space_separated(self, monkeypatch):
        """CSV env var is normalised to space-separated list."""
        monkeypatch.setenv("INFOGRAPHIC_FRAME_ANCESTORS", "https://a.example,https://b.example")
        result = frame_ancestors_from_env()
        assert result == "https://a.example https://b.example"

    def test_empty_env_uses_default(self, monkeypatch):
        """Empty env var falls back to default."""
        monkeypatch.setenv("INFOGRAPHIC_FRAME_ANCESTORS", "")
        assert frame_ancestors_from_env() == "'self'"
