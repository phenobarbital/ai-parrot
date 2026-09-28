"""FEAT-610 TASK-3851 — static asset checks."""

from __future__ import annotations

import re
from pathlib import Path


def test_static_assets_sri_and_wiring() -> None:
    """Check that static assets have proper SRI and wiring (AC13, AC15)."""
    static_dir = Path(__file__).resolve().parents[2] / "examples" / "a2ui" / "static"
    
    # Check index.html
    index_html = (static_dir / "index.html").read_text()
    
    # Should have SRI attributes for gridjs
    assert 'integrity="sha384-' in index_html, "Missing SRI for gridjs CSS"
    assert 'crossorigin="anonymous"' in index_html, "Missing crossorigin for gridjs CSS"
    
    # Should load renderer.js as module
    assert 'type="module"' in index_html, "renderer.js should be loaded as module"
    assert 'src="/static/renderer.js"' in index_html, "Should load renderer.js"
    
    # Should reference the token key
    assert "ai_parrot_token" in index_html, "Should reference ai_parrot_token"
    
    # Check renderer.js
    renderer_js = (static_dir / "renderer.js").read_text()
    
    # Should import from linked.js
    assert "import { createLane } from './linked.js'" in renderer_js, "Should import createLane from linked.js"
    
    # Should reference the token key
    assert "ai_parrot_token" in renderer_js, "Should reference ai_parrot_token"
    
    # Check that no credentials are hardcoded
    for file_name in ["index.html", "renderer.js", "styles.css"]:
        content = (static_dir / file_name).read_text()
        # Check for common credential patterns (this is a basic check)
        # Skip checking for "password" as it's used as a label/input type, not a value
        assert "secret" not in content.lower() or "placeholder" in content.lower(), f"Potential secrets in {file_name}"
        assert "token" not in content.lower() or ("ai_parrot_token" in content.lower()) or ("placeholder" in content.lower()), f"Unexpected token references in {file_name}"