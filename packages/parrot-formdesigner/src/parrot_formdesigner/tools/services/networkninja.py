"""NetworkninjaFormService — NetworkNinja PostgreSQL form-source service.

Migrated verbatim from DatabaseFormTool in tools/database_form.py.
Owns the SQL query, field-type map, and all mapping helpers.
"""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from typing import Any, Literal, cast

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from ...core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldConstraints,
    LogicGroup,
)
from ...core.options import FieldOption
from ...core.resolution import resolve_rule_references
from ...core.schema import (
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
    FormType,
)
from ...core.types import FieldType
from .abstract import AbstractFormService

# ---------------------------------------------------------------------------
# Stable import identity
# ---------------------------------------------------------------------------

#: Namespace for every UUIDv5 minted by this importer. Derived (not a magic
#: literal) so the value is reproducible from the URI alone.
_IDENTITY_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://parrot-formdesigner/import/networkninja"
)


def stable_form_uid(formid: int | str, orgid: int | str) -> uuid.UUID:
    """Derive the deterministic ``form_uid`` for a networkninja source form.

    The importer must be idempotent: re-importing the same source form has to
    yield the SAME ``form_uid``, or ``FormRegistry.register`` rejects it as a
    new form claiming an already-owned slug (``db-form-<formid>-<orgid>``),
    and every ``field_uid``-keyed answer, partial save, and resolved rule is
    orphaned.

    Args:
        formid: Numeric form identifier at the source.
        orgid: Organization ID that owns the form.

    Returns:
        A UUIDv5 that is a pure function of ``(formid, orgid)``.
    """
    return uuid.uuid5(_IDENTITY_NAMESPACE, f"networkninja:{orgid}:{formid}")


def _apply_stable_identity(schema: FormSchema, form_uid: uuid.UUID) -> None:
    """Rewrite the schema's auto-generated UUID4 identities to stable UUIDv5s.

    ``FormSchema``/``FormSection``/``FormField`` all default their ``*_uid``
    to ``uuid.uuid4()``, which makes an import non-reproducible. Every uid is
    re-derived here from the form's own identity plus the element's stable
    local id (``section_id`` / ``field_id`` — both already validated unique
    by ``FormSchema``'s post-init validator, which ran when the schema was
    constructed).

    Mutates ``schema`` in place.

    Args:
        schema: The freshly built schema whose uids are still random.
        form_uid: The deterministic form identity to derive children from.
    """
    schema.form_uid = form_uid
    for section in schema.sections:
        section.section_uid = uuid.uuid5(form_uid, f"section:{section.section_id}")
        for item in section.fields:
            if isinstance(item, FormSubsection):
                item.subsection_uid = uuid.uuid5(
                    form_uid, f"subsection:{item.subsection_id}"
                )
    for field in schema.iter_fields_recursive():
        field.field_uid = uuid.uuid5(form_uid, f"field:{field.field_id}")


def _prune_dangling_rule_references(schema: FormSchema) -> int:
    """Drop rule conditions that point at a field this import did not build.

    ``question_id_index`` resolves a condition's target through the ACTIVE
    METADATA, which is a superset of the fields actually built: a question
    whose ``data_type`` is missing from ``_FIELD_TYPE_MAP`` is skipped, and a
    column repeated across blocks is imported once. Either way a rule can end
    up naming a ``field_id`` that does not exist.

    ``resolve_rule_references`` RAISES on such a reference, which would turn a
    form that merely loses one question into a form that fails to import at
    all. The importer's own convention is the opposite — ``_map_logic_groups``
    already skips conditions it cannot resolve — so unresolvable conditions
    are dropped here to match, and a rule left with nothing is dropped whole
    (an empty condition list reads as "unconditional" to ``_eval_logic``,
    which would be a lie).

    FEAT-440: a ``groups``-carrying rule (store-group gating, spec §3
    Module 4) keeps its own flat ``conditions`` EMPTY by design — the flat
    list is not "everything pruned away" for such a rule, it never carried
    anything to begin with. Each group's conditions are pruned the same way
    as the flat list; a group left with nothing is dropped as a whole
    alternative (an empty group reads as "always matches" to
    ``_eval_logic``'s empty-list convention, which would wrongly reveal the
    element unconditionally). The rule itself is only dropped when BOTH the
    flat conditions and every group end up empty.

    No source form triggers this today: all 91 forms in the corpus use only
    mapped data_types. It is a guard against the next new ``data_type`` at
    the source turning a partial import into a total failure.

    Mutates ``schema`` in place.

    Args:
        schema: The freshly built schema.

    Returns:
        The number of conditions dropped.
    """
    known = {f.field_id for f in schema.iter_fields_recursive()}
    dropped = 0

    def _prune_conditions(conditions: list[FieldCondition]) -> list[FieldCondition]:
        nonlocal dropped
        kept = [
            c for c in conditions
            if (c.source or "field") != "field" or (c.field_id or "") in known
        ]
        dropped += len(conditions) - len(kept)
        return kept

    def _prune(rule: DependencyRule | None) -> DependencyRule | None:
        if rule is None:
            return None

        rule.conditions = _prune_conditions(rule.conditions)

        if rule.groups:
            pruned_groups: list[LogicGroup] = []
            for group in rule.groups:
                group.conditions = _prune_conditions(group.conditions)
                if group.conditions:
                    pruned_groups.append(group)
                # A group pruned to nothing is dropped as a whole
                # alternative, not kept as an unconditional match.
            rule.groups = pruned_groups or None

        if not rule.conditions and not rule.groups:
            return None
        return rule

    for section in schema.sections:
        section.depends_on = _prune(section.depends_on)
    for field in schema.iter_fields_recursive():
        field.depends_on = _prune(field.depends_on)
    return dropped


# ---------------------------------------------------------------------------
# SQL Query
# ---------------------------------------------------------------------------

_FORM_QUERY = """
SELECT
    f.formid, f.form_name, f.description, f.client_id, f.client_name, f.orgid,
    f.question_blocks,
    jsonb_agg(
        jsonb_build_object(
            'column_id', m.column_id, 'column_name', m.column_name,
            'description', m.description, 'data_type', m.data_type,
            'options', m.options
        )
    ) AS metadata
FROM networkninja.forms f
JOIN networkninja.form_metadata m USING(formid)
WHERE f.formid = $1 AND f.orgid = $2 AND m.is_active = true
GROUP BY f.formid, f.form_name, f.description, f.client_id, f.client_name,
         f.orgid, f.question_blocks
"""

# ---------------------------------------------------------------------------
# DB field type → FieldType mapping
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ImportDiffReport models (FEAT-300 TASK-006)
# ---------------------------------------------------------------------------


class ImportDiffEntry(BaseModel):
    """Per-field entry in an ImportDiffReport.

    Attributes:
        column_name: The source ``column_name`` from ``form_metadata``.
        source_data_type: The raw ``data_type`` string from the source.
        mapped_field_type: The resolved ``FieldType.value`` string, or
            ``None`` when mapping failed.
        status: One of ``"mapeado"`` (fully mapped), ``"aproximado"``
            (approximate mapping with meta hint), or
            ``"requiere_intervencion"`` (manual review needed).
        note: Human-readable note about the mapping decision.
        options_source: Provenance of the field's options — one of
            ``"metadata"``, ``"inline"``, ``"logic_groups"``, ``"none"`` for
            option-typed fields; ``None`` for non-option fields (FEAT-325).
    """

    model_config = ConfigDict(extra="forbid")

    column_name: str
    source_data_type: str
    mapped_field_type: str | None = None
    status: str  # "mapeado" | "aproximado" | "requiere_intervencion"
    note: str = ""
    options_source: str | None = None  # "metadata" | "inline" | "logic_groups" | "none"


class ImportDiffReport(BaseModel):
    """Aggregate report for a single networkninja form import.

    Attributes:
        form_id: The ``FormSchema.form_id`` produced by the import.
        source: Always ``"networkninja"``.
        imported_at: UTC timestamp of the import.
        fields: One entry per imported field column.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    source: str = "networkninja"
    imported_at: datetime
    fields: list[ImportDiffEntry] = []


# ---------------------------------------------------------------------------
# Field type mapping table
# ---------------------------------------------------------------------------


#: Maps DB ``data_type`` strings to ``(FieldType, extra_kwargs)`` tuples.
#: A ``None`` value means "explicitly unsupported — skip with warning".
_FIELD_TYPE_MAP: dict[str, tuple[FieldType, dict[str, Any]] | None] = {
    "FIELD_TEXT": (FieldType.TEXT, {}),
    "FIELD_TEXTAREA": (FieldType.TEXT_AREA, {}),
    "FIELD_INTEGER": (FieldType.INTEGER, {}),
    "FIELD_FLOAT2": (FieldType.NUMBER, {}),
    "FIELD_YES_NO": (FieldType.BOOLEAN, {}),
    "FIELD_SELECT": (FieldType.SELECT, {}),
    "FIELD_SELECT_RADIO": (
        FieldType.SELECT,
        {"meta": {"render_as": "radio"}},
    ),
    "FIELD_MULTISELECT": (FieldType.MULTI_SELECT, {}),
    "FIELD_DATE": (FieldType.DATE, {}),
    "FIELD_MONEY": (FieldType.NUMBER, {"meta": {"render_as": "money"}}),
    "FIELD_SUBSECTION": (
        FieldType.GROUP,
        {"read_only": True, "meta": {"render_as": "subsection"}},
    ),
    "FIELD_IMAGE_UPLOAD_MULTIPLE": (
        FieldType.FILE,
        {"meta": {"accept": "image/*", "multiple": True}},
    ),
    "FIELD_DISPLAY_TEXT": (
        FieldType.TEXT,
        {"read_only": True, "meta": {"render_as": "display_text"}},
    ),
    "FIELD_DISPLAY_IMAGE": (
        FieldType.IMAGE,
        {"read_only": True, "meta": {"render_as": "display_image"}},
    ),
    # FEAT-300: FIELD_SIGNATURE_CAPTURE now maps to SIGNATURE (was None)
    "FIELD_SIGNATURE_CAPTURE": (FieldType.SIGNATURE, {}),
    # FEAT-300: 9 new verified-live data_types
    "FIELD_FORMULA": (
        FieldType.FORMULA,
        {"meta": {"expression": None, "result_type": None}},
    ),
    "FIELD_IMAGE_UPLOAD": (
        FieldType.FILE,
        {"meta": {"accept": "image/*"}},
    ),
    "FIELD_AGREEMENT_CHECKBOX": (
        FieldType.BOOLEAN,
        {"meta": {"render_as": "agreement"}},
    ),
    "FIELD_DURATION": (
        FieldType.TEXT,
        {"meta": {"render_as": "duration"}},
    ),
    "FIELD_DATETIME": (FieldType.DATETIME, {}),
    "FIELD_TIME": (FieldType.TIME, {}),
    "FIELD_HYPERLINK": (FieldType.URL, {}),
    "FIELD_PHONENUMBER": (FieldType.PHONE, {}),
    "FIELD_TOTAL": (
        FieldType.FORMULA,
        {"meta": {"render_as": "total", "expression": None, "result_type": None}},
    ),
}

# Field types that carry selectable options
_OPTION_FIELD_TYPES: set[str] = {
    "FIELD_SELECT",
    "FIELD_SELECT_RADIO",
    "FIELD_MULTISELECT",
}


class NetworkninjaFormService(AbstractFormService):
    """NetworkNinja PostgreSQL form-source service.

    Owns the SQL query against ``networkninja.forms`` + ``networkninja.form_metadata``
    and the question_blocks → FormSchema transformation pipeline.

    DSN resolution order:
        1. constructor ``dsn=`` kwarg
        2. ``PARROT_NETWORKNINJA_DSN`` env var
        3. ``parrot.conf.default_dsn``

    Example:
        svc = NetworkninjaFormService(dsn="postgres://user:pw@host/db")
        raw = await svc.fetch(formid=42, orgid=7)
        form = svc.to_form_schema(raw)
    """

    def __init__(
        self,
        db: Any | None = None,
        dsn: str | None = None,
    ) -> None:
        """Initialize NetworkninjaFormService.

        Args:
            db: Optional pre-configured AsyncDB instance. When provided it is
                reused directly (supports connection pooling / test injection).
            dsn: PostgreSQL DSN. Falls back to ``PARROT_NETWORKNINJA_DSN``
                env var, then ``parrot.conf.default_dsn``.
        """
        self._db = db
        self._dsn = dsn
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # AbstractFormService interface
    # ------------------------------------------------------------------

    async def fetch(
        self,
        *,
        formid: int,
        orgid: int,
        **_: Any,
    ) -> dict[str, Any]:
        """Run the parameterized SQL query and return the row dict.

        Args:
            formid: Numeric form identifier.
            orgid: Organization ID that owns the form.
            **_: Additional kwargs are ignored.

        Returns:
            Row dict with form data.

        Raises:
            RuntimeError: When no row matches the (formid, orgid) pair, or
                on DB error.
        """
        from asyncdb import AsyncDB  # noqa: PLC0415

        db = self._db or AsyncDB("pg", dsn=self._get_dsn())

        async with await db.connection() as conn:
            result, errors = await conn.queryrow(_FORM_QUERY, formid, orgid)

        if errors:
            raise RuntimeError(f"DB query failed for formid={formid}: {errors}")

        if result is None:
            raise RuntimeError(f"Form not found: formid={formid}, orgid={orgid}")

        return result

    def to_form_schema(self, raw: dict[str, Any]) -> FormSchema:
        """Transform the row dict into a FormSchema.

        Args:
            raw: Dict with keys: formid, form_name, description, orgid,
                 question_blocks (JSON string or list), metadata (list of dicts).

        Returns:
            Fully constructed FormSchema.
        """
        schema, _ = self._build_form_schema_with_report(raw)
        return schema

    def import_with_report(
        self, raw: dict[str, Any]
    ) -> tuple[FormSchema, ImportDiffReport]:
        """Transform a raw row into a FormSchema plus an ImportDiffReport.

        The form is always returned (never aborted).  Unmappable fields are
        included in the report with ``status="requiere_intervencion"`` and
        the form is left as draft (``published_version=None``).

        Args:
            raw: Dict with keys: formid, form_name, description, orgid,
                 question_blocks (JSON string or list), metadata (list of dicts).

        Returns:
            Tuple of ``(FormSchema, ImportDiffReport)``.
        """
        return self._build_form_schema_with_report(raw)

    # ------------------------------------------------------------------
    # DSN resolution
    # ------------------------------------------------------------------

    def _get_dsn(self) -> str:
        """Return the configured DSN, env var, or package default.

        Returns:
            DSN string suitable for asyncdb's ``pg`` driver.

        Raises:
            RuntimeError: When no DSN is found anywhere.
        """
        if self._dsn:
            return self._dsn
        env_dsn = os.environ.get("PARROT_NETWORKNINJA_DSN")
        if env_dsn:
            return env_dsn
        try:
            from parrot.conf import default_dsn  # noqa: PLC0415
            if default_dsn:
                return default_dsn
        except ImportError:
            pass
        raise RuntimeError(
            "No DSN configured. Set PARROT_NETWORKNINJA_DSN env var or pass dsn= to the constructor."
        )

    # ------------------------------------------------------------------
    # Form building pipeline
    # ------------------------------------------------------------------

    def _build_form_schema_with_report(
        self, row: dict[str, Any]
    ) -> tuple[FormSchema, ImportDiffReport]:
        """Internal pipeline that produces both the FormSchema and the diff report.

        Args:
            row: DB result row dict.

        Returns:
            ``(FormSchema, ImportDiffReport)`` pair.
        """
        report_entries: list[ImportDiffEntry] = []
        schema = self._build_form_schema(row, report_entries=report_entries)
        form_id = schema.form_id
        report = ImportDiffReport(
            form_id=form_id,
            source="networkninja",
            imported_at=datetime.now(timezone.utc),
            fields=report_entries,
        )
        return schema, report

    def _build_form_schema(
        self,
        row: dict[str, Any],
        report_entries: list[ImportDiffEntry] | None = None,
    ) -> FormSchema:
        """Transform a DB result row into a FormSchema.

        Args:
            row: Dict with keys: formid, form_name, description, orgid,
                 question_blocks (JSON string or list), metadata (list of dicts).
            report_entries: Optional list to accumulate ``ImportDiffEntry``
                objects.  When provided, all mapped and unmapped fields are
                recorded here; the import NEVER aborts.

        Returns:
            Fully constructed FormSchema.
        """
        form_name: str = row.get("form_name") or f"form_{row['formid']}"
        form_id = f"db-form-{row['formid']}-{row['orgid']}"
        description: str | None = row.get("description") or None

        # Build metadata index: column_name → {column_id, data_type, description}
        raw_metadata: list[dict[str, Any]] = row.get("metadata") or []
        meta_index = self._build_metadata_index(raw_metadata)

        # Parse question_blocks — may be:
        #   a) A JSON string (most rows) — must json.loads()
        #   b) Already a list (JSONB-native)
        #   c) Legacy double-encoding: JSON string wrapping a list that uses
        #      old keys (question_block_id, question_block_type, etc.)
        question_blocks_raw = row.get("question_blocks") or "[]"
        question_blocks: list[dict[str, Any]] = self._normalize_question_blocks(
            question_blocks_raw
        )

        # Build question_id → column_name reverse index (for conditional resolution)
        question_id_index = self._build_question_id_index(question_blocks, meta_index)

        # Pre-scan questions to collect options for select-type fields
        select_options, options_provenance = self._collect_select_options(
            question_blocks, question_id_index, meta_index
        )

        # column_name → {option_value: option_id} catalog, used to re-index
        # EQUALS conditions to the option_id value-space (FEAT-325 Module 3).
        option_id_catalog = self._build_option_id_catalog(meta_index)

        # Derive form_type from block_type (FEAT-300):
        # any block with block_type == "survey" → FormType.SURVEY; else SIMPLE.
        # PRODUCT is never detected from networkninja (FEAT-302 only).
        form_type = FormType.SIMPLE
        for block in question_blocks:
            if block.get("block_type") == "survey":
                form_type = FormType.SURVEY
                break

        # Build sections — each question_block → one FormSection.
        #
        # `seen_columns` is shared across blocks on purpose. The source lets
        # one column appear in several blocks (on db-form-10-69, columns
        # 8984/8985/8986 are help notes repeated as a header in blocks 27 and
        # 28), but field_id is derived from the column and FormSchema rejects
        # duplicates — so without this the whole import dies with
        # "Duplicate field_id", which the API surfaces as an opaque HTTP 500.
        # First occurrence wins; the rest are recorded in the diff report.
        seen_columns: set[str] = set()
        sections: list[FormSection] = []
        for block in question_blocks:
            section = self._map_block_to_section(
                block, meta_index, question_id_index, select_options,
                options_provenance, option_id_catalog,
                report_entries=report_entries,
                seen_columns=seen_columns,
            )
            if section is not None:
                sections.append(section)

        schema = FormSchema(
            form_id=form_id,
            title=form_name,
            description=description,
            sections=sections,
            form_type=form_type,
        )

        # Identity must be a pure function of the source row, never uuid4 —
        # see stable_form_uid() for why a random uid breaks re-import.
        _apply_stable_identity(
            schema, stable_form_uid(row["formid"], row["orgid"])
        )

        # Rules are authored here against field_id, but FEAT-393 made
        # field_uid the authoritative reference: `_eval_condition` reads
        # `resolve_answer(form, condition.field_uid, answers)` and returns
        # None outright when field_uid is unset, so an unresolved rule is a
        # rule that can never fire server-side. Resolution has to run AFTER
        # _apply_stable_identity, because that is what gives the fields the
        # uids being pointed at.
        dangling = _prune_dangling_rule_references(schema)
        if dangling:
            self.logger.warning(
                "Dropped %d rule condition(s) in %s pointing at fields this "
                "import did not build", dangling, schema.form_id,
            )
        resolve_rule_references(schema)
        return schema

    @staticmethod
    def _normalize_question_blocks(
        raw: str | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Normalize legacy and current question_blocks formats.

        Handles:
        - ``str`` → ``json.loads()``
        - Legacy keys: ``question_block_id`` → ``block_id``,
          ``question_block_type`` → ``block_type``,
          ``question_block_logic_groups`` → ``block_logic_groups``.
        - Missing/null ``block_type`` → ``"simple"``.

        Args:
            raw: Raw question_blocks value from the DB row.

        Returns:
            Normalised list of block dicts.
        """
        if isinstance(raw, str):
            try:
                blocks = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        else:
            blocks = list(raw)

        normalised: list[dict[str, Any]] = []
        for block in blocks:
            b: dict[str, Any] = dict(block)  # shallow copy for safety

            # Legacy key migration
            if "block_id" not in b and "question_block_id" in b:
                b["block_id"] = b.pop("question_block_id")
            if "block_type" not in b and "question_block_type" in b:
                b["block_type"] = b.pop("question_block_type")
            if "block_logic_groups" not in b and "question_block_logic_groups" in b:
                b["block_logic_groups"] = b.pop("question_block_logic_groups")

            # Default missing/null block_type to "simple"
            if not b.get("block_type"):
                b["block_type"] = "simple"

            normalised.append(b)

        return normalised

    # ------------------------------------------------------------------
    # Index builders
    # ------------------------------------------------------------------

    def _build_metadata_index(
        self, raw_metadata: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Build column_name → metadata dict index.

        Args:
            raw_metadata: List of metadata dicts from the DB JSONB aggregate.

        Returns:
            Dict mapping column_name (str) to its metadata record.
        """
        index: dict[str, dict[str, Any]] = {}
        for entry in raw_metadata:
            col_name = str(entry.get("column_name", ""))
            if col_name:
                index[col_name] = {
                    "column_id": entry.get("column_id"),
                    "data_type": entry.get("data_type"),
                    "description": entry.get("description"),
                    "options": self._normalize_options(entry.get("options")),
                }
        return index

    @staticmethod
    def _normalize_options(raw: Any) -> list[dict[str, Any]]:
        """Coerce a raw ``form_metadata.options`` value into a list of dicts.

        ``form_metadata.options`` is not uniformly shaped in the source: some
        columns store a proper JSONB array of option objects, but others store
        a JSON *string* (e.g. the double-encoded ``"[]"`` on non-select
        columns, or occasionally ``"[{...}]"``), a scalar, or ``NULL``. Every
        downstream consumer (``_collect_select_options``,
        ``_build_option_id_catalog``) assumes a list of dicts, so all coercion
        happens here once (FEAT-325).

        Args:
            raw: The raw ``options`` value from the metadata aggregate.

        Returns:
            A list containing only dict-shaped option entries; ``[]`` when the
            value is null, a non-list scalar, or unparseable.
        """
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(raw, list):
            return []
        return [opt for opt in raw if isinstance(opt, dict)]

    def _build_option_id_catalog(
        self, meta_index: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, str]]:
        """Build column_name → {option_value: option_id} from metadata options.

        Used to re-index ``EQUALS`` conditions (whose
        ``condition_comparison_value`` is human text) to the ``option_id``
        value-space that ``FieldOption.value`` now uses for metadata-backed
        selects (FEAT-325).

        Args:
            meta_index: Active metadata index from ``_build_metadata_index``.

        Returns:
            Dict mapping column_name → {option_value (str): option_id (str)}.
            Columns with no metadata options are absent from the result.
        """
        catalog: dict[str, dict[str, str]] = {}
        for col, meta in meta_index.items():
            meta_options: list[dict[str, Any]] = meta.get("options") or []
            if not meta_options:
                continue
            col_catalog: dict[str, str] = {}
            for opt in meta_options:
                option_id = opt.get("option_id")
                option_value = opt.get("option_value")
                if option_id is None or option_value is None:
                    continue
                col_catalog[str(option_value)] = str(option_id)
            if col_catalog:
                catalog[col] = col_catalog
        return catalog

    def _build_question_id_index(
        self,
        question_blocks: list[dict[str, Any]],
        meta_index: dict[str, dict[str, Any]],
    ) -> dict[str, str]:
        """Build question_id → column_name reverse index.

        ``question_column_name`` is an int in the JSON, while ``column_name``
        in the metadata index is a string. This method casts for comparison.

        Used to resolve ``condition_question_reference_id`` in conditional logic.

        Args:
            question_blocks: Parsed list of question block dicts.
            meta_index: Active metadata index from ``_build_metadata_index``.

        Returns:
            Dict mapping str(question_id) → column_name.
        """
        index: dict[str, str] = {}
        for block in question_blocks:
            for question in block.get("questions") or []:
                qid = question.get("question_id")
                # question_column_name is int in JSON, column_name in metadata is str
                col_name = str(question.get("question_column_name", ""))
                if qid is not None and col_name in meta_index:
                    index[str(qid)] = col_name
        return index

    # ------------------------------------------------------------------
    # Multi-select option pre-scan
    # ------------------------------------------------------------------

    def _collect_select_options(
        self,
        question_blocks: list[dict[str, Any]],
        question_id_index: dict[str, str],
        meta_index: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, list[FieldOption]], dict[str, str]]:
        """Pre-scan questions to collect option values for select-type fields.

        ``form_metadata.options`` (the canonical metadata catalog) is the
        primary source: ``FieldOption(value=str(option_id), label=option_value,
        disabled=not is_active)``, deduplicated by ``option_id``. Inline
        ``options`` arrays in the question JSON, then ``logic_groups``
        conditions referencing the column, are used ONLY as a fallback when a
        column's metadata catalog is empty — preserving pre-FEAT-325 behaviour
        for logic-group-only / inline-only selects.

        Args:
            question_blocks: All parsed question blocks.
            question_id_index: question_id → column_name reverse index.
            meta_index: Active metadata index for type lookups.

        Returns:
            Tuple of:
            - Dict mapping column_name → deduplicated list of FieldOption.
            - Dict mapping column_name → provenance
              (``"metadata" | "inline" | "logic_groups" | "none"``) for every
              option-typed column present in ``meta_index``.
        """
        option_columns = {
            col
            for col, meta in meta_index.items()
            if meta.get("data_type") in _OPTION_FIELD_TYPES
        }

        collector: dict[str, dict[str, FieldOption]] = {}  # col_name → {value: FieldOption}
        provenance: dict[str, str] = {}
        metadata_populated: set[str] = set()

        # Source 0 (primary): form_metadata.options catalog
        for col in option_columns:
            meta_options: list[dict[str, Any]] = meta_index[col].get("options") or []
            if not meta_options:
                continue
            col_collector: dict[str, FieldOption] = {}
            for opt in meta_options:
                option_id = opt.get("option_id")
                if option_id is None:
                    continue
                value = str(option_id)
                option_value = opt.get("option_value")
                is_active = opt.get("is_active", True)
                col_collector[value] = FieldOption(
                    value=value,
                    label=str(option_value) if option_value is not None else value,
                    disabled=not is_active,
                )
            if col_collector:
                collector[col] = col_collector
                provenance[col] = "metadata"
                metadata_populated.add(col)

        # Fallback collector (legacy behaviour) — populated only for columns
        # whose metadata catalog is empty.
        legacy_collector: dict[str, dict[str, str]] = {}  # col_name → {value: label}
        inline_populated: set[str] = set()
        logic_populated: set[str] = set()

        def _scan_conditions(conditions: list[dict[str, Any]]) -> None:
            """Extract option values from a list of conditions."""
            for cond in conditions:
                ref_qid = str(
                    cond.get("condition_question_reference_id", "")
                )
                ref_col = question_id_index.get(ref_qid)
                if not ref_col or ref_col in metadata_populated:
                    continue

                ref_meta = meta_index.get(ref_col, {})
                if ref_meta.get("data_type") not in _OPTION_FIELD_TYPES:
                    continue

                comp_value = cond.get("condition_comparison_value")
                if comp_value is not None:
                    if ref_col not in legacy_collector:
                        legacy_collector[ref_col] = {}
                    # comparison_value is the human-readable label
                    legacy_collector[ref_col][str(comp_value)] = str(comp_value)
                    logic_populated.add(ref_col)

        for block in question_blocks:
            # Scan block-level logic groups (question_block_logic_groups)
            for group in self._block_logic_groups(block):
                _scan_conditions(group.get("conditions") or [])

            for question in block.get("questions") or []:
                # Source 1: inline options on the question itself
                col_name = str(question.get("question_column_name", ""))
                if col_name in meta_index and col_name not in metadata_populated:
                    ref_meta = meta_index.get(col_name, {})
                    if ref_meta.get("data_type") in _OPTION_FIELD_TYPES:
                        inline_opts = question.get("options") or []
                        for opt in inline_opts:
                            value = opt.get("value") or opt.get("option_id")
                            label = (
                                opt.get("label")
                                or opt.get("option_text")
                                or opt.get("text")
                            )
                            if value is not None:
                                if col_name not in legacy_collector:
                                    legacy_collector[col_name] = {}
                                legacy_collector[col_name][str(value)] = (
                                    str(label) if label else str(value)
                                )
                                inline_populated.add(col_name)

                # Source 2: options inferred from conditional references
                logic_groups = (
                    question.get("logic_groups")
                    or question.get("question_logic_groups")
                    or []
                )
                for group in logic_groups:
                    _scan_conditions(group.get("conditions") or [])

        for col, options in legacy_collector.items():
            collector[col] = {
                value: FieldOption(value=value, label=label)
                for value, label in options.items()
            }
            if col in inline_populated:
                provenance[col] = "inline"
            elif col in logic_populated:
                provenance[col] = "logic_groups"

        # Every option-typed column present in meta_index gets a provenance
        # entry, even when no options were found anywhere.
        for col in option_columns:
            provenance.setdefault(col, "none")

        return (
            {col: list(opts.values()) for col, opts in collector.items()},
            provenance,
        )

    # ------------------------------------------------------------------
    # Section and field mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _block_logic_groups(block: dict[str, Any]) -> list[dict[str, Any]]:
        """Return a block's logic groups under either spelling of the key.

        ``_normalise_question_blocks`` migrates the legacy
        ``question_block_logic_groups`` key to ``block_logic_groups``, but
        both readers here also run on blocks that never passed through it
        (direct unit-test input), so both spellings are accepted.

        Args:
            block: A single question block dict.

        Returns:
            The block's logic groups, or an empty list.
        """
        return (
            block.get("block_logic_groups")
            or block.get("question_block_logic_groups")
            or []
        )

    @staticmethod
    def _block_store_groups(block: dict[str, Any]) -> list[str]:
        """Return a block's store-group gating names, if the source carries any.

        Mirrors :meth:`_block_logic_groups`: the store-group condition is
        section-level exactly like ``block_logic_groups`` is (spec §1 —
        "blocks gated on a store group: 6 of 17"), so it is read off the
        block dict under the same ``store_groups`` key
        :meth:`_map_logic_groups` reads at question level. NO source this
        importer reads populates this key today (spec §1 Non-Goals —
        store-group membership lives only in the Recap Definition export,
        verified nowhere in the replicated database); this accessor exists
        so the mapping in :meth:`_map_logic_groups` activates the moment a
        source does supply it, and is exercised by fixtures only until then.

        Args:
            block: A single question block dict.

        Returns:
            The block's store-group names, or an empty list.
        """
        return block.get("store_groups") or []

    def _map_block_to_section(
        self,
        block: dict[str, Any],
        meta_index: dict[str, dict[str, Any]],
        question_id_index: dict[str, str],
        select_options: dict[str, list[FieldOption]],
        options_provenance: dict[str, str],
        option_id_catalog: dict[str, dict[str, str]],
        report_entries: list[ImportDiffEntry] | None = None,
        seen_columns: set[str] | None = None,
    ) -> FormSection | None:
        """Map a question_block dict to a FormSection.

        Args:
            block: A single question block dict from question_blocks.
            meta_index: Active metadata lookup.
            question_id_index: question_id → column_name reverse index.
            select_options: Pre-collected options keyed by column_name.
            options_provenance: Per-column option provenance
                (``"metadata" | "inline" | "logic_groups" | "none"``) from
                ``_collect_select_options``.
            option_id_catalog: column_name → {option_value: option_id} from
                ``_build_option_id_catalog``, used to re-index EQUALS
                conditions.
            report_entries: Optional accumulator for ``ImportDiffEntry`` objects.
            seen_columns: Columns already imported by an earlier block, mutated
                in place as this block claims new ones. A column that reappears
                is skipped, because ``field_id`` is derived from it and
                ``FormSchema`` rejects duplicates. ``None`` disables the check.

        Returns:
            FormSection if the block has at least one mappable field, else None.
        """
        block_id = block.get("block_id") or block.get("question_block_id", "")
        block_title: str | None = (
            block.get("block_description") or block.get("block_name") or None
        )
        section_id = f"section_{block_id}" if block_id else "section_default"

        fields: list[FormField] = []
        for question in block.get("questions") or []:
            col_name = str(question.get("question_column_name", ""))
            if seen_columns is not None and col_name in seen_columns:
                self.logger.debug(
                    "Skipping duplicate column '%s' in block '%s'",
                    col_name, block_id,
                )
                if report_entries is not None:
                    report_entries.append(ImportDiffEntry(
                        column_name=col_name,
                        source_data_type=(
                            meta_index.get(col_name, {}).get("data_type") or ""
                        ),
                        mapped_field_type=None,
                        status="requiere_intervencion",
                        note=(
                            f"column repeated in block '{block_id}' — already "
                            "imported from an earlier block; this occurrence "
                            "was dropped to keep field_id unique"
                        ),
                    ))
                continue

            field = self._map_question_to_field(
                question, meta_index, question_id_index, select_options,
                options_provenance, option_id_catalog,
                report_entries=report_entries,
            )
            if field is not None:
                fields.append(field)
                if seen_columns is not None:
                    seen_columns.add(col_name)

        if not fields:
            return None

        # Section-level conditional visibility. The source keeps it on the
        # block, in the same shape a question uses, under a different key —
        # so it goes through the very same translator, via a shim that
        # renames the key. Dropping it silently is not a cosmetic loss: on
        # `db-form-10-69` 15 of 17 blocks gate on one "type of visit"
        # question, and without the rule 277 of 292 fields (234 of them
        # required) render unconditionally and the form cannot be submitted.
        section_depends_on = self._map_logic_groups(
            {
                "logic_groups": self._block_logic_groups(block),
                "store_groups": self._block_store_groups(block),
            },
            question_id_index,
            option_id_catalog,
        )

        return FormSection(
            section_id=section_id,
            title=block_title,
            fields=fields,
            depends_on=section_depends_on,
        )

    def _map_question_to_field(
        self,
        question: dict[str, Any],
        meta_index: dict[str, dict[str, Any]],
        question_id_index: dict[str, str],
        select_options: dict[str, list[FieldOption]],
        options_provenance: dict[str, str],
        option_id_catalog: dict[str, dict[str, str]],
        report_entries: list[ImportDiffEntry] | None = None,
    ) -> FormField | None:
        """Map a question dict to a FormField.

        When ``report_entries`` is provided the import NEVER aborts on an
        unmappable data_type — instead a ``requiere_intervencion`` entry is
        recorded and the question is skipped (field returns ``None``).

        Formula fields (``FIELD_FORMULA`` / ``FIELD_TOTAL``) always produce a
        ``requiere_intervencion`` entry because the expression is unavailable
        at the networkninja source.

        Args:
            question: Single question dict from a question block.
            meta_index: Active metadata lookup.
            question_id_index: question_id → column_name reverse index.
            select_options: Pre-collected options keyed by column_name.
            options_provenance: Per-column option provenance
                (``"metadata" | "inline" | "logic_groups" | "none"``) from
                ``_collect_select_options``.
            option_id_catalog: column_name → {option_value: option_id} from
                ``_build_option_id_catalog``, used to re-index EQUALS
                conditions.
            report_entries: Optional accumulator for ``ImportDiffEntry`` objects.

        Returns:
            FormField if mappable, else None.
        """
        # question_column_name is stored as int in JSON — cast to str for lookup
        col_name = str(question.get("question_column_name", ""))

        # Skip if column is not in active metadata
        if col_name not in meta_index:
            self.logger.debug(
                "Skipping question: column '%s' not in active metadata", col_name
            )
            return None

        meta_entry = meta_index[col_name]
        data_type: str = meta_entry.get("data_type") or ""

        # Resolve field type from mapping table
        if data_type not in _FIELD_TYPE_MAP:
            self.logger.warning(
                "Unknown data_type '%s' for column '%s'",
                data_type, col_name,
            )
            if report_entries is not None:
                report_entries.append(ImportDiffEntry(
                    column_name=col_name,
                    source_data_type=data_type,
                    mapped_field_type=None,
                    status="requiere_intervencion",
                    note=f"data_type '{data_type}' is not in the mapping table — manual review required",
                ))
            return None

        mapping = _FIELD_TYPE_MAP[data_type]
        if mapping is None:
            # Should never happen after FEAT-300 (FIELD_SIGNATURE_CAPTURE now maps),
            # but kept as a safety net for future explicitly-unsupported entries.
            self.logger.warning(
                "Explicitly unsupported data_type '%s' for column '%s'",
                data_type, col_name,
            )
            if report_entries is not None:
                report_entries.append(ImportDiffEntry(
                    column_name=col_name,
                    source_data_type=data_type,
                    mapped_field_type=None,
                    status="requiere_intervencion",
                    note=f"data_type '{data_type}' is explicitly unsupported — manual review required",
                ))
            return None

        field_type, extra_kwargs = mapping

        field_id = f"field_{col_name}"
        label: str = question.get("question_description") or col_name

        # Validations → required flag + numeric bounds
        validations: list[dict[str, Any]] = question.get("validations") or []
        required = any(
            v.get("validation_type") == "responseRequired" for v in validations
        )
        constraints, unmapped_validations = self._map_validations(
            validations, field_type
        )

        # Conditional logic → DependencyRule
        depends_on: DependencyRule | None = self._map_logic_groups(
            question, question_id_index, option_id_catalog
        )

        # Options for select-type fields (collected during pre-scan)
        options: list[FieldOption] | None = None
        if data_type in _OPTION_FIELD_TYPES:
            collected = select_options.get(col_name)
            options = collected if collected else None

        # Option provenance for the report (FEAT-325) — only meaningful for
        # option-typed fields; None otherwise.
        field_options_source: str | None = None
        if data_type in _OPTION_FIELD_TYPES:
            field_options_source = options_provenance.get(col_name)

        # --- ImportDiffReport entry ---
        if report_entries is not None:
            is_formula = data_type in ("FIELD_FORMULA", "FIELD_TOTAL")
            is_approximate = bool(extra_kwargs.get("meta", {}).get("render_as"))

            if is_formula:
                # Formula expressions are never available from networkninja
                report_entries.append(ImportDiffEntry(
                    column_name=col_name,
                    source_data_type=data_type,
                    mapped_field_type=field_type.value,
                    status="requiere_intervencion",
                    note=(
                        "formula expression unavailable at networkninja source "
                        "(options=[]); meta.expression=None; evaluator is FEAT-301"
                    ),
                    options_source=field_options_source,
                ))
            elif unmapped_validations:
                # A validation the model cannot express is a real loss of
                # fidelity — reporting it as "mapeado" tells a reviewer the
                # field came across whole when it did not. Outranks the
                # "aproximado" render_as hint below: a missing bound changes
                # what the form accepts, a render hint does not.
                report_entries.append(ImportDiffEntry(
                    column_name=col_name,
                    source_data_type=data_type,
                    mapped_field_type=field_type.value,
                    status="requiere_intervencion",
                    note=(
                        "validation(s) not representable as FieldConstraints: "
                        + ", ".join(unmapped_validations)
                    ),
                    options_source=field_options_source,
                ))
            elif is_approximate:
                report_entries.append(ImportDiffEntry(
                    column_name=col_name,
                    source_data_type=data_type,
                    mapped_field_type=field_type.value,
                    status="aproximado",
                    note=(
                        f"mapped to {field_type.value} with render_as hint "
                        f"{extra_kwargs['meta'].get('render_as')!r}"
                    ),
                    options_source=field_options_source,
                ))
            else:
                report_entries.append(ImportDiffEntry(
                    column_name=col_name,
                    source_data_type=data_type,
                    mapped_field_type=field_type.value,
                    status="mapeado",
                    note="",
                    options_source=field_options_source,
                ))

        return FormField(
            field_id=field_id,
            field_type=field_type,
            label=label,
            required=required,
            depends_on=depends_on,
            options=options,
            constraints=constraints,
            **extra_kwargs,
        )

    # ------------------------------------------------------------------
    # Validations
    # ------------------------------------------------------------------

    @staticmethod
    def _map_validations(
        validations: list[dict[str, Any]],
        field_type: FieldType,
    ) -> tuple[FieldConstraints | None, list[str]]:
        """Translate a question's validations into ``FieldConstraints``.

        ``responseRequired`` is handled by the caller (it maps to the field's
        own ``required`` flag, not to a constraint). Numeric bounds map here:

        - ``lteValue`` → ``max_value`` directly (inclusive at both ends).
        - ``ltValue`` on an INTEGER field → ``max_value = value - 1``, which
          is the exact inclusive equivalent over the integers.
        - ``ltValue`` on any other numeric field is an EXCLUSIVE bound, and
          ``FieldConstraints`` has no exclusive maximum. Rather than silently
          widen the range by treating it as inclusive, it is reported back to
          the caller as unmapped.

        When several bounds apply to one field the tightest one wins.

        Args:
            validations: Raw ``validations`` list from the question.
            field_type: The already-resolved target field type.

        Returns:
            ``(constraints, unmapped)`` — ``constraints`` is ``None`` when no
            bound could be derived; ``unmapped`` names the validation types
            that were understood but could not be represented.
        """
        max_value: float | None = None
        unmapped: list[str] = []

        for validation in validations:
            vtype = validation.get("validation_type")
            if vtype == "responseRequired":
                continue

            raw_value = validation.get("validation_comparison_value")
            if vtype not in ("ltValue", "lteValue") or raw_value is None:
                unmapped.append(str(vtype))
                continue

            try:
                bound = float(raw_value)
            except (TypeError, ValueError):
                unmapped.append(f"{vtype}({raw_value!r})")
                continue

            if vtype == "ltValue":
                if field_type is not FieldType.INTEGER:
                    unmapped.append(f"{vtype} (exclusive bound on {field_type.value})")
                    continue
                # Largest integer strictly below `bound`. Plain `bound - 1`
                # is only right when the threshold is whole: "< 10.5" would
                # store 9.5 and wrongly reject 10. ceil() handles fractional
                # and negative thresholds alike ("< -3.5" → -4).
                bound = math.ceil(bound) - 1

            max_value = bound if max_value is None else min(max_value, bound)

        if max_value is None:
            return None, unmapped
        return FieldConstraints(max_value=max_value), unmapped

    # ------------------------------------------------------------------
    # Conditional logic
    # ------------------------------------------------------------------

    def _map_logic_groups(
        self,
        question: dict[str, Any],
        question_id_index: dict[str, str],
        option_id_catalog: dict[str, dict[str, str]] | None = None,
    ) -> DependencyRule | None:
        """Translate logic_groups on a question into a DependencyRule.

        Rules:
        - Multiple conditions in one logic_group → ``logic="or"``
        - Multiple logic_groups on one question → ``logic="and"``
        - All rules use ``effect="show"``
        - Only ``condition_logic="EQUALS"`` is supported; others are skipped.
        - FEAT-325: when the referenced column has a metadata option_id
          catalog, ``condition_comparison_value`` (human text) is re-indexed
          to the matching ``option_id`` so ``FieldCondition.value`` shares the
          value-space of the metadata-backed ``FieldOption.value``. Columns
          with no catalog keep the original text comparison; an unmatched
          comparison value is preserved as-is (logged at debug, never
          dropped).
        - FEAT-440 (spec §3 Module 4): a ``store_groups`` list of store-group
          names on ``question`` (or the block-level shim passed from
          ``_map_block_to_section``) is translated via
          :meth:`_map_store_group_rule` instead of the flat conditions/logic
          pair — see that method for the group-nesting shape.

        Args:
            question: Question dict potentially containing logic_groups
                and/or store_groups.
            question_id_index: question_id → column_name reverse index.
            option_id_catalog: column_name → {option_value: option_id} from
                ``_build_option_id_catalog``. ``None``/empty behaves like no
                catalog (text comparison preserved).

        Returns:
            DependencyRule if any valid conditions and/or store groups are
            present, else None.
        """
        logic_groups: list[dict[str, Any]] = (
            question.get("logic_groups")
            or question.get("question_logic_groups")
            or []
        )
        store_groups: list[str] = question.get("store_groups") or []
        if not logic_groups and not store_groups:
            return None

        all_conditions: list[FieldCondition] = []

        for group in logic_groups:
            group_conditions: list[FieldCondition] = []

            for cond in group.get("conditions") or []:
                if cond.get("condition_logic") != "EQUALS":
                    self.logger.debug(
                        "Skipping unsupported condition_logic '%s'",
                        cond.get("condition_logic"),
                    )
                    continue

                ref_qid = str(cond.get("condition_question_reference_id", ""))
                ref_col = question_id_index.get(ref_qid)
                if not ref_col:
                    self.logger.debug(
                        "Skipping condition: question_id '%s' not resolved", ref_qid
                    )
                    continue

                ref_field_id = f"field_{ref_col}"
                comparison_value = cond.get("condition_comparison_value")

                # FEAT-325: re-index text comparison_value → option_id when
                # the referenced column has a metadata option_id catalog.
                col_catalog = (option_id_catalog or {}).get(ref_col)
                if col_catalog is not None and comparison_value is not None:
                    reindexed = col_catalog.get(str(comparison_value))
                    if reindexed is not None:
                        comparison_value = reindexed
                    else:
                        self.logger.debug(
                            "comparison_value '%s' not found in option_id "
                            "catalog for column '%s' — keeping original value",
                            comparison_value, ref_col,
                        )

                group_conditions.append(
                    FieldCondition(
                        field_id=ref_field_id,
                        operator=ConditionOperator.EQ,
                        value=comparison_value,
                    )
                )

            all_conditions.extend(group_conditions)

        # Store groups on an element are alternatives (any ONE of them shows
        # it), which `groups`/`LogicGroup` expresses and a flat conditions/
        # logic pair cannot — see `_map_store_group_rule`. Any answer
        # condition already collected above (e.g. a visit-type EQUALS) joins
        # EVERY store-group alternative, since it must hold regardless of
        # which group matched.
        if store_groups:
            return self._map_store_group_rule(store_groups, all_conditions)

        if not all_conditions:
            return None

        # Multiple groups mean AND — EXCEPT when every group tests the same
        # field, which makes them alternatives on one answer rather than
        # independent prerequisites.
        #
        # The exception is not a preference, it is satisfiability. A rule
        # like "visit type == Brand Ambassador AND visit type == Assisted
        # Sales" can never hold: `_eval_logic` resolves "and" to
        # all(results), and one select carries one answer, so the element
        # stays hidden forever. Every multi-group rule on db-form-10-69 (12
        # blocks, 13 questions) has exactly that shape.
        #
        # Sweeping all 91 source forms: 34 multi-group rules test a single
        # field (alternatives) and 3 span several fields (genuine
        # prerequisites, e.g. formid 102 orgid 74 gating on four different
        # questions). Deciding per rule keeps both readings correct.
        #
        # Known approximation, pre-existing: groups are flattened into one
        # flat condition list, so a rule that is multi-group AND multi-
        # condition-per-group loses the intra-group OR. No source form has
        # that shape today.
        referenced_fields = {c.field_id for c in all_conditions}
        if len(logic_groups) > 1 and len(referenced_fields) > 1:
            top_logic = cast(Literal["and", "or"], "and")
        else:
            top_logic = cast(
                Literal["and", "or"], "or" if len(all_conditions) > 1 else "and"
            )

        return DependencyRule(
            conditions=all_conditions,
            logic=top_logic,
            effect="show",
        )

    @staticmethod
    def _map_store_group_rule(
        store_groups: list[str],
        shared_conditions: list[FieldCondition],
    ) -> DependencyRule:
        """Translate a per-element list of store-group names into a rule.

        Spec §3 Module 4. Store groups on one element are alternatives — any
        SINGLE one showing it — so each becomes its OWN :class:`LogicGroup`,
        holding a ``visit_context`` ``CONTAINS`` condition for that one group
        name. An existing answer condition already gating this element (e.g.
        a visit-type ``EQUALS``) is not itself an alternative: it must hold
        no matter which store-group alternative matched, so it is copied
        into EVERY group alongside the group's own condition.

        Nothing populates ``visit_context`` yet (spec §7 Risks) — a rule
        built here fails closed against a live form with no context, which
        is stricter than no rule at all, by design (see the Hazard note in
        TASK-2315). This method itself is source-agnostic: it is exercised
        directly by fixtures, and reached in production only once a source
        row supplies a ``store_groups`` list (see ``_block_store_groups`` /
        the ``question.get("store_groups")`` read in ``_map_logic_groups``).

        Args:
            store_groups: Store-group names gating this element. Must be
                non-empty (callers only invoke this when it is).
            shared_conditions: Conditions already required by this element
                (e.g. from an existing answer-based logic_groups), each
                AND'd into every store-group alternative. May be empty when
                the element is gated on store group alone.

        Returns:
            A ``DependencyRule`` expressed via ``groups`` (never the flat
            ``conditions``/``logic`` pair — see
            :class:`~parrot_formdesigner.core.constraints.LogicGroup`).
        """
        groups = [
            LogicGroup(
                conditions=[
                    FieldCondition(
                        source="visit_context",
                        key="store_groups",
                        operator=ConditionOperator.CONTAINS,
                        value=group_name,
                    ),
                    # Fresh copies per group — resolution (FEAT-393) writes
                    # field_uid onto each condition in place, and every group
                    # must carry its own instance rather than aliasing the
                    # same object across alternatives.
                    *(c.model_copy() for c in shared_conditions),
                ]
            )
            for group_name in store_groups
        ]
        return DependencyRule(conditions=[], groups=groups, effect="show")
