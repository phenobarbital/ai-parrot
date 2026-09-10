"""Validated configuration, manifest, schema and identity for the LanceDB backend.

Pure module: no SDK import, no I/O. Everything here is consumed by
``lancedb.py`` (TASK-3062+) and re-derived independently by tests.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field, model_validator  # verified: packages/ai-parrot/src/parrot/stores/models.py:13

SCHEMA_VERSION = 1
RESERVED_METADATA_KEY = "_lancedb"
STANDARD_STRING_FIELDS = ("source", "source_type", "parent_id", "document_type")
STANDARD_BOOL_FIELDS = ("is_full_document", "is_chunk")

_COLLECTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_METADATA_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Key fragments treated as credentials and excluded from the embedding
# identity fingerprint (spec §2: "excluding credentials").
_CREDENTIAL_KEY_FRAGMENTS = ("key", "token", "secret", "password", "credential", "auth")


class LanceDBConfig(BaseModel):
    """Backend-owned settings, validated once before any SDK operation."""

    uri: str
    collection_name: str = "my_collection"
    dimension: int = 768
    metric_type: Literal["COSINE"] = "COSINE"
    index_type: Literal["FLAT"] = "FLAT"
    embedding_id: str | None = None
    metadata_fields: dict[str, Literal["str", "bool", "int", "float"]] = Field(default_factory=dict)
    read_consistency_interval_seconds: float = 0.0
    batch_size: int = 128

    model_config = {"frozen": True}

    @model_validator(mode="before")
    @classmethod
    def _resolve_table_alias(cls, data: Any) -> Any:
        """``table`` is a compatibility alias for ``collection_name``.

        Conflicting explicit names (both supplied, both non-default, and
        different) raise ``ValueError`` per spec §2 config table.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        table = data.pop("table", None)
        if table is None:
            return data
        collection_name = data.get("collection_name")
        if collection_name is not None and collection_name != table:
            raise ValueError(
                f"Conflicting collection name aliases: table={table!r} vs "
                f"collection_name={collection_name!r}"
            )
        data["collection_name"] = table
        return data

    @model_validator(mode="after")
    def _validate_uri(self) -> "LanceDBConfig":
        if not self.uri or not self.uri.strip():
            raise ValueError("LanceDBConfig.uri must be a non-empty local directory path")
        parsed = urlparse(self.uri)
        # A bare local path parses with an empty or single-letter (Windows
        # drive) scheme; anything else (s3://, gs://, http://, ...) is a
        # rejected URI scheme. No fallback to another directory.
        if parsed.scheme and len(parsed.scheme) > 1:
            raise ValueError(
                f"LanceDBConfig.uri must be a local directory path, not a URI scheme: {self.uri!r}"
            )
        object.__setattr__(self, "uri", str(Path(self.uri).expanduser()))
        return self

    @model_validator(mode="after")
    def _validate_collection_name(self) -> "LanceDBConfig":
        if not _COLLECTION_NAME_RE.match(self.collection_name):
            raise ValueError(
                f"LanceDBConfig.collection_name {self.collection_name!r} must match "
                f"[A-Za-z_][A-Za-z0-9_]{{0,127}}"
            )
        return self

    @model_validator(mode="after")
    def _validate_dimension(self) -> "LanceDBConfig":
        if self.dimension <= 0:
            raise ValueError("LanceDBConfig.dimension must be a positive integer")
        return self

    @model_validator(mode="after")
    def _validate_numeric_bounds(self) -> "LanceDBConfig":
        if self.read_consistency_interval_seconds < 0 or not _is_finite(
            self.read_consistency_interval_seconds
        ):
            raise ValueError(
                "LanceDBConfig.read_consistency_interval_seconds must be finite and nonnegative"
            )
        if self.batch_size <= 0:
            raise ValueError("LanceDBConfig.batch_size must be a positive integer")
        return self

    @model_validator(mode="after")
    def _validate_metadata_fields(self) -> "LanceDBConfig":
        reserved = set(STANDARD_STRING_FIELDS) | set(STANDARD_BOOL_FIELDS)
        for name in self.metadata_fields:
            if name in (RESERVED_METADATA_KEY,):
                raise ValueError(
                    f"LanceDBConfig.metadata_fields may not redeclare reserved key {name!r}"
                )
            if name in reserved:
                # Redeclaring a standard field with an incompatible type is
                # rejected; redeclaring with the SAME type is a no-op that
                # callers should simply omit, so treat any explicit
                # redeclaration of a standard name as incompatible per the
                # spec's "incompatible redeclarations rejected" language.
                raise ValueError(
                    f"LanceDBConfig.metadata_fields may not redeclare standard field {name!r}"
                )
            if not _METADATA_FIELD_NAME_RE.match(name):
                raise ValueError(
                    f"LanceDBConfig.metadata_fields key {name!r} must match "
                    f"[A-Za-z_][A-Za-z0-9_]{{0,63}}"
                )
        return self


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


class CollectionManifest(BaseModel):
    """Versioned identity persisted in the Arrow schema metadata."""

    schema_version: int = SCHEMA_VERSION
    collection_uuid: str
    dimension: int
    metric_type: str
    embedding_fingerprint: str
    metadata_fields: dict[str, str]

    model_config = {"frozen": True}

    def check_compatible(self, config: "LanceDBConfig", embedding_fingerprint_value: str) -> None:
        """Raise an actionable, non-destructive error on reopen mismatch.

        On reopen, unspecified settings come FROM the manifest (the caller
        is expected to have derived ``config``/``embedding_fingerprint_value``
        accordingly before calling this). This method only rejects an
        explicit mismatch; it never migrates or overwrites persisted data.
        """
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"LanceDB collection schema_version={self.schema_version} is unsupported "
                f"by this build (expected {SCHEMA_VERSION}); reopen without migration is "
                f"not possible. Data was not modified."
            )
        if self.dimension != config.dimension:
            raise ValueError(
                f"LanceDB collection dimension mismatch: stored={self.dimension} "
                f"requested={config.dimension}. Data was not modified."
            )
        if self.metric_type != config.metric_type:
            raise ValueError(
                f"LanceDB collection metric_type mismatch: stored={self.metric_type} "
                f"requested={config.metric_type}. Data was not modified."
            )
        if self.embedding_fingerprint != embedding_fingerprint_value:
            raise ValueError(
                "LanceDB collection embedding identity mismatch: the stored embedding "
                "fingerprint does not match the requested configuration. Data was not "
                "modified."
            )


class LanceDBHybridHit(BaseModel):
    """Backend-owned hybrid result. Deliberately has no ``distance`` alias."""

    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float
    score_kind: Literal["rrf"] = "rrf"
    higher_is_better: Literal[True] = True
    # NOTE: spec §8 Q6 (design research S2) is now RESOLVED — see
    # TASK-3057's gate evidence (sdd/state/FEAT-542/lancedb-sdk-contract.md):
    # the pinned SDK's default hybrid query exposes only the fused
    # ``_relevance_score``, no pre-fusion component columns. v1 ships the
    # single fused score; do not add component fields.


def embedding_fingerprint(settings: dict[str, Any]) -> str:
    """Stable identity for an embedding configuration, excluding credentials.

    Contextual-embedding settings are part of the identity fingerprint
    (spec §2), so every key that is not credential-shaped is included.
    """

    def _is_credential_key(key: str) -> bool:
        lowered = key.lower()
        return any(fragment in lowered for fragment in _CREDENTIAL_KEY_FRAGMENTS)

    def _canonicalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _canonicalize(v) for k, v in sorted(value.items()) if not _is_credential_key(k)}
        if isinstance(value, (list, tuple)):
            return [_canonicalize(v) for v in value]
        return value

    canonical = _canonicalize(settings)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_id_for(text: str, metadata: dict[str, Any]) -> str:
    """Fallback identity: sha256 of ORIGINAL text plus canonical original metadata.

    Must be computed on the caller's original document/metadata, BEFORE any
    contextual augmentation is applied (spec §2 "Data Models").
    """
    canonical_metadata = json.dumps(metadata, sort_keys=True, separators=(",", ":"), default=str)
    payload = f"{text}\x1e{canonical_metadata}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def namespaced_id(collection_uuid: str, record_id: str) -> str:
    """``lancedb:<collection_uuid>:<percent-encoded record_id>``."""
    return f"lancedb:{collection_uuid}:{quote(record_id, safe='')}"


def build_arrow_schema(config: LanceDBConfig, manifest: CollectionManifest):
    """Explicit Arrow schema carrying the manifest in schema metadata.

    Imports pyarrow lazily so this module stays importable (and unit
    testable) without the optional ``lancedb``/``pyarrow`` extra installed
    at the call site — pyarrow itself is a core dependency
    (``packages/ai-parrot/pyproject.toml:157``), but keeping the import
    local avoids surprising import-time side effects for a pure-model
    module.
    """
    import pyarrow as pa  # local import: keep this module import-safe (AC1)

    fields = [
        pa.field("record_id", pa.string(), nullable=False),
        pa.field("document", pa.string(), nullable=False),
        pa.field("embedding", pa.list_(pa.float32(), config.dimension), nullable=False),
        pa.field("metadata_json", pa.string(), nullable=False),
    ]

    _TYPE_MAP = {
        "str": pa.string(),
        "bool": pa.bool_(),
        "int": pa.int64(),
        "float": pa.float64(),
    }
    for name in STANDARD_STRING_FIELDS:
        fields.append(pa.field(f"meta_{name}", pa.string(), nullable=True))
    for name in STANDARD_BOOL_FIELDS:
        fields.append(pa.field(f"meta_{name}", pa.bool_(), nullable=True))
    for name, kind in sorted(manifest.metadata_fields.items()):
        if name in STANDARD_STRING_FIELDS or name in STANDARD_BOOL_FIELDS:
            continue
        fields.append(pa.field(f"meta_{name}", _TYPE_MAP[kind], nullable=True))

    metadata = {b"lancedb_manifest": manifest.model_dump_json().encode("utf-8")}
    return pa.schema(fields, metadata=metadata)
