"""Typed data contracts shared by the Roblox mapping and API tracks (FEAT-532).

These are **proposed** new types (spec §2 "Data Models and New Public
Interfaces") — none of them existed before this task. They exist so
TASK-2898 (project/sourcemap resolution), TASK-2900/2901/2902 (API
acquisition/render/publication), and TASK-2906/2907 (enrichment) can be
implemented independently, in parallel, against an agreed shape instead of
sharing file edits.

Deliberately inert on import: no network client, no filesystem access, no
tree-sitter/grammar loading. Every model is a plain
:class:`pydantic.BaseModel` following the same conventions as
``languages/base.py`` (:class:`~parrot.knowledge.wiki.languages.base.LanguageOutline`)
and ``project.py`` (:class:`~parrot.knowledge.wiki.project.WikiNamespaceConfig`).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Local project mapping (module 2 — TASK-2898/TASK-2907)
# ---------------------------------------------------------------------------


class RobloxInstanceIndex(BaseModel):
    """File<->DataModel-instance association index for one repository scan.

    Built once per scan from ``sourcemap.json`` (preferred) or
    ``default.project.json`` (fallback), never both blended. Associations
    are intentionally one-to-many in both directions: a Rojo mapping can
    legitimately point more than one instance path at the same file (e.g.
    a shared module linked into several services), and — for
    ``init.luau``/``init.lua`` folder conventions — more than one instance
    can be represented by files that resolve to the same folder. Neither
    direction is collapsed or arbitrarily de-duplicated; callers render
    every valid association in **stable sorted order**.

    Attributes:
        file_to_instances: Repository-relative source path -> sorted list
            of DataModel instance paths (e.g.
            ``"src/Main.luau" -> ["game.ServerScriptService.Main"]"``).
        instance_to_files: DataModel instance path -> sorted list of
            repository-relative source paths that map to it.
        class_names: DataModel instance path -> its Rojo ``className``
            (e.g. ``"ModuleScript"``, ``"Script"``, ``"LocalScript"``).
        source_kind: Which mapping source produced this index. ``"none"``
            means no valid mapping was found — the index carries only
            :attr:`diagnostics` and callers proceed with local requires
            only (spec §"Code-to-API linking": build code pages and local
            requires, report skipped linking, perform no network access).
        mapping_digest: Content hash of the mapping input(s) actually
            used, so downstream enrichment invalidation (TASK-2907) can
            detect "the mapping changed" independent of source bytes.
        diagnostics: Human-readable degrade reasons (missing file,
            malformed JSON, stale entry, over-depth, escaping path,
            ambiguous instance name, etc.) — never raised as exceptions.
    """

    model_config = ConfigDict(extra="forbid")

    file_to_instances: dict[str, list[str]] = Field(default_factory=dict)
    instance_to_files: dict[str, list[str]] = Field(default_factory=dict)
    class_names: dict[str, str] = Field(default_factory=dict)
    source_kind: str = "none"
    mapping_digest: str = ""
    diagnostics: list[str] = Field(default_factory=list)

    @field_validator("source_kind")
    @classmethod
    def _validate_source_kind(cls, value: str) -> str:
        allowed = {"sourcemap", "project-file", "none"}
        if value not in allowed:
            raise ValueError(f"source_kind must be one of {sorted(allowed)}, got {value!r}")
        return value


# ---------------------------------------------------------------------------
# Normalized API dump input types (module 3/4 — TASK-2900/TASK-2901)
# ---------------------------------------------------------------------------


class RobloxApiParameter(BaseModel):
    """One parameter of an API dump function/event/callback member."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("parameter name must not be empty")
        return value


class RobloxApiMember(BaseModel):
    """One member (property/function/event/callback) of a dump class.

    Attributes:
        member_type: One of ``"Property" | "Function" | "Event" |
            "Callback"`` — matches the official API dump's ``MemberType``.
        value_type: Property value type, or return-adjacent type for
            simple members; ``None`` when not applicable.
        parameters: Ordered parameter list (functions/callbacks/events).
        return_type: Function/callback return type, when applicable.
        security: Security context string from the dump (e.g.
            ``"None"``, ``"LocalUserSecurity"``), preserved verbatim.
        thread_safety: Thread-safety string from the dump, preserved
            verbatim (e.g. ``"Safe"``, ``"Unsafe"``, ``"ReadSafe"``).
        tags: Raw dump tags (e.g. ``["Deprecated"]``), preserved verbatim.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    member_type: str
    value_type: str | None = None
    parameters: list[RobloxApiParameter] = Field(default_factory=list)
    return_type: str | None = None
    security: str | None = None
    thread_safety: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("member name must not be empty")
        return value

    @field_validator("member_type")
    @classmethod
    def _validate_member_type(cls, value: str) -> str:
        allowed = {"Property", "Function", "Event", "Callback"}
        if value not in allowed:
            raise ValueError(f"member_type must be one of {sorted(allowed)}, got {value!r}")
        return value


class RobloxApiClass(BaseModel):
    """One normalized API dump class entity, joined with creator-docs prose.

    The dump is authoritative for :attr:`name`, :attr:`superclass`,
    :attr:`members` and :attr:`tags` (spec §"API plane acquisition"); only
    :attr:`description` and :attr:`doc_url` come from creator-docs and may
    legitimately be ``None`` — a missing YAML file for a class is a
    supported *structural-only* page, not an error.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    superclass: str | None = None
    members: list[RobloxApiMember] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    doc_url: str | None = None

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("class name must not be empty")
        return value


class RobloxApiEnumItem(BaseModel):
    """One named value of an API dump enum."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: int

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("enum item name must not be empty")
        return value


class RobloxApiEnum(BaseModel):
    """One normalized API dump enum entity."""

    model_config = ConfigDict(extra="forbid")

    name: str
    items: list[RobloxApiEnumItem] = Field(default_factory=list)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("enum name must not be empty")
        return value


class NormalizedApiDump(BaseModel):
    """The full normalized dump + creator-docs join, read-only input to
    ``roblox/render.py``.

    Sorted by :attr:`RobloxApiClass.name` / :attr:`RobloxApiEnum.name` is
    the renderer's responsibility (spec: "Sort entities/edges ... for
    ... identical replay"), not enforced here — this type only carries
    the joined data.
    """

    model_config = ConfigDict(extra="forbid")

    classes: list[RobloxApiClass] = Field(default_factory=list)
    enums: list[RobloxApiEnum] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API generation identity and publication (module 3/4)
# ---------------------------------------------------------------------------


class RobloxApiManifest(BaseModel):
    """One API generation's provenance and content identity.

    :attr:`downloaded_at` is deliberately kept separate from every other
    field: acquisition timestamps are manifest *metadata*, not content —
    two generations acquired at different times from the same
    ``studio_version``/``creator_docs_commit``/``renderer_schema_version``
    must be content-identical (spec: "Generated page content and edges
    are deterministic for identical inputs; acquisition timestamps are
    manifest metadata, not content changes").

    Attributes:
        studio_version: Resolved Studio version string (from
            ``versionQTStudio``), pins the API dump.
        creator_docs_commit: SHA-pinned commit of the ``Roblox/creator-docs``
            repository the tarball was fetched at.
        renderer_schema_version: Version of the page/edge rendering
            schema that produced this generation; a bump forces
            enrichment invalidation even when neither upstream source
            changed.
        source_hashes: Content hash per acquired payload (e.g.
            ``{"api_dump": "<sha256>", "creator_docs_tarball": "<sha256>"}``),
            used by ``--refresh`` to detect "nothing changed, reuse".
        downloaded_at: ISO-8601 acquisition timestamp. Metadata only.
        class_count: Number of class pages generated. Not a fixed
            acceptance count (spec: "observed counts are historical
            measurements, not fixed acceptance counts") — just a
            recorded fact about this generation.
        enum_count: Number of enum pages generated.
        structural_only_count: Classes with no creator-docs prose
            (missing YAML), rendered as structural-only pages.
        missing_doc_classes: Names of classes rendered structural-only.
        skipped: Diagnostics for dump entities that could not be
            rendered (e.g. unresolvable ``extends``/``references``).
    """

    model_config = ConfigDict(extra="forbid")

    studio_version: str
    creator_docs_commit: str
    renderer_schema_version: int = Field(ge=1)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    downloaded_at: str
    class_count: int = Field(ge=0)
    enum_count: int = Field(ge=0)
    structural_only_count: int = Field(ge=0)
    missing_doc_classes: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)

    @field_validator("studio_version")
    @classmethod
    def _non_empty_studio_version(cls, value: str) -> str:
        if not value:
            raise ValueError("studio_version must not be empty")
        return value

    @field_validator("creator_docs_commit")
    @classmethod
    def _valid_commit_sha(cls, value: str) -> str:
        if not value or not all(c in "0123456789abcdefABCDEF" for c in value):
            raise ValueError(f"creator_docs_commit must be a non-empty hex SHA, got {value!r}")
        return value


class RobloxApiCatalog(BaseModel):
    """Class/enum names -> unqualified local page ids, for one generation.

    Local ids are unqualified (``class/Players``, ``enum/Material``);
    federation is responsible for qualifying them (``roblox::class/Players``)
    at the read boundary, never at generation time.
    """

    model_config = ConfigDict(extra="forbid")

    generation_id: str
    classes: dict[str, str] = Field(default_factory=dict)
    enums: dict[str, str] = Field(default_factory=dict)

    @field_validator("generation_id")
    @classmethod
    def _non_empty_generation_id(cls, value: str) -> str:
        if not value:
            raise ValueError("generation_id must not be empty")
        return value

    def page_id_for_class(self, name: str) -> str | None:
        """Return the unqualified page id for a known class, else ``None``."""
        return self.classes.get(name)

    def page_id_for_enum(self, name: str) -> str | None:
        """Return the unqualified page id for a known enum, else ``None``."""
        return self.enums.get(name)


def class_page_id(name: str) -> str:
    """Render the stable unqualified page id for an API class."""
    return f"class/{name}"


def enum_page_id(name: str) -> str:
    """Render the stable unqualified page id for an API enum."""
    return f"enum/{name}"


class RobloxApiIngestResult(BaseModel):
    """Outcome of one ``ingest_roblox_api()`` call.

    Attributes:
        generation_dir: Path to the isolated, immutable generation
            directory this call resolved to (freshly published, or the
            existing validated one on a cache hit).
        manifest: The resolved generation's manifest.
        reused: ``True`` when this call made zero HTTP requests and
            reused an existing validated generation (the default
            ingestion behavior absent ``--refresh``).
        published: ``True`` when this call performed a new atomic
            namespace-registry pointer update. Mutually informative with
            :attr:`reused` (a cache hit is never also a publish).
        diagnostics: Human-readable notes (e.g. "nothing changed,
            generation reused", partial failure detail preserved from a
            failed refresh that retained the last good generation).
    """

    model_config = ConfigDict(extra="forbid")

    generation_dir: str
    manifest: RobloxApiManifest
    reused: bool
    published: bool

    diagnostics: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Code-to-API enrichment (module 6 — TASK-2906/TASK-2907)
# ---------------------------------------------------------------------------


class RobloxReferenceExtractionKind(str, Enum):
    """How one candidate API reference was recognized in Luau source.

    ``CHAINED_ACCESS`` covers the owner's "everything, including chained
    accesses" decision (spec §8: ``workspace.Terrain``-style access on a
    known root) — accepted despite its false-positive cost.
    """

    SERVICE_CALL = "service_call"
    TYPE_ANNOTATION = "type_annotation"
    CHAINED_ACCESS = "chained_access"


class RobloxApiReferenceCandidate(BaseModel):
    """One candidate code-to-API reference, pending catalog resolution.

    Attributes:
        source_span: ``(start_byte, end_byte)`` offsets in the source
            file this candidate was extracted from — diagnostic only,
            never used as a wiki identity.
        recognized_root: The known root the candidate resolved against
            (e.g. ``"workspace"``, ``"game"``, an explicit
            ``GetService`` argument) — never a shadowed/local-aliased
            name (spec §8: local shadowing excludes a candidate).
        extraction_kind: How the candidate was recognized.
        target_name: The candidate class/enum name as written in source.
    """

    model_config = ConfigDict(extra="forbid")

    source_span: tuple[int, int]
    recognized_root: str
    extraction_kind: RobloxReferenceExtractionKind
    target_name: str

    @field_validator("target_name", "recognized_root")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("source_span")
    @classmethod
    def _valid_span(cls, value: tuple[int, int]) -> tuple[int, int]:
        start, end = value
        if start < 0 or end < start:
            raise ValueError(f"invalid source_span {value!r}")
        return value


class RobloxFileEnrichment(BaseModel):
    """One source file's Roblox enrichment: DataModel section + API candidates.

    Kept as a dedicated, source-owned carrier — never folded into
    :class:`~parrot.knowledge.wiki.languages.base.LanguageOutline`, whose
    ``refs`` field is reserved for structural symbol references (spec
    §"Code-to-API linking": "Do not ... reuse ``LanguageOutline.refs`` as
    an external-edge transport").

    Attributes:
        rel_path: Repository-relative path of the enriched source file.
        datamodel_section: Rendered DataModel instance-path/``className``
            body section text for this file's page, or ``""`` when no
            mapping was available for this file.
        reference_candidates: Candidate API references extracted from
            this file, pending resolution against a
            :class:`RobloxApiCatalog`.
        dependency_digest: Combined invalidation key — hashes the mapping
            digest, API catalog generation id, renderer version and
            source bytes together, so a mapping/catalog/renderer change
            invalidates enrichment even when Luau source bytes are
            unchanged (spec §"Code-to-API linking").
        diagnostics: Human-readable degrade/skip reasons (e.g. "no API
            catalog available, skipped API linking").
    """

    model_config = ConfigDict(extra="forbid")

    rel_path: str
    datamodel_section: str = ""
    reference_candidates: list[RobloxApiReferenceCandidate] = Field(default_factory=list)
    dependency_digest: str = ""
    diagnostics: list[str] = Field(default_factory=list)

    @field_validator("rel_path")
    @classmethod
    def _non_empty_rel_path(cls, value: str) -> str:
        if not value:
            raise ValueError("rel_path must not be empty")
        return value
