"""Relational field aspect data models.

This module defines ``EntityRef`` and ``RelationSpec``, the two Pydantic
models used to express relational semantics (Many2one, Many2many, and
One2many, in Odoo terms) as an optional aspect on ``FormField`` — see
``FormField.relation`` in :mod:`parrot_formdesigner.core.schema` (wired in
a later module; this module is intentionally leaf-level and imports
nothing else from the package).

Namespace conventions for ``EntityRef.namespace`` (free-form, documented
only — unknown namespaces are allowed by design and simply ignored by
consumers that do not recognize them):

- ``"odoo"`` — an Odoo model name (e.g. ``"res.partner"``) as ``entity``.
- ``"db"`` — a database table, typically ``schema.table`` (e.g.
  ``"public.customers"``) as ``entity``.
- ``"api"`` — an external API resource identifier as ``entity``.
- ``"formdesigner"`` — another parrot-formdesigner form, with ``entity``
  set to that form's ``form_id``.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class EntityRef(BaseModel):
    """Identifies the target entity of a relation.

    Attributes:
        namespace: Free-form namespace identifying the kind of target
            (documented conventions: ``"odoo"``, ``"db"``, ``"api"``,
            ``"formdesigner"``; unrecognized namespaces are permitted by
            design — there is no central registry, and consumers that do
            not recognize a namespace simply ignore the relation).
        entity: The target entity identifier within ``namespace`` (e.g.
            ``"res.partner"``, ``"public.customers"``, or a ``form_id``
            when ``namespace == "formdesigner"``).
        key_field: The target's key field to use for identity. ``None``
            means the target's default key (e.g. its primary key).
    """

    model_config = ConfigDict(extra="forbid")

    namespace: str
    entity: str
    key_field: str | None = None


class RelationSpec(BaseModel):
    """Relational semantics of a field's value, orthogonal to field_type.

    Attributes:
        cardinality: ``"one"`` for a single reference (Many2one),
            ``"many"`` for multiple references (Many2many) or embedded
            child rows (One2many).
        target: The :class:`EntityRef` this relation points to.
        mode: ``"reference"`` for a field whose value is an ID (or list of
            IDs) pointing at ``target``; ``"embed"`` for a field whose
            value is a list of embedded child rows owned by the parent
            record (One2many), reusing the existing ``ARRAY`` +
            ``item_template`` machinery.
        display_field: Optional target field shown to users in place of
            the raw ID (e.g. a partner's ``name``).
        inverse_field: In embed mode, the child field that points back to
            the parent record. Required when ``mode == "embed"``.
        on_delete: Passthrough hint only — ``"restrict"``, ``"cascade"``,
            or ``"set_null"``. Not enforced in v1; interpretation is left
            to the consumer (e.g. an Odoo renderer/toolkit).
        filters: Consumer-interpreted filters narrowing the target set
            (e.g. restrict option fetching to active records only). Not
            interpreted by parrot-formdesigner itself.
    """

    model_config = ConfigDict(extra="forbid")

    cardinality: Literal["one", "many"]
    target: EntityRef
    mode: Literal["reference", "embed"] = "reference"
    display_field: str | None = None
    inverse_field: str | None = None
    on_delete: Literal["restrict", "cascade", "set_null"] | None = None
    filters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_embed_mode(self) -> "RelationSpec":
        """Validate embed-mode constraints (spec-local only).

        ``mode="embed"`` requires ``inverse_field`` to be set and
        ``cardinality`` to be ``"many"`` (a parent record cannot embed a
        single child field without knowing which field owns the back
        reference, and single embedded rows are not a supported shape in
        v1). field_type/combination validation against the parent
        ``FormField`` is out of scope here — see
        :mod:`parrot_formdesigner.core.schema`.
        """
        if self.mode == "embed":
            if self.inverse_field is None:
                raise ValueError(
                    "RelationSpec: mode='embed' requires 'inverse_field' "
                    "to be set (the child field pointing back to the "
                    "parent record)."
                )
            if self.cardinality != "many":
                raise ValueError(
                    "RelationSpec: mode='embed' requires cardinality='many' " f"(got cardinality={self.cardinality!r})."
                )
        return self
