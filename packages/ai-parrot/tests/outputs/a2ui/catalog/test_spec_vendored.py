"""Tests for the vendored A2UI v1.0 spec (FEAT-470 TASK-2534)."""

from __future__ import annotations

import hashlib
import re
import urllib.request

import jsonschema
import pytest
from parrot.outputs.a2ui.catalog.basic import (
    BASIC_CATALOG_ID,
    SPEC_COMMIT,
    SPEC_FILES,
    load_spec,
    schema_registry,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class TestSpecFilesPresentAndPinned:
    def test_spec_files_present_and_pinned(self):
        """All six vendored JSON documents load; SPEC_COMMIT is a 40-hex SHA."""
        assert _SHA_RE.match(SPEC_COMMIT), f"not a 40-hex SHA: {SPEC_COMMIT!r}"
        for name in SPEC_FILES:
            doc = load_spec(name)
            assert isinstance(doc, dict)
            assert "$id" in doc

    def test_basic_catalog_id_matches(self):
        assert load_spec("catalog")["catalogId"] == BASIC_CATALOG_ID

    def test_unknown_spec_name_raises(self):
        with pytest.raises(ValueError):
            load_spec("nonexistent")  # type: ignore[arg-type]


class TestSchemaRegistryResolvesCommonTypes:
    def test_schema_registry_resolves_common_types(self):
        registry = schema_registry()
        resolver = registry.resolver()
        resolved = resolver.lookup("https://a2ui.org/specification/v1_0/common_types.json#/$defs/Extensions")
        assert resolved.contents["type"] == "object"

    def test_schema_registry_resolves_catalog_alias(self):
        """agent_to_renderer.json's relative "catalog.json#/..." ref resolves."""
        registry = schema_registry()
        resolver = registry.resolver()
        resolved = resolver.lookup("https://a2ui.org/specification/v1_0/catalog.json#/$defs/anyComponent")
        assert "oneOf" in resolved.contents or "anyOf" in resolved.contents

    def test_validate_sample_create_surface_against_agent_to_renderer(self):
        """A minimal createSurface envelope validates against the real schema."""
        registry = schema_registry()
        schema = load_spec("agent_to_renderer")
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema, registry=registry)
        sample = {
            "version": "v1.0",
            "createSurface": {
                "surfaceId": "main",
                "catalogId": BASIC_CATALOG_ID,
                "components": [{"id": "root", "component": "Text", "text": "hi"}],
            },
        }
        validator.validate(sample)  # raises on failure


@pytest.mark.network
class TestSpecDriftAgainstUpstream:
    def test_spec_drift_against_upstream(self):
        """Every vendored file's bytes match the pinned upstream SHA's bytes."""
        base = "https://raw.githubusercontent.com/google/A2UI/" f"{SPEC_COMMIT}/specification/v1_0"
        upstream_paths = {
            "catalog": "catalogs/basic/catalog.json",
            "common_types": "json/common_types.json",
            "agent_to_renderer": "json/agent_to_renderer.json",
            "renderer_to_agent": "json/renderer_to_agent.json",
            "catalog_definition": "json/catalog_definition.json",
            "agent_capabilities": "json/agent_capabilities.json",
        }
        for name, rel_path in upstream_paths.items():
            local_bytes = _local_bytes(name)
            with urllib.request.urlopen(f"{base}/{rel_path}", timeout=15) as resp:
                upstream_bytes = resp.read()
            assert (
                hashlib.sha256(local_bytes).hexdigest() == hashlib.sha256(upstream_bytes).hexdigest()
            ), f"{name} has drifted from the pinned upstream commit"


def _local_bytes(name: str) -> bytes:
    from pathlib import Path

    import parrot.outputs.a2ui.catalog.basic as basic_pkg

    spec_dir = Path(basic_pkg.__file__).parent / "spec"
    return (spec_dir / SPEC_FILES[name]).read_bytes()
