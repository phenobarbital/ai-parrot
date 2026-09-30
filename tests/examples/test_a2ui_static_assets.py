"""FEAT-610 TASK-3851 — static asset checks."""

from __future__ import annotations

import re
from pathlib import Path


def test_static_assets_sri_and_wiring() -> None:
    """Check that static assets have proper SRI and wiring (AC13, AC15)."""
    static_dir = Path(__file__).resolve().parents[2] / "examples" / "a2ui" / "static"

    # Check index.html
    index_html = (static_dir / "index.html").read_text()

    # The example ships no third-party CDN asset (ECharts is vendored via /static/vendor, the grid is native)
    assert "unpkg.com" not in index_html and "cdn." not in index_html, "no CDN assets: nothing to pin with SRI"
    assert "gridjs" not in index_html, "the grid is a native server-paged table"
    assert 'id="notice"' in index_html, "errors are shown in the notice area, never alert()"
    assert 'id="loginForm"' in index_html

    # Should load renderer.js as module
    assert 'type="module"' in index_html, "renderer.js should be loaded as module"
    assert 'src="/static/renderer.js"' in index_html, "Should load renderer.js"

    # Should reference the token key
    assert "ai_parrot_token" in index_html, "Should reference ai_parrot_token"

    # Check renderer.js
    renderer_js = (static_dir / "renderer.js").read_text()

    # Should import from linked.js
    assert "import { createLane, isDerived, isQuerySlug } from './linked.js'" in renderer_js, (
        "Should import createLane from linked.js"
    )
    assert "from './dsl.js'" in (static_dir / "linked.js").read_text(), "linked.js runs transforms through dsl.js"

    # Should reference the token key
    assert "ai_parrot_token" in renderer_js, "Should reference ai_parrot_token"
    assert "alert(" not in renderer_js and "innerHTML" not in renderer_js, "no alert()/innerHTML (LLM-built text)"

    # Check that no credentials are hardcoded
    for file_name in ["index.html", "renderer.js", "styles.css"]:
        content = (static_dir / file_name).read_text()
        # Check for common credential patterns (this is a basic check)
        # Skip checking for "password" as it's used as a label/input type, not a value
        assert "secret" not in content.lower() or "placeholder" in content.lower(), f"Potential secrets in {file_name}"
        assert (
            "token" not in content.lower()
            or ("ai_parrot_token" in content.lower())
            or ("placeholder" in content.lower())
        ), f"Unexpected token references in {file_name}"
