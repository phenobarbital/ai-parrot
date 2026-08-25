"""Unit tests for the controls catalog + field-helper snippets' FileEnvelope
shapes (FEAT-460).
"""

import importlib
import sys

import pytest
from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA
from parrot_formdesigner.controls.registry import _REGISTRY, get_controls
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools.field_helpers import _FIELD_SCHEMA_SNIPPETS


@pytest.fixture(autouse=True)
def _ensure_registry_seeded():
    """Defensively re-seed the controls registry if another test cleared it.

    ``tests/unit/controls/test_extension_registration.py`` has a
    pre-existing autouse fixture that does ``_REGISTRY.clear()`` in its
    teardown without re-seeding — a shared-mutable-state bug in that
    (out-of-scope) test file that leaves ``get_controls()`` empty for any
    test running afterward in the same session. Re-seed here rather than
    assume a particular test-run order.
    """
    if not _REGISTRY:
        sys.modules.pop("parrot_formdesigner.controls.builtin", None)
        importlib.import_module("parrot_formdesigner.controls.builtin")
    yield


class TestBuiltinMetadataEnvelope:
    @pytest.mark.parametrize(
        "ft",
        [
            FieldType.FILE,
            FieldType.IMAGE,
            FieldType.IMAGE_DROPZONE,
            FieldType.MULTI_UPLOAD,
        ],
    )
    def test_value_shape_includes_filename(self, ft):
        # value_shape is NOT stored in _BUILTIN_METADATA (verified against
        # the actual file: it's computed dynamically in builtin.py's
        # _seed() via type_level_value_shape() and published on the
        # registered FieldControlMetadata instead).
        controls = {c.type: c for c in get_controls()}
        shape = controls[ft.value].value_shape
        shape_str = str(shape)
        assert "filename" in shape_str

    @pytest.mark.parametrize("ft", [FieldType.FILE, FieldType.IMAGE])
    def test_file_image_still_media_category(self, ft):
        assert _BUILTIN_METADATA[ft]["category"] == "media"

    @pytest.mark.parametrize(
        "ft",
        [
            FieldType.FILE,
            FieldType.IMAGE,
            FieldType.IMAGE_DROPZONE,
            FieldType.MULTI_UPLOAD,
        ],
    )
    def test_upload_types_still_upload_render_hint(self, ft):
        assert _BUILTIN_METADATA[ft]["render_hint"] == "upload"


class TestFieldHelperSnippets:
    @pytest.mark.parametrize("key", ["file", "image", "image_dropzone", "multi_upload"])
    def test_snippet_has_envelope_example(self, key):
        snippet = _FIELD_SCHEMA_SNIPPETS[key]
        example = snippet.get("value_example", {})
        if isinstance(example, dict):
            assert "filename" in example
        elif isinstance(example, list):
            assert "filename" in example[0]

    @pytest.mark.parametrize("key", ["file", "image", "image_dropzone", "multi_upload"])
    def test_snippet_has_dual_read_note(self, key):
        snippet = _FIELD_SCHEMA_SNIPPETS[key]
        assert "note" in snippet
        assert "legacy" in snippet["note"].lower()
