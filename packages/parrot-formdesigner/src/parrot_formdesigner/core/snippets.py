"""Snippet, manifest, and sandbox-boundary models for FEAT-459.

Defines the data every other formbuilder-custom-code module (loaders,
resolver, sandbox pools, router, broker) shares. Mirrors the
``model_config = ConfigDict(extra="forbid")`` convention of
``core/events.py`` — no new model in this feature accepts unknown fields.

Public surface:
    - CapabilityTier, SnippetSource, SnippetStatus
    - BrokerAllowlist, CapabilityManifest
    - SnippetBundle
    - SandboxContext, AbortSignal, SandboxOutcome
    - SnippetIntegrityError, SnippetTierUnavailableError,
      CapabilityDenied, SnippetNotApprovedError
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot_formdesigner.core.events import EventResolution, FormEventName


class CapabilityTier(StrEnum):
    """Declared power level of a snippet; selects its executor (spec §2)."""

    PURE = "pure"  # payload + schema only, no I/O
    HELPERS = "helpers"  # + curated stdlib subset, metadata, declared claims
    BROKERED = "brokered"  # + host-mediated allowlisted outbound calls
    TOOLKIT = "toolkit"  # + registered parrot tools/agents


class SnippetSource(StrEnum):
    """Where a bundle came from. Determines its approval gate and tier cap."""

    GIT = "git"  # platform-wide, tenant=None, approved by merged PR
    DB = "db"  # tenant-scoped, approved in-app by a tenant admin


class SnippetStatus(StrEnum):
    """Lifecycle of a DB-sourced tenant snippet.

    GIT bundles are always PUBLISHED by construction — an unmerged snippet
    does not exist on disk, so there is no DRAFT/REVOKED state for it.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    REVOKED = "revoked"


class BrokerAllowlist(BaseModel):
    """Explicit outbound permissions for tier BROKERED / TOOLKIT."""

    model_config = ConfigDict(extra="forbid")

    http_hosts: tuple[str, ...] = ()  # exact hostnames; no wildcards in v1
    query_tables: tuple[str, ...] = ()  # fully-qualified table names
    notifications: tuple[str, ...] = ()  # channel identifiers
    toolkits: tuple[str, ...] = ()  # registered parrot toolkit names


class CapabilityManifest(BaseModel):
    """What a snippet declares it needs.

    The security contract, and the unit ``check_snippet_conformance.py`` (M15)
    checks the source against. ``timeout_ms``/``max_memory_mb`` bounds mirror the
    OQ-6 pool sizing defaults documented in spec §7.
    """

    model_config = ConfigDict(extra="forbid")

    tier: CapabilityTier
    auth_claims: tuple[str, ...] = ()  # AuthContext.claims keys projected in (OQ-5)
    stdlib_modules: tuple[str, ...] = ()  # subset of a fixed curated allowlist
    allowlist: BrokerAllowlist = Field(default_factory=BrokerAllowlist)
    timeout_ms: int = Field(default=5_000, ge=1, le=30_000)
    max_memory_mb: int = Field(default=128, ge=16, le=2_048)


class SnippetBundle(BaseModel):
    """One snippet from either source: manifest + Python half + optional TS half."""

    model_config = ConfigDict(extra="forbid")

    source: SnippetSource
    status: SnippetStatus = SnippetStatus.PUBLISHED
    version: int = 1  # DB snippets increment; git is always 1
    approved_by: str | None = None  # tenant admin id (DB) or commit sha (git)
    approved_at: datetime | None = None
    handler_ref: str = Field(
        ...,
        # Same pattern as FormEventBinding.handler_ref — verified:
        # core/events.py:69
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$",
    )
    event: FormEventName
    tenant: str | None = None  # None = global, matching registry semantics
    manifest: CapabilityManifest
    python_source: str
    python_sha256: str
    client_source: str | None = None  # compiled JS for the Web Worker
    client_sha256: str | None = None


class SandboxContext(BaseModel):
    """Serialisable projection of ``FormEventContext`` that crosses the boundary.

    Deliberately NOT ``FormEventContext``: ``auth_context`` on that model is
    a live object typed ``Any`` (core/events.py:128) and must never be
    handed to a worker. This model has no ``token``/``headers`` field by
    construction (OQ-5) — there is no field to accidentally populate.
    """

    model_config = ConfigDict(extra="forbid")

    event: FormEventName
    form_id: str
    tenant: str | None
    claims: Mapping[str, Any]  # only manifest-declared auth_claims
    payload: Mapping[str, Any] | None = None
    schema_dump: Mapping[str, Any] | None = None
    user_message: str | None = None
    extra: Mapping[str, Any] = Field(default_factory=dict)


class AbortSignal(BaseModel):
    """Serialisable form of ``FormEventAbort`` — verified: core/events.py:201."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    user_message: str
    status_code: int = 403


class SandboxOutcome(BaseModel):
    """What a worker returns. Exactly one of ``resolution``/``abort`` is set."""

    model_config = ConfigDict(extra="forbid")

    resolution: EventResolution | None = None
    abort: AbortSignal | None = None
    duration_ms: float
    broker_calls: int = 0


class SnippetIntegrityError(Exception):
    """Raised when a snippet's source hash does not match its manifest."""


class SnippetTierUnavailableError(Exception):
    """Raised when a bundle declares tier 3/4 but gVisor is unavailable (OQ-4)."""


class CapabilityDenied(Exception):
    """Raised by the host broker when a request is outside the manifest allowlist."""


class SnippetNotApprovedError(Exception):
    """Raised when execution is attempted against a DRAFT or REVOKED bundle."""
