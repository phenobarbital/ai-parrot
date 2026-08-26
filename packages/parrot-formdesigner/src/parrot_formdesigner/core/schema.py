"""Core form schema data models.

This module defines the canonical Pydantic models for form structure:
FormField, FormSubsection, FormSection, SubmitAction, FormSchema, and
RenderedForm.  These models are the foundation of the entire forms
abstraction layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import AuthConfig
from .constraints import DependencyRule, FieldConstraints, PostDependency
from .events import FormEventsConfig
from .options import FieldOption, OptionsSource
from .persistence import FormPersistenceConfig
from .relations import RelationSpec
from .types import FieldType, LocalizedString

# Legal (field_type) sets for each (mode, cardinality) combination of
# FormField.relation — spec §2 "Canonical combinations" table (FEAT-456).
_RELATION_REFERENCE_ONE_TYPES = frozenset({FieldType.SELECT, FieldType.DYNAMIC_SELECT, FieldType.TREE_SELECT})
_RELATION_REFERENCE_MANY_TYPES = frozenset({FieldType.MULTI_SELECT, FieldType.TAGS, FieldType.TRANSFER_LIST})


class FormType(str, Enum):
    """Discriminator for the form's structural type.

    Attributes:
        SIMPLE: A straightforward form with a linear set of questions
            (no survey blocks). This is the default.
        PRODUCT: A form bound to one or more product programmes
            (activated via FEAT-302 ``product_bindings``).
        SURVEY: A form composed of survey-style question blocks
            (imported from ``networkninja.forms.question_blocks`` where
            ``block_type == "survey"``).
    """

    SIMPLE = "simple"
    PRODUCT = "product"
    SURVEY = "survey"


class UnknownFieldsPolicy(str, Enum):
    """Policy for top-level submission keys the schema does not declare.

    Attributes:
        DROP: Discard silently (default — pre-FEAT-458 behaviour).
        KEEP: Capture into ``FormSubmission.extra_data``, subject to caps.
        REJECT: Fail the submission with 422.
    """

    DROP = "drop"  # discard silently (default — pre-FEAT-458 behaviour)
    KEEP = "keep"  # capture into FormSubmission.extra_data, subject to caps
    REJECT = "reject"  # fail the submission with 422


class FormField(BaseModel):
    """A single field within a form section.

    FormField is self-referential: GROUP fields can have children,
    and ARRAY fields can have an item_template defining the repeated element.

    Attributes:
        field_uid: Stable, immutable UUID4 identity for this field
            (FEAT-393). Auto-generated on creation and never changes for
            the lifetime of the field — the primary key for edit
            operations, rule references, blob storage keys, and internal
            maps. Client-supplied values are accepted (upsert origin).
        field_id: Unique identifier for this field within the form.
        field_type: The type of input control to render.
        label: Human-readable label shown to the user.
        description: Optional extended description or help text.
        placeholder: Optional placeholder text shown when the field is empty.
        required: Whether this field must be filled before submission.
        default: Default value for the field.
        read_only: Whether the field is displayed but cannot be edited.
        constraints: Validation constraints applied to this field.
        options: Static list of options for select/multi-select fields.
        options_source: Dynamic options source configuration.
        depends_on: Pre-dependency rule controlling conditional visibility
            (references only earlier fields in the form layout).
        post_depends: Forward effects this field has on later fields — e.g.
            computed values, cascades, or visibility changes on controls
            declared *after* this field. ``None`` (default) means no forward
            effects. Validated by :class:`~parrot_formdesigner.services.FormValidator`.
        children: Child fields for GROUP type fields.
        item_template: Template for items in ARRAY type fields.
        relation: Relational semantics of this field's value (FEAT-456),
            orthogonal to ``field_type`` — e.g. a Many2one reference, a
            Many2many reference, or a One2many embedded-rows relation.
            ``None`` (default) means the field carries no relational
            meaning; existing renderers and consumers are unaffected.
        meta: Arbitrary metadata for renderer-specific extensions.
    """

    model_config = ConfigDict(extra="forbid")

    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    field_id: str
    field_type: FieldType
    label: LocalizedString
    description: LocalizedString | None = None
    placeholder: LocalizedString | None = None
    required: bool = False
    default: Any = None
    read_only: bool = False
    constraints: FieldConstraints | None = None
    options: list[FieldOption] | None = None
    options_source: OptionsSource | None = None
    depends_on: DependencyRule | None = None
    post_depends: list[PostDependency] | None = None
    children: list[FormField] | None = None
    item_template: FormField | None = None
    relation: RelationSpec | None = None
    meta: dict[str, Any] | None = None

    @property
    def is_relational(self) -> bool:
        """Whether this field carries relational semantics (FEAT-456)."""
        return self.relation is not None

    @model_validator(mode="after")
    def _validate_relation_combination(self) -> FormField:
        """Enforce the legal (field_type x cardinality x mode) table.

        See spec §2 "Canonical combinations" (FEAT-456). Only runs when
        ``relation`` is set — ``relation=None`` is always legal and leaves
        every other field untouched.
        """
        relation = self.relation
        if relation is None:
            return self

        if relation.mode == "reference":
            if relation.cardinality == "one":
                if self.field_type not in _RELATION_REFERENCE_ONE_TYPES:
                    raise ValueError(
                        f"Field '{self.field_id}': relation mode='reference', "
                        "cardinality='one' requires field_type in "
                        f"{sorted(t.value for t in _RELATION_REFERENCE_ONE_TYPES)} "
                        f"(got {self.field_type.value!r})"
                    )
            else:  # cardinality == "many"
                if self.field_type not in _RELATION_REFERENCE_MANY_TYPES:
                    raise ValueError(
                        f"Field '{self.field_id}': relation mode='reference', "
                        "cardinality='many' requires field_type in "
                        f"{sorted(t.value for t in _RELATION_REFERENCE_MANY_TYPES)} "
                        f"(got {self.field_type.value!r})"
                    )
        else:  # mode == "embed"
            if self.field_type != FieldType.ARRAY:
                raise ValueError(
                    f"Field '{self.field_id}': relation mode='embed' requires "
                    f"field_type=ARRAY (got {self.field_type.value!r})"
                )
            if self.item_template is None:
                raise ValueError(f"Field '{self.field_id}': relation mode='embed' requires " "item_template to be set")

        return self


# Required for self-referential model resolution (also resolves PostDependency forward ref)
FormField.model_rebuild()


class FormSubsection(BaseModel):
    """A visual sub-grouping of fields within a section.

    Subsections provide an additional level of organization below sections.
    They co-exist alongside ``FormField`` items in ``FormSection.fields``,
    giving renderers a grouping boundary (header, divider, container) without
    creating a full section (which would affect wizard steps, accordion
    panels, etc.).

    Attributes:
        subsection_uid: Stable, immutable UUID4 identity for this
            subsection (FEAT-393). Auto-generated on creation.
        subsection_id: Unique identifier for this subsection within the form.
        title: Optional title displayed as a subsection header.
        description: Optional description shown under the subsection title.
        fields: List of fields in this subsection.
        depends_on: Dependency rule controlling conditional visibility.
        meta: Arbitrary metadata for renderer-specific extensions.
    """

    model_config = ConfigDict(extra="forbid")

    subsection_uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    subsection_id: str
    title: LocalizedString | None = None
    description: LocalizedString | None = None
    fields: list[FormField]
    depends_on: DependencyRule | None = None
    meta: dict[str, Any] | None = None


SectionItem = Union[FormField, FormSubsection]


class FormSection(BaseModel):
    """A logical grouping of fields within a form.

    Sections can be used to organize fields visually and in wizard-style forms
    each section becomes a separate step.

    The ``fields`` list may contain both ``FormField`` and ``FormSubsection``
    items in any order.  Use :meth:`iter_fields` to iterate over all
    ``FormField`` instances (flattening through subsections).

    Attributes:
        section_uid: Stable, immutable UUID4 identity for this section
            (FEAT-393). Auto-generated on creation.
        section_id: Unique identifier for this section.
        title: Optional title displayed as a section header.
        description: Optional description shown under the section title.
        fields: Ordered list of fields and subsections in this section.
        depends_on: Dependency rule controlling conditional section visibility.
        meta: Arbitrary metadata for renderer-specific extensions.
    """

    section_uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    section_id: str
    title: LocalizedString | None = None
    description: LocalizedString | None = None
    fields: list[SectionItem]
    depends_on: DependencyRule | None = None
    meta: dict[str, Any] | None = None

    def iter_fields(self) -> Iterator[FormField]:
        """Yield every ``FormField``, flattening through subsections."""
        for item in self.fields:
            if isinstance(item, FormSubsection):
                yield from item.fields
            else:
                yield item


def walk_fields(items: Iterable[SectionItem]) -> Iterator[FormField]:
    """Yield every ``FormField``, recursing subsections, GROUP ``children``,
    and ARRAY ``item_template``.

    This is the ONE canonical recursive traversal for the full field tree
    (FEAT-393, Module 2) — the traversal used by uniqueness validation,
    rule-reference resolution, and UID lookups. It supersedes the divergent
    walks in ``iter_all_fields()`` (layout order only, no nesting),
    ``services/validators.py``'s ``_collect_fields``/``_collect_nested_fields``,
    and ``api/operations.py``'s ``_field_index`` — those are re-keyed onto
    this helper by later tasks (TASK-1998/1999), not replaced here.

    A GROUP field's ``children`` and an ARRAY field's ``item_template`` are
    yielded AFTER their parent field (parent-before-children order).

    Args:
        items: A section's ``fields`` list (``FormField`` and/or
            ``FormSubsection`` items).

    Yields:
        Every ``FormField`` in the tree, parent-before-children order.
    """
    for item in items:
        if isinstance(item, FormSubsection):
            yield from walk_fields(item.fields)
            continue
        yield item
        if item.children:
            yield from walk_fields(item.children)
        if item.item_template is not None:
            yield from walk_fields([item.item_template])


class SubmitAction(BaseModel):
    """Defines what happens when a form is submitted.

    Attributes:
        action_type: How the submission is handled.
        action_ref: Reference to the handler (tool name, URL, event name, callback ID).
        method: HTTP method for endpoint submissions.
        confirm_message: Optional confirmation message shown before submission.
    """

    action_type: Literal["tool_call", "endpoint", "event", "callback"]
    action_ref: str
    method: str = "POST"
    confirm_message: LocalizedString | None = None
    auth: AuthConfig | None = None


MetadataSource = Literal[
    "user_id",
    "username",
    "org_id",
    "submitted_at",
    "submission_id",
    "tenant",
    "programs",
    "ip",
    "user_agent",
    "locale",
    "callback",
    "constant",
]


BUILTIN_METADATA_SOURCE_NAMES: frozenset[str] = frozenset(
    {
        "user_id",
        "username",
        "org_id",
        "submitted_at",
        "submission_id",
        "tenant",
        "programs",
        "ip",
        "user_agent",
        "locale",
    }
)


class FormMetadataField(BaseModel):
    """Declared contextual metadata captured on every form submission.

    Metadata fields are computed in a before-save enrichment step on the
    submit handler. Each declaration produces one or more ``key`` / value
    pairs that are either promoted to a real ``form_data`` column (for
    reserved core keys) or flat-merged into the submission ``data`` JSONB
    alongside the user's answers (no ``"metadata"`` sub-object).

    Attributes:
        key: Identifier under which the value is stored. Must be a valid
            Postgres identifier (``[A-Za-z_][A-Za-z0-9_]{0,62}``) so it
            is safe to promote to a column name and stable as a JSONB
            key. Validated at FormSchema construction.
        source: Where the value comes from. Built-in sources resolve
            against the inbound request / session; ``"callback"`` invokes
            a coroutine registered with ``register_form_callback``;
            ``"constant"`` returns ``default`` verbatim.
        label: Optional human-readable label (i18n supported).
        callback_ref: Required when ``source == "callback"``. Logical
            callback name looked up in the shared tenant-scoped form
            callback registry.
        default: Value substituted when the resolver returns ``None`` or
            a non-required callback fails. Also the source of truth for
            ``source == "constant"``.
        required: When ``True``, an unresolved value (resolver returns
            ``None`` after ``default`` substitution) fails the
            submission with HTTP 422.
        options: Free-form per-source options bag (e.g.
            ``{"header": "Accept-Language"}`` for ``locale``). Kept loose
            on purpose to avoid a discriminated union per built-in.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    source: MetadataSource
    label: LocalizedString | None = None
    callback_ref: str | None = None
    default: Any = None
    required: bool = False
    options: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_callback_ref(self) -> "FormMetadataField":
        if self.source == "callback" and not self.callback_ref:
            raise ValueError("callback_ref is required when source='callback'")
        if self.source != "callback" and self.callback_ref:
            raise ValueError("callback_ref is only valid when source='callback'")
        return self


class FormSchema(BaseModel):
    """The canonical representation of a complete form.

    FormSchema is the central data model of the forms abstraction layer.
    It is platform-agnostic and can be rendered to Adaptive Cards, HTML5,
    JSON Schema, or any other format via the renderer system.

    Attributes:
        form_uid: Stable, immutable UUID4 identity for this form. Auto-generated
            on creation and never changes for the lifetime of the form — the
            primary key for URL routing, registry lookups, storage, and
            cross-system references (FEAT-389).
        form_id: Human-readable slug for this form. Mutable and used for
            display/search — never as a primary key (FEAT-389).
        version: Schema version string.
        title: Human-readable form title.
        description: Optional description of the form's purpose.
        sections: Ordered list of form sections.
        submit: Optional submission action configuration.
        cancel_allowed: Whether the user can cancel/dismiss the form.
        meta: Arbitrary metadata for renderer-specific extensions.
        created_at: Optional creation timestamp (UTC). Populated by storage
            backends when forms are loaded from persistence; ``None`` for
            ad-hoc forms registered in memory.
        tenant: Optional tenant slug. When set, persistence backends use it
            to resolve the Postgres schema where the form is stored
            (e.g. ``"epson"`` → ``epson.form_schemas``). ``None`` falls
            back to the storage's default schema.
        metadata: Declared contextual metadata fields captured on submission.
        events: Optional lifecycle event bindings (FEAT-188). Maps each
            lifecycle event name (``onBeforeOpen``, ``onSchemaLoaded``,
            ``onBeforeSubmit``, ``onAfterSubmit``, ``onError``) to a
            ``FormEventBinding`` that declares the logical handler reference
            and transport options. When ``None`` (default), no lifecycle hooks
            are invoked — forms without events behave identically to their
            pre-FEAT-188 state.
        is_public: If True, the form's read and submission URLs are accessible
            without authentication. Default ``False``. Toggling to ``True``
            registers the form's public paths in navigator-auth's runtime
            exclude list; toggling to ``False`` or deleting the form unregisters
            them. (FEAT-241)
        persistence: Optional per-form persistence declaration (FEAT-457).
            When set, this form's submission data (and optionally its own
            definition body) is written to the declared destination instead
            of the generic shared storage. ``None`` (default) preserves
            today's behaviour exactly — no breaking change.
        unknown_fields: Policy for top-level submission payload keys the
            schema does not declare (FEAT-458). Defaults to
            ``UnknownFieldsPolicy.DROP`` — discard silently, identical to
            pre-FEAT-458 behaviour.
    """

    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None
    tenant: str | None = None
    metadata: list[FormMetadataField] | None = None
    events: FormEventsConfig | None = None
    # FEAT-300 — Form Builder Parity
    form_type: FormType = FormType.SIMPLE
    product_bindings: list[str] | None = None
    published_version: str | None = None
    # FEAT-241 — Public Forms
    is_public: bool = False
    # FEAT-457 — Autonomous FormSchema Persistence
    persistence: FormPersistenceConfig | None = None
    # FEAT-458 — Unknown-Field Capture
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP

    def iter_all_fields(self) -> Iterator[FormField]:
        """Yield every ``FormField`` across all sections, flattening subsections.

        NOTE: this is the renderer LAYOUT-ORDER traversal only (sections +
        subsections, top-level fields) — it does NOT recurse into GROUP
        ``children`` or ARRAY ``item_template``. It is NOT the uniqueness
        traversal; use :meth:`iter_fields_recursive` (or the module-level
        :func:`walk_fields`) for anything that must see the full tree
        (FEAT-393, Module 2).
        """
        for section in self.sections:
            yield from section.iter_fields()

    def iter_fields_recursive(self) -> Iterator[FormField]:
        """Yield every ``FormField`` in the full tree — sections,
        subsections, GROUP ``children``, and ARRAY ``item_template``
        (FEAT-393, Module 2). The canonical traversal for uniqueness
        validation, rule-reference resolution, and UID lookups.
        """
        for section in self.sections:
            yield from walk_fields(section.fields)

    @model_validator(mode="after")
    def _validate_unique_identity(self) -> "FormSchema":
        """Reject duplicate UIDs (section/subsection/field) and duplicate
        ``field_id``s anywhere in the full tree (FEAT-393, Module 2).

        Global uniqueness rests on uuid4 collision-negligibility — this
        validator only catches the realistic failure modes: a
        client-supplied duplicate UID (upsert origin), or a form authored
        (or migrated) with a repeated ``field_id``.
        """
        seen_uids: set[uuid.UUID] = set()
        seen_field_ids: set[str] = set()

        for section in self.sections:
            if section.section_uid in seen_uids:
                raise ValueError(f"Duplicate section_uid {section.section_uid} in form " f"{self.form_id!r}")
            seen_uids.add(section.section_uid)

            for item in section.fields:
                if isinstance(item, FormSubsection):
                    if item.subsection_uid in seen_uids:
                        raise ValueError(f"Duplicate subsection_uid {item.subsection_uid} " f"in form {self.form_id!r}")
                    seen_uids.add(item.subsection_uid)

        for field in self.iter_fields_recursive():
            if field.field_uid in seen_uids:
                raise ValueError(f"Duplicate field_uid {field.field_uid} in form " f"{self.form_id!r}")
            seen_uids.add(field.field_uid)

            if field.field_id in seen_field_ids:
                raise ValueError(f"Duplicate field_id {field.field_id!r} in form " f"{self.form_id!r}")
            seen_field_ids.add(field.field_id)

        return self

    @model_validator(mode="after")
    def _validate_metadata(self) -> "FormSchema":
        if not self.metadata:
            return self

        # Lazy import to avoid a hard dependency from core/ to services/.
        from ..services._identifiers import validate_identifier

        seen_keys: set[str] = set()
        field_ids = {f.field_id for f in self.iter_all_fields()}

        for entry in self.metadata:
            try:
                validate_identifier(entry.key, kind="metadata key")
            except ValueError as exc:
                raise ValueError(f"FormMetadataField.key {entry.key!r} is not a valid " f"identifier: {exc}") from exc

            if entry.key in seen_keys:
                raise ValueError(f"Duplicate metadata key {entry.key!r} in FormSchema " f"{self.form_id!r}.")
            seen_keys.add(entry.key)

            if entry.key in field_ids:
                raise ValueError(
                    f"Metadata key {entry.key!r} collides with a form " f"field_id in FormSchema {self.form_id!r}."
                )

            if entry.source == "callback" and entry.key in BUILTIN_METADATA_SOURCE_NAMES:
                raise ValueError(
                    f"Metadata key {entry.key!r} is a reserved built-in "
                    "source name and cannot be overridden with "
                    "source='callback'. Use a different key (e.g. "
                    f"'{entry.key}_ext')."
                )

        return self

    @model_validator(mode="after")
    def _validate_persistence(self) -> FormSchema:
        """Reject an author-supplied column that collides with a reserved
        submission column, or that flattens to an invalid identifier
        (FEAT-457).

        Only applies when :attr:`persistence` is set AND the target is
        tabular (``postgres_table``, ``csv_file``, ``gsheet``, or an
        ``asyncdb`` target whose driver is NOT a document driver). Document
        targets (``asyncdb`` with a document driver such as ``mongo`` or
        ``arango``) store ``data`` nested — there is no column namespace to
        collide with, so this check is skipped entirely.
        """
        if self.persistence is None:
            return self

        target = self.persistence.data
        is_document_target = target.type == "asyncdb" and target.driver in {"mongo", "arango"}
        if is_document_target:
            return self

        # Lazy import to avoid a hard dependency from core/ to services/
        # (services/sinks/mapper.py imports core/schema.py — see TASK-2421's
        # Codebase Contract note on the circular-import risk).
        from ..services.sinks.mapper import RESERVED_COLUMNS, column_names_for

        # column_names_for() raises ValueError itself for any flattened
        # column name that fails validate_identifier (e.g. a GROUP path
        # exceeding the 63-character Postgres identifier cap) — that
        # propagation covers criterion (b) with no extra call needed here.
        names = column_names_for(self)
        author_supplied = names[len(RESERVED_COLUMNS) :]

        for column in author_supplied:
            if column in RESERVED_COLUMNS:
                raise ValueError(
                    f"Field/metadata column {column!r} collides with a "
                    "reserved submission column "
                    f"({sorted(RESERVED_COLUMNS)}) and cannot be used when "
                    "persistence targets a tabular sink."
                )

        return self


def derive_stable_identities(schema: FormSchema, form_uid: uuid.UUID) -> None:
    """Re-derive a schema's child identities from ``form_uid``, in place.

    ``section_uid``, ``subsection_uid`` and ``field_uid`` default to random
    UUID4s (see the ``Field(default_factory=uuid.uuid4)`` declarations above),
    which is correct when a form is authored but wrong whenever a whole schema
    is copied: the copy inherits the original's identities verbatim, so two
    distinct forms end up claiming the same ``field_uid``.

    Each uid is derived as a UUID5 of the owning form's identity plus the
    element's stable local id (``section_id`` / ``subsection_id`` /
    ``field_id``), all of which ``FormSchema``'s post-init validator already
    guarantees unique within the form. That makes this:

    * **collision-free** — a different ``form_uid`` yields a different uid for
      every child, so no two forms can share one;
    * **deterministic** — the same (form_uid, local id) pair always produces
      the same uid, so the operation is idempotent and reproducible;
    * **structure-preserving** — nothing but the uids changes.

    Args:
        schema: The schema to rewrite. Mutated in place.
        form_uid: The form identity to derive children from. Normally
            ``schema.form_uid``; passed explicitly so callers that mint a new
            identity cannot accidentally derive from the stale one.
    """
    for section in schema.sections:
        section.section_uid = uuid.uuid5(form_uid, f"section:{section.section_id}")
        for item in section.fields:
            if isinstance(item, FormSubsection):
                item.subsection_uid = uuid.uuid5(form_uid, f"subsection:{item.subsection_id}")
    for field in schema.iter_fields_recursive():
        field.field_uid = uuid.uuid5(form_uid, f"field:{field.field_id}")


class RenderWarning(BaseModel):
    """Warning emitted when a renderer uses degraded fallback for a field type.

    Attributes:
        field_id: The ID of the field that triggered the fallback.
        field_uid: The stable UUID identity of the field that triggered the
            fallback (FEAT-393), when known. ``None`` for warnings emitted
            outside a per-field rendering context.
        field_type: The FieldType.value string (e.g. "signature").
        renderer: The renderer name ("html5" | "adaptive_card" | "pdf" |
                  "xforms" | "jsonschema" | "telegram").
        reason: Human-readable explanation (e.g. "unsupported in PDF — rendered as placeholder").
    """

    field_id: str
    field_uid: uuid.UUID | None = None
    field_type: str
    renderer: str
    reason: str


class RenderedForm(BaseModel):
    """Output of a form renderer.

    Attributes:
        content: The rendered form content (varies by renderer).
        content_type: MIME type or format identifier for the content.
        style_output: Optional style-related output from the renderer.
        metadata: Renderer-specific metadata about the rendering process.
        warnings: Degraded-rendering warnings. Empty list when all fields
            rendered natively. One entry per (field_id, renderer) pair that
            used FallbackRenderer.
    """

    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
    warnings: list[RenderWarning] = []
