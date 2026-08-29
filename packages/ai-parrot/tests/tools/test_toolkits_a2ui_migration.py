"""Toolkit A2UI migration tests (TASK-1739 / Module 11).

The toolkits (``parrot.tools.*``) are heavy modules that resolve inconsistently under
this repo's worktree pytest layout (namespace packages + Cython). These tests defer the
import and SKIP when the worktree module is not the one loaded; they run in CI. The
deterministic builder capability (the D1a core) is covered by ``test_builders.py``.
"""

import importlib

import pytest


def _import_or_skip(module: str):
    try:
        return importlib.import_module(module)
    except Exception as exc:  # noqa: BLE001 - Cython/namespace worktree limitation
        pytest.skip(f"cannot import {module} in worktree pytest layout: {exc}")


class TestInfographicToolkitMigration:
    def test_render_direct_preserved(self):
        mod = _import_or_skip("parrot.tools.infographic_toolkit")
        assert mod.InfographicToolkit.return_direct is True

    def test_enhance_lane_marked_deprecated(self):
        mod = _import_or_skip("parrot.tools.infographic_toolkit")
        import inspect

        src = inspect.getsource(mod.InfographicToolkit._maybe_enhance)
        assert "DeprecationWarning" in src and "FEAT-273" in src


class TestInteractiveToolkitMigration:
    def test_return_direct_preserved(self):
        mod = _import_or_skip("parrot.tools.interactive_toolkit")
        assert mod.InteractiveToolkit.return_direct is True

    def test_enhance_lane_marked_deprecated(self):
        mod = _import_or_skip("parrot.tools.interactive_toolkit")
        import inspect

        src = inspect.getsource(mod.InteractiveToolkit._maybe_enhance)
        assert "DeprecationWarning" in src and "FEAT-273" in src


class TestBuildersAreThePreferredLane:
    def test_builders_module_available(self):
        # The deterministic (D1a) builders are the migration target; always importable.
        from parrot.outputs.a2ui import builders

        assert hasattr(builders, "build_infographic")
        assert hasattr(builders, "build_chart")


class TestToolkitsEmitV1Envelopes:
    """TASK-2547 Test Specification: ``test_toolkits_emit_v1_envelopes``.

    Both toolkits' ``_build_a2ui_envelope*`` helpers delegate to the v1.0
    builders/adapter (``build_card``, ``infographic_response_to_envelope`` ->
    ``build_infographic`` -> ``build_surface``), which already call
    ``validate_envelope`` at construction time — a non-``None`` result is
    itself proof the envelope validated. This test also re-validates
    explicitly (reconstructing the ``CreateSurface`` from the wire dict)
    and asserts the v1.0 wire shape: the envelope-by-key wrapper, top-level
    props (no legacy ``properties`` nesting), and a component with ``id="root"``.
    """

    def _bare_instance(self, module_name: str, class_name: str):
        mod = _import_or_skip(module_name)
        import logging

        cls = getattr(mod, class_name)
        instance = cls.__new__(cls)
        instance.logger = logging.getLogger(f"test.{module_name}")
        return instance

    def _surface(self, envelope: dict) -> dict:
        """Assert the v1.0 envelope-by-key wrapper and return the inner surface."""
        assert set(envelope) == {"version", "createSurface"}
        assert envelope["version"] == "v1.0"
        return envelope["createSurface"]

    def test_infographic_toolkit_envelope_validates_as_v1(self):
        from parrot.models.infographic import InfographicResponse
        from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
        from parrot.outputs.a2ui.models import CreateSurface

        toolkit = self._bare_instance("parrot.tools.infographic_toolkit", "InfographicToolkit")
        response = InfographicResponse(
            template="quarterly",
            blocks=[
                {"type": "title", "title": "Q1 Overview"},
                {"type": "hero_card", "label": "Revenue", "value": "$1.2M"},
            ],
        )
        envelope = toolkit._build_a2ui_envelope(response, "infographic-art-v1")
        assert envelope is not None

        surface = self._surface(envelope)
        # The artifact id is the surface id verbatim — never re-prefixed.
        assert surface["surfaceId"] == "infographic-art-v1"

        root = surface["components"][0]
        assert root["id"] == "root"
        assert "properties" not in root  # v1.0: props are top-level, not nested
        assert root["title"] == "Q1 Overview"

        # Re-validate explicitly against the catalog allowlist.
        rebuilt = CreateSurface.model_validate(surface)
        validate_envelope(rebuilt, origin=ProducerOrigin.LLM)

    def test_interactive_toolkit_envelope_validates_as_v1(self):
        from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
        from parrot.outputs.a2ui.models import CreateSurface

        toolkit = self._bare_instance("parrot.tools.interactive_toolkit", "InteractiveToolkit")
        envelope = toolkit._build_a2ui_envelope(
            template_name="dashboard", artifact_id="interactive-art-v2", title="Dashboard", brief="A brief."
        )
        assert envelope is not None

        surface = self._surface(envelope)
        # The artifact id is the surface id verbatim — never re-prefixed.
        assert surface["surfaceId"] == "interactive-art-v2"
        assert not surface["surfaceId"].startswith("interactive-interactive-")

        root = surface["components"][0]
        assert root["id"] == "root"
        assert root["component"] == "InfoCard"
        assert "properties" not in root  # v1.0: props are top-level, not nested
        assert root["title"] == "Dashboard"

        rebuilt = CreateSurface.model_validate(surface)
        validate_envelope(rebuilt, origin=ProducerOrigin.LLM)

    def test_both_toolkits_emit_a2a_acceptable_envelopes(self):
        """The wire shape is what ``Artifact.from_a2ui_envelope`` accepts.

        A bare ``model_dump()`` was rejected with "Unrecognized A2UI envelope
        keys", so every agent shipping one of these surfaces over A2A failed.
        """
        from parrot.a2a.models import Artifact
        from parrot.models.infographic import InfographicResponse

        infographic = self._bare_instance("parrot.tools.infographic_toolkit", "InfographicToolkit")
        interactive = self._bare_instance("parrot.tools.interactive_toolkit", "InteractiveToolkit")

        envelopes = [
            infographic._build_a2ui_envelope(
                InfographicResponse(template="q", blocks=[{"type": "title", "title": "T"}]),
                "infographic-art-a2a",
            ),
            interactive._build_a2ui_envelope(
                template_name="dashboard", artifact_id="interactive-art-a2a", title="D"
            ),
        ]
        for envelope in envelopes:
            artifact = Artifact.from_a2ui_envelope(envelope)
            assert artifact.parts[0].data == envelope
