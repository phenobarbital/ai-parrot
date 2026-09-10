"""Strict model, schema and identity tests (FEAT-542, AC3)."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from parrot.stores.lancedb_models import (  # new in this task
    RESERVED_METADATA_KEY,
    CollectionManifest,
    LanceDBConfig,
    LanceDBHybridHit,
    build_arrow_schema,
    embedding_fingerprint,
    namespaced_id,
    record_id_for,
)


class TestLanceDBConfig:
    def test_rejects_uri_schemes_and_canonicalizes_local_path(self, tmp_path):
        local = LanceDBConfig(uri=str(tmp_path / "col"))
        assert local.uri  # canonicalized, non-empty

        with pytest.raises(ValidationError):
            LanceDBConfig(uri="s3://bucket/col")

        with pytest.raises(ValidationError):
            LanceDBConfig(uri="")

    def test_conflicting_table_and_collection_name_raise(self):
        # Same value via both aliases: fine.
        cfg = LanceDBConfig(uri="/tmp/x", table="agent_knowledge")
        assert cfg.collection_name == "agent_knowledge"

        # Conflicting explicit names: ValueError.
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", table="a", collection_name="b")

    def test_collection_name_pattern_enforced(self):
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", collection_name="1-bad-name")

    def test_dimension_and_numeric_bounds(self):
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", dimension=0)
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", batch_size=0)
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", read_consistency_interval_seconds=-1.0)

    def test_metadata_fields_reject_reserved_and_standard_and_malformed(self):
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", metadata_fields={RESERVED_METADATA_KEY: "str"})
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", metadata_fields={"source": "int"})  # standard field redeclared
        with pytest.raises(ValidationError):
            LanceDBConfig(uri="/tmp/x", metadata_fields={"1bad": "str"})


class TestCollectionManifest:
    def test_compatible_config_does_not_raise(self):
        manifest = CollectionManifest(
            collection_uuid=str(uuid.uuid4()),
            dimension=8,
            metric_type="COSINE",
            embedding_fingerprint="fp",
            metadata_fields={},
        )
        config = LanceDBConfig(uri="/tmp/x", dimension=8, metric_type="COSINE")
        manifest.check_compatible(config, "fp")  # no raise

    def test_dimension_mismatch_raises_without_migration(self):
        manifest = CollectionManifest(
            collection_uuid=str(uuid.uuid4()),
            dimension=8,
            metric_type="COSINE",
            embedding_fingerprint="fp",
            metadata_fields={},
        )
        config = LanceDBConfig(uri="/tmp/x", dimension=16, metric_type="COSINE")
        with pytest.raises(ValueError):
            manifest.check_compatible(config, "fp")

    def test_embedding_fingerprint_mismatch_raises(self):
        manifest = CollectionManifest(
            collection_uuid=str(uuid.uuid4()),
            dimension=8,
            metric_type="COSINE",
            embedding_fingerprint="fp-a",
            metadata_fields={},
        )
        config = LanceDBConfig(uri="/tmp/x", dimension=8, metric_type="COSINE")
        with pytest.raises(ValueError):
            manifest.check_compatible(config, "fp-b")

    def test_unsupported_schema_version_raises(self):
        manifest = CollectionManifest(
            schema_version=999,
            collection_uuid=str(uuid.uuid4()),
            dimension=8,
            metric_type="COSINE",
            embedding_fingerprint="fp",
            metadata_fields={},
        )
        config = LanceDBConfig(uri="/tmp/x", dimension=8, metric_type="COSINE")
        with pytest.raises(ValueError):
            manifest.check_compatible(config, "fp")


class TestIdentity:
    def test_fingerprint_excludes_credentials_and_includes_contextual_settings(self):
        with_key = embedding_fingerprint({"model": "m1", "api_key": "secret-a", "contextual": True})
        without_key_diff_value = embedding_fingerprint({"model": "m1", "api_key": "secret-b", "contextual": True})
        assert with_key == without_key_diff_value  # credential value doesn't affect fingerprint

        different_contextual = embedding_fingerprint({"model": "m1", "api_key": "secret-a", "contextual": False})
        assert different_contextual != with_key  # contextual settings ARE part of the identity

    def test_fingerprint_is_order_independent_and_deterministic(self):
        a = embedding_fingerprint({"model": "m1", "revision": "r1"})
        b = embedding_fingerprint({"revision": "r1", "model": "m1"})
        assert a == b
        assert a == embedding_fingerprint({"model": "m1", "revision": "r1"})

    def test_record_id_for_is_deterministic_and_content_sensitive(self):
        a = record_id_for("hello world", {"source": "x"})
        b = record_id_for("hello world", {"source": "x"})
        c = record_id_for("hello world!", {"source": "x"})
        assert a == b
        assert a != c

    def test_namespaced_ids_do_not_collide_across_collections(self):
        uuid_a = str(uuid.uuid4())
        uuid_b = str(uuid.uuid4())
        id_a = namespaced_id(uuid_a, "shared-record-id")
        id_b = namespaced_id(uuid_b, "shared-record-id")
        assert id_a != id_b
        assert id_a.startswith("lancedb:")
        assert uuid_a in id_a and "shared-record-id" in id_a

    def test_namespaced_id_percent_encodes_record_id(self):
        encoded = namespaced_id("col-uuid", "id with spaces/slash")
        assert " " not in encoded
        assert "/" not in encoded.rsplit(":", 1)[-1] or "%2F" in encoded


class TestHybridHit:
    def test_has_no_distance_alias(self):
        hit = LanceDBHybridHit(id="x", content="y", score=0.5)
        assert not hasattr(hit, "distance")
        assert hit.score_kind == "rrf"
        assert hit.higher_is_better is True

    def test_rejects_non_rrf_score_kind(self):
        with pytest.raises(ValidationError):
            LanceDBHybridHit(id="x", content="y", score=0.5, score_kind="bm25")  # type: ignore[arg-type]


class TestArrowSchema:
    def test_build_arrow_schema_carries_manifest_metadata(self):
        pytest.importorskip("pyarrow")
        config = LanceDBConfig(uri="/tmp/x", dimension=8, metric_type="COSINE")
        manifest = CollectionManifest(
            collection_uuid=str(uuid.uuid4()),
            dimension=8,
            metric_type="COSINE",
            embedding_fingerprint="fp",
            metadata_fields={"custom_flag": "bool"},
        )
        schema = build_arrow_schema(config, manifest)
        names = schema.names
        assert "record_id" in names
        assert "document" in names
        assert "embedding" in names
        assert "metadata_json" in names
        assert "meta_source" in names  # standard string field
        assert "meta_is_chunk" in names  # standard bool field
        assert "meta_custom_flag" in names  # declared custom field
        assert schema.metadata is not None
        assert b"lancedb_manifest" in schema.metadata

    def test_build_arrow_schema_is_never_inferred_from_rows(self):
        """No row is passed to build_arrow_schema at all — schema comes from config/manifest only."""
        pytest.importorskip("pyarrow")
        import inspect

        sig = inspect.signature(build_arrow_schema)
        assert list(sig.parameters) == ["config", "manifest"]
