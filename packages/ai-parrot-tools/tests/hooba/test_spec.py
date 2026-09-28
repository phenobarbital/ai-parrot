"""FEAT-602 TASK-3735 — pinned spec loader and pruner."""

import json

import pytest

from parrot_tools.hooba import spec as spec_module
from parrot_tools.hooba.spec import PINNED_VERSION, REQUIRED_PATHS, HoobaSpecError, load_pinned_spec
from parrot_tools.hooba.spec.prune import prune_spec


def test_pinned_spec_loads_and_validates():
    """The bundled, committed document is valid, current, and carries every required path."""
    doc = load_pinned_spec()

    assert doc["openapi"].startswith("3.")
    assert doc["info"]["version"] == PINNED_VERSION
    assert doc["servers"] == [{"url": "https://api.hooba.com"}]
    for required_path in REQUIRED_PATHS:
        assert required_path in doc["paths"]


def test_pinned_spec_sha256_mismatch_fails_closed(tmp_path, monkeypatch):
    """A tampered bundled file must fail closed with HoobaSpecError (S5)."""
    tampered = tmp_path / "hooba-api-2026.6.17.pruned.json"
    original = spec_module.PINNED_FILE.read_bytes()
    tampered.write_bytes(original + b"\n// tampered\n")
    monkeypatch.setattr(spec_module, "PINNED_FILE", tampered)
    monkeypatch.delenv("HOOBA_SPEC_PATH", raising=False)

    with pytest.raises(HoobaSpecError):
        load_pinned_spec()


def test_override_path_missing_required_path_raises(tmp_path):
    """An override document that lacks a REQUIRED_PATHS entry must raise, even without a hash check."""
    incomplete = {
        "openapi": "3.0.0",
        "info": {"version": "9999.1.1"},
        "servers": [{"url": "https://api.hooba.com"}],
        "paths": {"/auth/login": {"post": {"tags": ["Authentication"]}}},
        "components": {"schemas": {}},
    }
    override_file = tmp_path / "incomplete.json"
    override_file.write_text(json.dumps(incomplete), encoding="utf-8")

    with pytest.raises(HoobaSpecError):
        load_pinned_spec(path=str(override_file))


def test_prune_spec_keeps_referenced_components_only():
    """The pruner keeps only kept-tag operations and the components they transitively reference."""
    doc = {
        "openapi": "3.0.0",
        "info": {"version": "1.0.0"},
        "paths": {
            "/kept": {
                "get": {
                    "tags": ["Invoice"],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Kept"}}}}
                    },
                }
            },
            "/dropped": {
                "get": {
                    "tags": ["NotKept"],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Dropped"}}}}
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Kept": {"type": "object", "properties": {"nested": {"$ref": "#/components/schemas/Nested"}}},
                "Nested": {"type": "object", "x-internal": True},
                "Dropped": {"type": "object"},
            }
        },
        "x-root-extra": "drop-me",
    }

    result = prune_spec(doc, keep_tags=("Invoice",))

    assert "/kept" in result["paths"]
    assert "/dropped" not in result["paths"]
    assert set(result["components"]["schemas"].keys()) == {"Kept", "Nested"}
    assert "Dropped" not in result["components"]["schemas"]
    assert "x-internal" not in result["components"]["schemas"]["Nested"]
    assert "x-root-extra" not in result
    assert result["servers"] == [{"url": "https://api.hooba.com"}]
