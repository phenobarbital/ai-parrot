"""End-to-end integration tests for interactive HTML artifacts.

Exercises the full pipeline with an in-memory artifact store and a stubbed
enhance LLM — no real provider calls, no server package required. Mirrors the
shape of ``test_infographic_e2e.py``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.tools.interactive_toolkit import InteractiveToolkit
from parrot.storage.models import Artifact, ArtifactType
from parrot.storage.artifact_signing import get_signing_key, verify_signature


class InMemoryArtifactStore:
    """Minimal async artifact store backed by a dict (scope-keyed)."""

    def __init__(self) -> None:
        self._items: dict[str, Artifact] = {}

    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact):
        self._items[artifact.artifact_id] = artifact

    async def get_artifact(self, user_id, agent_id, session_id, artifact_id):
        return self._items.get(artifact_id)


def _enhance_bot(html: str):
    bot = SimpleNamespace(user_id="u", agent_id="agt", session_id="sess")

    async def enhance_interactive(**kwargs):
        return html

    bot.enhance_interactive = enhance_interactive
    return bot


@pytest.fixture
def store():
    return InMemoryArtifactStore()


async def test_e2e_render_persist_serve_roundtrip(store):
    """render → persist → fetch back the self-contained HTML, verify signed URL."""
    enhanced = (
        "<!DOCTYPE html><html><head></head><body>"
        "<h1>Sales</h1><div id='chart'></div>"
        "<script>/* echarts wiring */</script></body></html>"
    )
    tk = InteractiveToolkit(artifact_store=store)
    tk._bot = _enhance_bot(enhanced)

    result = await tk.render(
        template_name="dashboard",
        brief="Quarterly sales dashboard",
        libraries=["echarts"],
        mode="enhance",
        theme="dark",
        title="Q4 Sales",
    )

    assert result.enhanced is True
    assert result.artifact_id.startswith("interactive-")

    # The artifact is retrievable and carries servable HTML + bundles.
    artifact = await store.get_artifact("u", "agt", "sess", result.artifact_id)
    assert artifact is not None
    assert artifact.artifact_type == ArtifactType.INTERACTIVE
    assert artifact.title == "Q4 Sales"
    assert artifact.definition["html"] == enhanced
    assert artifact.definition["template"] == "dashboard"
    assert artifact.definition["theme"] == "dark"
    assert artifact.definition["libraries"] == ["echarts"]
    assert artifact.definition["js_bundles"]  # CSP source for the public route

    # The signed public URL verifies against the configured signing key.
    segment = result.html_url.split("/api/v1/artifacts/public/")[1].split("/")[0]
    assert verify_signature(result.artifact_id, segment, get_signing_key()) is True


async def test_e2e_deterministic_is_self_contained(store):
    """Deterministic mode yields a standalone document with no leftover markers."""
    tk = InteractiveToolkit(artifact_store=store)
    result = await tk.render(
        template_name="wizard", brief="3-step onboarding", mode="deterministic",
    )
    artifact = await store.get_artifact("_anon", "_anon", "_anon", result.artifact_id)
    html = artifact.definition["html"]
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<!-- SLOT:" not in html
    assert "<!--HEAD-->" not in html
    # The inline stepper bundle is embedded (self-contained, no CDN needed).
    assert "window.Stepper" in html


async def test_e2e_artifact_type_enum_value():
    assert ArtifactType.INTERACTIVE.value == "interactive"
    assert ArtifactType("interactive") is ArtifactType.INTERACTIVE
