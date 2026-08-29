"""Satellite-side bake-resolution tests (FEAT-470 TASK-2538, v1.0 wire).

These require ``jsonpointer`` (the ``ai-parrot-visualizations[a2ui]`` extra); they
are skipped if it is unavailable.
"""

import json

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.baking import BakeError, bake_envelope
from parrot.outputs.a2ui.models import Component, CreateSurface


def _envelope(binding: str, data_model: dict) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(id="root", component="Text", text={"path": binding}),
        ],
        dataModel=data_model,
    )


class TestBakingPass:
    def test_bake_resolves_all_pointers(self):
        env = _envelope("/charts/blk-000/series", {"charts": {"blk-000": {"series": [1, 2, 3]}}})
        baked = bake_envelope(env)
        assert baked[0]["text"] == [1, 2, 3]
        # No live "path"/"call" binding remains.
        dumped = json.dumps(baked)
        assert '"path"' not in dumped
        assert '"call"' not in dumped

    def test_bake_unresolvable_pointer_raises(self):
        env = _envelope("/charts/missing", {"charts": {"blk-000": {}}})
        with pytest.raises(BakeError):
            bake_envelope(env)

    def test_bake_is_deterministic(self):
        env = _envelope("/d", {"d": {"a": 1, "b": [2, 3]}})
        assert bake_envelope(env) == bake_envelope(env)
