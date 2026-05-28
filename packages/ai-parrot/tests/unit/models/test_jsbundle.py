"""Unit tests for JSBundle model validators (FEAT-197, TASK-1319)."""
from __future__ import annotations

import sys
import pytest

# Force real parrot.models.infographic module (bypass conftest stub).
_stub = sys.modules.pop("parrot.models.infographic", None)
import parrot.models.infographic as _real_infographic
sys.modules["parrot.models.infographic"] = _real_infographic

from parrot.models.infographic import JSBundle  # noqa: E402


class TestJSBundleValidation:
    """Validation tests for the JSBundle model."""

    def test_inline_ok(self):
        """scope='inline' with inline source is valid."""
        b = JSBundle(name="x", scope="inline", inline="/* js */")
        assert b.scope == "inline"
        assert b.inline == "/* js */"

    def test_cdn_ok(self):
        """scope='cdn' with url and sri_hash is valid."""
        b = JSBundle(
            name="echarts",
            scope="cdn",
            url="https://cdn/x.js",
            sri_hash="sha384-AAAA",
        )
        assert b.scope == "cdn"
        assert b.url == "https://cdn/x.js"
        assert b.sri_hash == "sha384-AAAA"

    @pytest.mark.parametrize("kwargs", [
        dict(scope="cdn", url=None, sri_hash="sha384-AAAA"),
        dict(scope="cdn", url="https://cdn/x.js", sri_hash=None),
        dict(scope="cdn", url="https://cdn/x.js", sri_hash="sha384-AAA", inline="oops"),
        dict(scope="inline", inline=None),
        dict(scope="inline", inline="x", url="https://cdn/x.js"),
        dict(scope="inline", inline="x", sri_hash="sha384-AAA"),
    ])
    def test_invalid_combinations_rejected(self, kwargs):
        """Invalid field combinations should raise ValueError."""
        with pytest.raises(ValueError):
            JSBundle(name="x", **kwargs)

    def test_default_scope_is_inline(self):
        """Default scope should be 'inline'."""
        b = JSBundle(name="x", inline="/* code */")
        assert b.scope == "inline"

    def test_cdn_bundle_round_trips(self):
        """CDN bundle should survive model_dump / model_validate."""
        import json
        b = JSBundle(
            name="echarts",
            scope="cdn",
            url="https://cdn/x.js",
            sri_hash="sha384-AAAA",
        )
        data = json.loads(b.model_dump_json())
        restored = JSBundle.model_validate(data)
        assert restored.name == "echarts"
        assert restored.url == "https://cdn/x.js"
        assert restored.sri_hash == "sha384-AAAA"
        assert restored.scope == "cdn"
