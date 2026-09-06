"""Pure, deterministic Roblox API class/enum page rendering (FEAT-532 TASK-2901).

No HTTP, no publication, no registry mutation, no wall-clock data in
stable content — this module is a pure function of its inputs (the
acquired dump + creator-docs YAML). Given the same inputs it always
produces byte-identical page bodies and identically-ordered edges/catalog
entries (spec: "Generated page content and edges are deterministic for
identical inputs; acquisition timestamps are manifest metadata, not
content changes").

Two-stage pipeline:

1. :func:`build_normalized_dump` — merges exact dump class/member
   identities (existence, superclass, parameters, return types,
   security, thread safety, enum items — all dump-authoritative) with
   optional creator-docs prose (description/doc link only), into the
   :class:`~parrot.knowledge.wiki.roblox.models.NormalizedApiDump`
   TASK-2897 defined.
2. :func:`render_generation` — renders one sorted
   :class:`~parrot.knowledge.wiki.store.WikiPageRecord` per class/enum,
   ``extends``/``references`` edges restricted to entities present in
   *this* generation, and the :class:`~parrot.knowledge.wiki.roblox.models.RobloxApiCatalog`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from parrot.knowledge.wiki import store as wiki_store
from parrot.knowledge.wiki.roblox.models import (
    NormalizedApiDump,
    RobloxApiCatalog,
    RobloxApiClass,
    RobloxApiEnum,
    RobloxApiEnumItem,
    RobloxApiMember,
    RobloxApiParameter,
    class_page_id,
    enum_page_id,
)
from parrot.knowledge.wiki.store import WikiPageRecord

#: Doc-URL prefix for the (deterministically constructed, never fetched)
#: canonical creator-docs link recorded as provenance on each class page.
_DOC_URL_TEMPLATE = "https://create.roblox.com/docs/reference/engine/classes/{name}"

#: Creator-docs YAML prose keys tried in order — the real key name was
#: not independently re-verified against a live fetch in this offline
#: workflow (TASK-2900 only defines the acquisition transport); trying
#: both keeps this resilient to either convention.
_DESCRIPTION_KEYS = ("description", "summary")


# ---------------------------------------------------------------------------
# Token estimation — never triggers a first-time tokenizer download
# ---------------------------------------------------------------------------


def _safe_token_count(text: str) -> int:
    """Estimate a token count without ever triggering a cold tiktoken fetch.

    ``store.estimate_tokens`` lazily loads (and process-caches) a
    ``tiktoken`` encoder on first call, which can hit the network for the
    BPE vocabulary file. This helper only delegates to it when that
    encoder cache is **already resolved** (success or the ``False``
    failure sentinel) — determined by reading, never writing,
    ``store._TOKEN_ENCODER``. On a cold cache it uses the exact same
    deterministic ``len(text) // 4`` fallback ``estimate_tokens`` itself
    uses when the tokenizer is unavailable, without ever probing it.

    Args:
        text: Text to measure.

    Returns:
        Estimated token count (``0`` for empty text).
    """
    if not text:
        return 0
    if wiki_store._TOKEN_ENCODER is not None:
        return wiki_store.estimate_tokens(text)
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Stage 1 — merge dump identities with creator-docs prose
# ---------------------------------------------------------------------------


def _type_name(type_obj: Any) -> str:
    """Render one dump ``ValueType``/``ReturnType``/parameter type as text.

    The official dump shapes a type as ``{"Category": "Class"|"Enum"|
    "Primitive"|"DataType"|"Group", "Name": "..."}``; this renders just
    the ``Name`` (what a hand-written Luau type annotation would say),
    which also makes exact-name reference recognition in
    :func:`_class_and_enum_references` straightforward.
    """
    if isinstance(type_obj, dict):
        name = type_obj.get("Name")
        if isinstance(name, str):
            return name
        return str(type_obj)
    if isinstance(type_obj, str):
        return type_obj
    return "" if type_obj is None else str(type_obj)


def _type_category(type_obj: Any) -> str | None:
    """The dump's ``Category`` for a type object, or ``None``."""
    if isinstance(type_obj, dict):
        category = type_obj.get("Category")
        return category if isinstance(category, str) else None
    return None


def _security_text(raw: Any) -> str | None:
    """Render a dump ``Security`` value (plain string or ``{Read,Write}``)."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        read = raw.get("Read", "")
        write = raw.get("Write", "")
        return f"Read={read}, Write={write}"
    return str(raw)


def _normalize_member(raw: dict[str, Any]) -> RobloxApiMember | None:
    name = raw.get("Name")
    member_type = raw.get("MemberType")
    if (
        not isinstance(name, str)
        or not name
        or member_type
        not in (
            "Property",
            "Function",
            "Event",
            "Callback",
        )
    ):
        return None

    parameters: list[RobloxApiParameter] = []
    for raw_param in raw.get("Parameters") or []:
        if not isinstance(raw_param, dict):
            continue
        pname = raw_param.get("Name")
        if not isinstance(pname, str) or not pname:
            continue
        parameters.append(RobloxApiParameter(name=pname, type=_type_name(raw_param.get("Type"))))

    value_type = None
    return_type = None
    if member_type == "Property":
        value_type = _type_name(raw.get("ValueType")) or None
    elif member_type in ("Function", "Callback"):
        return_type = _type_name(raw.get("ReturnType")) or None

    tags = [t for t in (raw.get("Tags") or []) if isinstance(t, str)]

    return RobloxApiMember(
        name=name,
        member_type=member_type,
        value_type=value_type,
        parameters=parameters,
        return_type=return_type,
        security=_security_text(raw.get("Security")),
        thread_safety=raw.get("ThreadSafety") if isinstance(raw.get("ThreadSafety"), str) else None,
        tags=sorted(tags),
    )


def _extract_description(docs: dict[str, Any] | None) -> str | None:
    if not isinstance(docs, dict):
        return None
    for key in _DESCRIPTION_KEYS:
        value = docs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_class(raw: dict[str, Any], docs: dict[str, Any] | None) -> RobloxApiClass | None:
    name = raw.get("Name")
    if not isinstance(name, str) or not name:
        return None
    superclass = raw.get("Superclass")
    if not isinstance(superclass, str) or superclass in ("<<<ROOT>>>", ""):
        superclass = None
    members = sorted(
        (m for m in (_normalize_member(r) for r in raw.get("Members") or [] if isinstance(r, dict)) if m is not None),
        key=lambda m: m.name,
    )
    tags = sorted(t for t in (raw.get("Tags") or []) if isinstance(t, str))
    description = _extract_description(docs)
    return RobloxApiClass(
        name=name,
        superclass=superclass,
        members=members,
        tags=tags,
        description=description,
        doc_url=_DOC_URL_TEMPLATE.format(name=name) if description is not None else None,
    )


def _normalize_enum(raw: dict[str, Any]) -> RobloxApiEnum | None:
    name = raw.get("Name")
    if not isinstance(name, str) or not name:
        return None
    items: list[RobloxApiEnumItem] = []
    for raw_item in raw.get("Items") or []:
        if not isinstance(raw_item, dict):
            continue
        iname = raw_item.get("Name")
        ivalue = raw_item.get("Value")
        if isinstance(iname, str) and iname and isinstance(ivalue, int):
            items.append(RobloxApiEnumItem(name=iname, value=ivalue))
    # No creator-docs source is acquired for enums (TASK-2900 only fetches
    # */classes/*.yaml) — enums are always structural-only in this v1.
    return RobloxApiEnum(name=name, items=sorted(items, key=lambda i: i.name), description=None)


def build_normalized_dump(api_dump: dict[str, Any], class_docs: dict[str, Any]) -> NormalizedApiDump:
    """Merge exact dump identities with optional creator-docs prose.

    The dump is authoritative for existence, inheritance, member kinds,
    parameters, return types, security, thread safety, and enum items;
    ``class_docs`` (from TASK-2900's acquisition) supplies only
    :attr:`~parrot.knowledge.wiki.roblox.models.RobloxApiClass.description`/
    :attr:`~....doc_url`. A class absent from ``class_docs`` is a
    complete, valid structural-only page — never an error.

    Args:
        api_dump: The parsed API dump (already validated by TASK-2900 to
            contain a ``"Classes"`` list).
        class_docs: Class name -> parsed creator-docs YAML content.

    Returns:
        The merged, not-yet-sorted :class:`NormalizedApiDump`. (Sorting
        for deterministic output order is :func:`render_generation`'s job.)
    """
    classes = [
        c
        for c in (
            _normalize_class(raw, class_docs.get(raw.get("Name")))
            for raw in api_dump.get("Classes", [])
            if isinstance(raw, dict)
        )
        if c is not None
    ]
    enums = [
        e for e in (_normalize_enum(raw) for raw in api_dump.get("Enums", []) if isinstance(raw, dict)) if e is not None
    ]
    return NormalizedApiDump(classes=classes, enums=enums)


# ---------------------------------------------------------------------------
# Stage 2 — render pages, edges, catalog
# ---------------------------------------------------------------------------


@dataclass
class RenderedGeneration:
    """Output of :func:`render_generation`: everything TASK-2902 needs to
    publish one API generation, plus the counts/diagnostics that feed its
    manifest.

    Attributes:
        pages: Sorted (by ``concept_id``) class/enum pages.
        edges: Sorted ``(source_concept_id, target_concept_id, rel)``
            tuples — the store's actual ``(src, dst, rel)`` convention
            (verified against ``store.py``'s ``add_edges``/
            ``replace_source_slice``, e.g. ``SELECT src, dst, rel FROM
            edges``); ``rel`` is ``"extends"`` or ``"references"``.
        catalog: The generation's :class:`RobloxApiCatalog`.
        class_count: Number of class pages rendered.
        enum_count: Number of enum pages rendered.
        structural_only_count: Classes with no creator-docs description.
        missing_doc_classes: Sorted names of structural-only classes.
        skipped: Diagnostics for dump entities that could not be
            rendered (e.g. unresolvable member data).
    """

    pages: list[WikiPageRecord]
    edges: list[tuple[str, str, str]]
    catalog: RobloxApiCatalog
    class_count: int
    enum_count: int
    structural_only_count: int
    missing_doc_classes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _render_member_line(member: RobloxApiMember) -> str:
    params = ", ".join(f"{p.name}: {p.type}" for p in member.parameters)
    if member.member_type == "Property":
        sig = f"{member.name}: {member.value_type or 'unknown'}"
    else:
        sig = f"{member.name}({params})"
        if member.return_type:
            sig = f"{sig}: {member.return_type}"
    parts = [f"### {member.member_type} {sig}"]
    if member.security:
        parts.append(f"- Security: {member.security}")
    if member.thread_safety:
        parts.append(f"- ThreadSafety: {member.thread_safety}")
    if member.tags:
        parts.append(f"- Tags: {', '.join(member.tags)}")
    return "\n".join(parts)


def _render_class_body(cls: RobloxApiClass, catalog_names: set[str], generation_id: str) -> str:
    lines = [f"# {cls.name}"]
    if cls.superclass:
        lines.append(f"Superclass: {cls.superclass}")
    if cls.tags:
        lines.append(f"Tags: {', '.join(cls.tags)}")
    lines.append("")
    lines.append("## Description")
    lines.append(cls.description or "(no creator-docs description available for this class)")
    if cls.doc_url:
        lines.append(f"Upstream: {cls.doc_url}")
    lines.append("")
    lines.append("## Members")
    if cls.members:
        for member in cls.members:
            lines.append(_render_member_line(member))
    else:
        lines.append("(no members)")
    lines.append("")
    lines.append(f"Generation: {generation_id}")
    return "\n".join(lines)


def _render_enum_body(enum: RobloxApiEnum, generation_id: str) -> str:
    lines = [f"# {enum.name} (Enum)", "", "## Items"]
    if enum.items:
        for item in enum.items:
            lines.append(f"- {item.name} = {item.value}")
    else:
        lines.append("(no items)")
    lines.append("")
    lines.append(f"Generation: {generation_id}")
    return "\n".join(lines)


def _member_referenced_names(member: RobloxApiMember) -> list[tuple[str, str | None]]:
    """``(name, category)`` pairs a member's types textually carry.

    ``category`` is only available when the original dump structure was
    a ``{"Category": ..., "Name": ...}`` object; plain-string types (the
    common case once flattened by :func:`_type_name`) carry ``None`` and
    are matched by exact name against both the class and enum catalogs
    in :func:`_class_and_enum_references`.
    """
    names: list[tuple[str, str | None]] = []
    if member.value_type:
        names.append((member.value_type, None))
    if member.return_type:
        names.append((member.return_type, None))
    for param in member.parameters:
        names.append((param.type, None))
    return names


def _class_and_enum_references(cls: RobloxApiClass, class_names: set[str], enum_names: set[str]) -> list[str]:
    """Recognized class/enum names referenced by ``cls``'s own members.

    Exact-name matching only, against *this generation's* own catalog —
    never fabricates a page for a name that is not itself a rendered
    class or enum (spec: "Do not generate classes solely because
    documentation mentions them").
    """
    found: set[str] = set()
    for member in cls.members:
        for name, _category in _member_referenced_names(member):
            if name in class_names or name in enum_names:
                found.add(name)
    return sorted(found)


def render_generation(dump: NormalizedApiDump, *, generation_id: str, schema_version: int) -> RenderedGeneration:
    """Render one full, deterministic API generation from a merged dump.

    Args:
        dump: The merged :class:`NormalizedApiDump` from
            :func:`build_normalized_dump`.
        generation_id: Stable identity of this generation (recorded in
            every page body as provenance, never wall-clock data).
        schema_version: Renderer schema version — a bump here forces
            downstream enrichment invalidation independent of upstream
            source changes (spec §"API plane acquisition").

    Returns:
        The :class:`RenderedGeneration`. Deterministic: reordering
        ``dump.classes``/``dump.enums`` before calling this produces
        byte-identical output (everything is (re-)sorted internally).
    """
    classes = sorted(dump.classes, key=lambda c: c.name)
    enums = sorted(dump.enums, key=lambda e: e.name)
    class_names = {c.name for c in classes}
    enum_names = {e.name for e in enums}

    catalog = RobloxApiCatalog(
        generation_id=generation_id,
        classes={c.name: class_page_id(c.name) for c in classes},
        enums={e.name: enum_page_id(e.name) for e in enums},
    )

    pages: list[WikiPageRecord] = []
    edges: list[tuple[str, str, str]] = []
    missing_doc_classes: list[str] = []

    for cls in classes:
        concept_id = class_page_id(cls.name)
        body = _render_class_body(cls, class_names | enum_names, generation_id)
        pages.append(
            WikiPageRecord(
                concept_id=concept_id,
                title=cls.name,
                category="roblox-class",
                summary=cls.description or f"Roblox API class {cls.name}.",
                body=body,
                token_count=_safe_token_count(body),
                origin="ingest",
                content_hash=hashlib.sha1(body.encode("utf-8")).hexdigest(),
            )
        )
        if cls.description is None:
            missing_doc_classes.append(cls.name)

        if cls.superclass is not None and cls.superclass in class_names:
            edges.append((concept_id, class_page_id(cls.superclass), "extends"))

        for ref_name in _class_and_enum_references(cls, class_names, enum_names):
            target = class_page_id(ref_name) if ref_name in class_names else enum_page_id(ref_name)
            if target != concept_id:
                edges.append((concept_id, target, "references"))

    for enum in enums:
        concept_id = enum_page_id(enum.name)
        body = _render_enum_body(enum, generation_id)
        pages.append(
            WikiPageRecord(
                concept_id=concept_id,
                title=f"{enum.name} (Enum)",
                category="roblox-enum",
                summary=f"Roblox API enum {enum.name}.",
                body=body,
                token_count=_safe_token_count(body),
                origin="ingest",
                content_hash=hashlib.sha1(body.encode("utf-8")).hexdigest(),
            )
        )

    pages.sort(key=lambda p: p.concept_id)
    edges = sorted(set(edges))

    return RenderedGeneration(
        pages=pages,
        edges=edges,
        catalog=catalog,
        class_count=len(classes),
        enum_count=len(enums),
        structural_only_count=len(missing_doc_classes),
        missing_doc_classes=sorted(missing_doc_classes),
        skipped=[],
    )
