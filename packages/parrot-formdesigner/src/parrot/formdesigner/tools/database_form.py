"""DatabaseFormTool — Load a form definition from PostgreSQL into a FormSchema.

Queries the ``networkninja.forms`` + ``networkninja.form_metadata`` tables by
``formid`` and ``orgid``, deterministically maps the result to a ``FormSchema``,
and optionally persists it in the ``FormRegistry``.

Transformation pipeline:
1. Query — fetch form + metadata in one parameterized SQL call via asyncdb
2. Index — build metadata lookup by column_name and question_id → column_name reverse index
3. Pre-scan — collect multi-select option values from conditional references
4. Map sections — each question_block → FormSection
5. Map fields — each question → FormField (skip if unsupported or not in metadata)
6. Map logic — logic_groups → DependencyRule with ConditionOperator.EQ
7. Map validations — responseRequired → required=True
8. Register — store FormSchema in FormRegistry
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

try:
    from parrot.tools.abstract import AbstractTool, ToolResult
except ImportError:
    AbstractTool = object
    ToolResult = dict
# from ..forms legacy:  AbstractTool, ToolResult
from ..core.constraints import ConditionOperator, DependencyRule, FieldCondition
from ..core.options import FieldOption
from ..services.registry import FormRegistry
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType

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
            'description', m.description, 'data_type', m.data_type
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
    # Explicitly unsupported — skip with warning
    "FIELD_SIGNATURE_CAPTURE": None,
}

# Field types that carry selectable options
_OPTION_FIELD_TYPES: set[str] = {
    "FIELD_SELECT",
    "FIELD_SELECT_RADIO",
    "FIELD_MULTISELECT",
}


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class DatabaseFormInput(BaseModel):
    """Input schema for DatabaseFormTool.

    Attributes:
        formid: Numeric form identifier in the database.
        orgid: Organization ID that owns the form.
        persist: Whether to save the resulting FormSchema to the registry storage.
    """

    formid: int = Field(..., ge=1, description="Numeric form identifier in the database")
    orgid: int = Field(..., ge=1, description="Organization ID that owns the form")
    persist: bool = Field(
        default=False,
        description="Save the generated FormSchema to the registry storage",
    )


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class DatabaseFormTool(AbstractTool):
    """Load a form definition from PostgreSQL into a FormSchema.

    Queries ``networkninja.forms`` + ``networkninja.form_metadata`` by
    ``formid`` and ``orgid``, translates field types, conditional logic, and
    validation rules into a ``FormSchema``, registers it in the
    ``FormRegistry``, and returns it in ``ToolResult.metadata["form"]``.

    Example:
        tool = DatabaseFormTool(registry=registry)
        result = await tool.execute(formid=42, orgid=7)
        form_schema = FormSchema(**result.metadata["form"])
    """

    name: str = "database_form"
    description: str = (
        "Load a form definition from PostgreSQL into a FormSchema. "
        "Requires formid and orgid to identify the form."
    )
    args_schema = DatabaseFormInput

    def __init__(
        self,
        registry: FormRegistry,
        dsn: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize DatabaseFormTool.

        Args:
            registry: FormRegistry where the generated FormSchema will be registered.
            dsn: PostgreSQL DSN (asyncdb format: ``postgres://user:pwd@host/db``).
                Defaults to ``parrot.conf.default_dsn``.
            **kwargs: Additional keyword arguments forwarded to AbstractTool.
        """
        super().__init__(**kwargs)
        self._registry = registry
        self._dsn = dsn
        self.logger = logging.getLogger(__name__)

    def _get_dsn(self) -> str:
        """Return the configured DSN or the package default.

        Returns:
            DSN string suitable for asyncdb's ``pg`` driver.
        """
        if self._dsn:
            return self._dsn
        # Lazy import avoids import-time side-effects
        from ...conf import default_dsn  # noqa: PLC0415
        return default_dsn

    # ------------------------------------------------------------------
    # AbstractTool interface
    # ------------------------------------------------------------------

    async def _execute(  # type: ignore[override]
        self,
        formid: int,
        orgid: int,
        persist: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute the database form load pipeline.

        Args:
            formid: Numeric form identifier.
            orgid: Organization ID.
            persist: If True, persist the form via the registry storage backend.
            **kwargs: Ignored extra arguments.

        Returns:
            ToolResult with ``success=True`` and the FormSchema in
            ``metadata["form"]``, or ``success=False`` with error details.
        """
        try:
            row = await self._fetch_form_row(formid, orgid)
            if row is None:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    metadata={
                        "error": f"Form not found: formid={formid}, orgid={orgid}"
                    },
                )

            form = self._build_form_schema(row)

            await self._registry.register(form, persist=persist)

            self.logger.info(
                "Loaded form %s (formid=%s, orgid=%s) — %d sections",
                form.form_id,
                formid,
                orgid,
                len(form.sections),
            )

            return ToolResult(
                success=True,
                status="success",
                result={"form_id": form.form_id, "title": str(form.title)},
                metadata={"form": form.model_dump()},
            )

        except json.JSONDecodeError as exc:
            self.logger.error(
                "Malformed JSON in question_blocks for formid=%s: %s", formid, exc
            )
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={
                    "error": (
                        f"Malformed question_blocks JSON for formid={formid}: {exc}"
                    )
                },
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "DatabaseFormTool error for formid=%s: %s",
                formid,
                exc,
                exc_info=True,
            )
            return ToolResult(
                success=False,
                status="error",
                result=None,
                metadata={"error": str(exc)},
            )

    # ------------------------------------------------------------------
    # DB layer
    # ------------------------------------------------------------------

    async def _fetch_form_row(
        self, formid: int, orgid: int
    ) -> dict[str, Any] | None:
        """Execute the parameterized SQL query and return the single result row.

        Args:
            formid: Form identifier.
            orgid: Organization identifier.

        Returns:
            Row dict if found, None if no rows returned.

        Raises:
            RuntimeError: On connection failure or query errors.
        """
        from asyncdb import AsyncDB  # noqa: PLC0415

        dsn = self._get_dsn()
        db = AsyncDB("pg", dsn=dsn)

        async with await db.connection() as conn:
            result, errors = await conn.queryrow(_FORM_QUERY, formid, orgid)

        if errors:
            raise RuntimeError(f"DB query failed for formid={formid}: {errors}")

        return result  # None when no matching row

    # ------------------------------------------------------------------
    # Form building pipeline
    # ------------------------------------------------------------------

    def _build_form_schema(self, row: dict[str, Any]) -> FormSchema:
        """Transform a DB result row into a FormSchema.

        Args:
            row: Dict with keys: formid, form_name, description, orgid,
                 question_blocks (JSON string or list), metadata (list of dicts).

        Returns:
            Fully constructed FormSchema.
        """
        form_name: str = row.get("form_name") or f"form_{row['formid']}"
        form_id = f"db-form-{row['formid']}-{row['orgid']}"
        description: str | None = row.get("description") or None

        # Build metadata index: column_name → {column_id, data_type, description}
        raw_metadata: list[dict[str, Any]] = row.get("metadata") or []
        meta_index = self._build_metadata_index(raw_metadata)

        # Parse question_blocks — stored as JSON text (not JSONB), must json.loads()
        question_blocks_raw = row.get("question_blocks") or "[]"
        if isinstance(question_blocks_raw, str):
            question_blocks: list[dict[str, Any]] = json.loads(question_blocks_raw)
        else:
            question_blocks = list(question_blocks_raw)

        # Build question_id → column_name reverse index (for conditional resolution)
        question_id_index = self._build_question_id_index(question_blocks, meta_index)

        # Pre-scan questions to collect options for select-type fields
        select_options = self._collect_select_options(
            question_blocks, question_id_index, meta_index
        )

        # Build sections — each question_block → one FormSection
        sections: list[FormSection] = []
        for block in question_blocks:
            section = self._map_block_to_section(
                block, meta_index, question_id_index, select_options
            )
            if section is not None:
                sections.append(section)

        return FormSchema(
            form_id=form_id,
            title=form_name,
            description=description,
            sections=sections,
        )

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
                }
        return index

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
    ) -> dict[str, list[FieldOption]]:
        """Pre-scan questions to collect option values for select-type fields.

        Options are gathered from two sources:
        1. Inline ``options`` arrays in the question JSON (preferred).
        2. ``logic_groups`` conditions that reference a select-type column
           via ``condition_question_reference_id``.

        Args:
            question_blocks: All parsed question blocks.
            question_id_index: question_id → column_name reverse index.
            meta_index: Active metadata index for type lookups.

        Returns:
            Dict mapping column_name → deduplicated list of FieldOption.
        """
        collector: dict[str, dict[str, str]] = {}  # col_name → {value: label}

        def _scan_conditions(conditions: list[dict[str, Any]]) -> None:
            """Extract option values from a list of conditions."""
            for cond in conditions:
                ref_qid = str(
                    cond.get("condition_question_reference_id", "")
                )
                ref_col = question_id_index.get(ref_qid)
                if not ref_col:
                    continue

                ref_meta = meta_index.get(ref_col, {})
                if ref_meta.get("data_type") not in _OPTION_FIELD_TYPES:
                    continue

                comp_value = cond.get("condition_comparison_value")
                if comp_value is not None:
                    if ref_col not in collector:
                        collector[ref_col] = {}
                    # comparison_value is the human-readable label
                    collector[ref_col][str(comp_value)] = str(comp_value)

        for block in question_blocks:
            # Scan block-level logic groups (question_block_logic_groups)
            block_logic = (
                block.get("question_block_logic_groups")
                or block.get("block_logic_groups")
                or []
            )
            for group in block_logic:
                _scan_conditions(group.get("conditions") or [])

            for question in block.get("questions") or []:
                # Source 1: inline options on the question itself
                col_name = str(question.get("question_column_name", ""))
                if col_name in meta_index:
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
                                if col_name not in collector:
                                    collector[col_name] = {}
                                collector[col_name][str(value)] = (
                                    str(label) if label else str(value)
                                )

                # Source 2: options inferred from conditional references
                logic_groups = (
                    question.get("logic_groups")
                    or question.get("question_logic_groups")
                    or []
                )
                for group in logic_groups:
                    _scan_conditions(group.get("conditions") or [])

        return {
            col: [
                FieldOption(value=value, label=label)
                for value, label in options.items()
            ]
            for col, options in collector.items()
        }

    # ------------------------------------------------------------------
    # Section and field mapping
    # ------------------------------------------------------------------

    def _map_block_to_section(
        self,
        block: dict[str, Any],
        meta_index: dict[str, dict[str, Any]],
        question_id_index: dict[str, str],
        select_options: dict[str, list[FieldOption]],
    ) -> FormSection | None:
        """Map a question_block dict to a FormSection.

        Args:
            block: A single question block dict from question_blocks.
            meta_index: Active metadata lookup.
            question_id_index: question_id → column_name reverse index.
            select_options: Pre-collected options keyed by column_name.

        Returns:
            FormSection if the block has at least one mappable field, else None.
        """
        block_id = block.get("question_block_id") or block.get("block_id", "")
        block_title: str | None = (
            block.get("block_description") or block.get("block_name") or None
        )
        section_id = f"section_{block_id}" if block_id else "section_default"

        fields: list[FormField] = []
        for question in block.get("questions") or []:
            field = self._map_question_to_field(
                question, meta_index, question_id_index, select_options
            )
            if field is not None:
                fields.append(field)

        if not fields:
            return None

        return FormSection(
            section_id=section_id,
            title=block_title,
            fields=fields,
        )

    def _map_question_to_field(
        self,
        question: dict[str, Any],
        meta_index: dict[str, dict[str, Any]],
        question_id_index: dict[str, str],
        select_options: dict[str, list[FieldOption]],
    ) -> FormField | None:
        """Map a question dict to a FormField.

        Skips questions whose column is not in active metadata or whose
        data_type is unsupported.

        Args:
            question: Single question dict from a question block.
            meta_index: Active metadata lookup.
            question_id_index: question_id → column_name reverse index.
            select_options: Pre-collected options keyed by column_name.

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
                "Skipping question column '%s': unknown data_type '%s'",
                col_name,
                data_type,
            )
            return None

        mapping = _FIELD_TYPE_MAP[data_type]
        if mapping is None:
            # Explicitly unsupported (e.g., FIELD_SIGNATURE_CAPTURE)
            self.logger.warning(
                "Skipping question column '%s': unsupported data_type '%s'",
                col_name,
                data_type,
            )
            return None

        field_type, extra_kwargs = mapping

        field_id = f"field_{col_name}"
        label: str = question.get("question_description") or col_name

        # Validations → required flag
        validations: list[dict[str, Any]] = question.get("validations") or []
        required = any(
            v.get("validation_type") == "responseRequired" for v in validations
        )

        # Conditional logic → DependencyRule
        depends_on: DependencyRule | None = self._map_logic_groups(
            question, question_id_index
        )

        # Options for select-type fields (collected during pre-scan)
        options: list[FieldOption] | None = None
        if data_type in _OPTION_FIELD_TYPES:
            collected = select_options.get(col_name)
            options = collected if collected else None

        return FormField(
            field_id=field_id,
            field_type=field_type,
            label=label,
            required=required,
            depends_on=depends_on,
            options=options,
            **extra_kwargs,
        )

    # ------------------------------------------------------------------
    # Conditional logic
    # ------------------------------------------------------------------

    def _map_logic_groups(
        self,
        question: dict[str, Any],
        question_id_index: dict[str, str],
    ) -> DependencyRule | None:
        """Translate logic_groups on a question into a DependencyRule.

        Rules:
        - Multiple conditions in one logic_group → ``logic="or"``
        - Multiple logic_groups on one question → ``logic="and"``
        - All rules use ``effect="show"``
        - Only ``condition_logic="EQUALS"`` is supported; others are skipped.

        Args:
            question: Question dict potentially containing logic_groups.
            question_id_index: question_id → column_name reverse index.

        Returns:
            DependencyRule if any valid conditions are present, else None.
        """
        logic_groups: list[dict[str, Any]] = (
            question.get("logic_groups")
            or question.get("question_logic_groups")
            or []
        )
        if not logic_groups:
            return None

        all_conditions: list[FieldCondition] = []
        multi_group = len(logic_groups) > 1

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

                group_conditions.append(
                    FieldCondition(
                        field_id=ref_field_id,
                        operator=ConditionOperator.EQ,
                        value=comparison_value,
                    )
                )

            all_conditions.extend(group_conditions)

        if not all_conditions:
            return None

        # Multiple logic_groups → AND between groups (each group acts as OR internally)
        # Single group with multiple conditions → OR
        if multi_group:
            top_logic = "and"
        else:
            top_logic = "or" if len(all_conditions) > 1 else "and"

        return DependencyRule(
            conditions=all_conditions,
            logic=top_logic,  # type: ignore[arg-type]
            effect="show",
        )
