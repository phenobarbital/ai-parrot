"""QuerySource conditions dialect: static reference, validators and payload builder (spec §3 M3).

Verified against querysource 4.5.11 (GitHub tag 4.5.11 == dev): parsers/abstract.pyx:156-290,380-410,474-527
and parsers/sql.pyx:25,96,113-235. The wheel ships compiled parsers, so this module is the source of truth
for the LLM — never introspect the parser at runtime.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.models import DialectReference, FilterValue

logger = logging.getLogger(__name__)

DIALECT_VERIFIED_AGAINST: str = "4.5.11"
OPTION_KEYS: frozenset[str] = frozenset(
    {
        "fields",
        "querylimit",
        "_limit",
        "_offset",
        "paged",
        "page",
        "group_by",
        "grouping",
        "order_by",
        "ordering",
        "filter",
        "where_cond",
        "filter_options",
        "qry_options",
        "refresh",
        "hierarchy",
        "distinct",
        "add_fields",
        "tablename",
        "schema",
        "database",
        "slug",
        "conditions",
    }
)
LIST_OPERATORS: tuple[str, ...] = ("<", ">", ">=", "<=", "<>", "!=", "IS NOT", "IS")  # sql.pyx:96
DICT_OPERATORS: tuple[str, ...] = (">=", "<=", "<>", "!=", "<", ">")  # sql.pyx:25
KEY_SUFFIX_CHARS: str = "|!~#@:"  # sql.pyx:132
_BETWEEN_FORBIDDEN: tuple[str, ...] = (";", "--", "/*", "UNION", "SELECT")  # sql.pyx:184-189

DIALECT_REFERENCE = DialectReference(
    verified_against=DIALECT_VERIFIED_AGAINST,
    option_keys={
        "fields": "list[str] — columns to project (overrides the slug's stored fields)",
        "querylimit": "int — row limit (the toolkit sets this from `limit`, capped at max_rows); alias `_limit`",
        "_offset": "int — row offset; `paged`/`page` enable page-based pagination",
        "ordering": "list[str] — ORDER BY columns, e.g. ['-created_at'] not supported: use 'col DESC'; alias `order_by`",
        "grouping": "list[str] — GROUP BY columns; alias `group_by`",
        "filter": "dict — WHERE clauses (see where_grammar); alias `where_cond`",
        "refresh": "bool — bypass the QuerySource cache for this call",
        "filter_options": "dict — extra WHERE entries merged into filter",
        "qry_options": "dict — provider-specific options",
        "hierarchy": "list — hierarchical filtering rules",
        "distinct": "bool — SELECT DISTINCT",
        "conditions": "dict — nested placeholder values; merged over the flat ones",
        "add_fields": "list[str] — additional columns appended to the projection alongside `fields`, not replacing it",
        "tablename": "str — override the source/destination table name (provider-specific; rarely set by agents)",
        "schema": "str — override the database schema (provider-specific; rarely set by agents)",
        "database": "str — override the target database name (provider-specific; rarely set by agents)",
        "slug": "str — the query-slug identifier itself; pass it as the tool's own `slug` argument, never nested here",
    },
    placeholder_rules=[
        "A slug's stored `conditions` are DEFAULT values for the placeholders in its SQL (e.g. {firstdate}); "
        "`cond_definition` declares their types.",
        "Merge order: stored defaults < your flat keys < your nested `conditions`. Your values win.",
        "Any key that is NOT an option key and NOT a declared placeholder becomes a WHERE filter — so put ad-hoc "
        "column filters in `filter`, and only declared names in `placeholders`.",
        "Values starting with '@' call a deployment variable function (see `variables`), e.g. '@today'.",
    ],
    where_grammar=[
        "col: 'v'            → col = 'v'",
        "col: '!v'  or  'col!': 'v'   → col != 'v'",
        "col: ['a', 'b']    → col IN ('a','b');   'col!': [...] → NOT IN",
        "col: ['>=', 10]    → col >= 10   (first item must be one of operators_list_form)",
        "col: {'>': 10}     → col > 10    (single key from operators_dict_form)",
        "col: 'BETWEEN 1 AND 5' → (col BETWEEN 1 AND 5)  — no ';', '--', '/*', UNION, SELECT",
        "col: 'null' / '!null' → IS NULL / IS NOT NULL",
        "col: true → col = True",
        "Keys must be identifier-safe ([A-Za-z0-9_.] after stripping suffix chars |!~#@:); "
        "the parser silently DROPS unsafe keys/operators — this toolkit rejects them up front instead.",
    ],
    operators_list_form=list(LIST_OPERATORS),
    operators_dict_form=list(DICT_OPERATORS),
    examples=[
        {"slug": "epson_field_activity", "placeholders": {"firstdate": "2026-08-09", "lastdate": "2026-08-15"}},
        {
            "slug": "epson_field_activity",
            "placeholders": {"firstdate": "@yesterday", "lastdate": "@today"},
            "filter": {"store_id": ["101", "102"]},
            "fields": ["store_id", "visits"],
            "limit": 50,
        },
        {
            "slug": "pokemon_all_fso_odoo_new",
            "filter": {"warehouse_alias!": "DC01", "qty": {">": 0}},
            "ordering": ["qty DESC"],
            "grouping": ["warehouse_alias"],
        },
    ],
    notes=[
        "Unsafe keys/operators are dropped silently by the SQL parser; validate first.",
        "querylimit is always applied by the toolkit; results are bounded by max_rows.",
    ],
)


def _key_is_safe(key: str) -> bool:
    """Mirror sql.pyx:130-138: strip suffix chars, then only alnum, '_' or '.' allowed."""
    stripped = key.rstrip(KEY_SUFFIX_CHARS)
    return bool(stripped) and all(c.isalnum() or c in "_." for c in stripped)


def validate_placeholders(placeholders: dict[str, Any], allowed: set[str]) -> None:
    """Raise InvalidConditionsError for keys not in `allowed` or present in OPTION_KEYS."""
    unknown = sorted(k for k in placeholders if k not in allowed or k in OPTION_KEYS)
    if unknown:
        raise InvalidConditionsError(
            f"Unknown placeholders {unknown}; this slug declares {sorted(allowed)}. "
            "Use `filter` for ad-hoc column conditions and the typed arguments for options."
        )


def validate_filter(filter: dict[str, FilterValue], *, strict: bool = True) -> list[str]:
    """Validate WHERE entries against the grammar; return rejected keys (raise when strict)."""
    rejected: list[str] = []
    for key, value in filter.items():
        reason = None
        if not _key_is_safe(key):
            reason = "unsafe key"
        elif isinstance(value, dict):
            # {op: v} form — bounded by sql.pyx:151-159: exactly one key, in DICT_OPERATORS.
            if len(value) != 1:
                reason = "dict filter must have exactly one operator key"
            else:
                (op,) = value.keys()
                if op not in DICT_OPERATORS:
                    reason = f"unknown dict operator {op!r}"
        elif isinstance(value, list):
            # [op, v] comparison form vs plain IN list — bounded by sql.pyx:160-181.
            if len(value) == 2 and isinstance(value[0], str) and value[0] in LIST_OPERATORS:
                pass  # comparison form: [operator, value]
            elif any(isinstance(item, (dict, list)) for item in value):
                reason = "IN list values must be scalars"
        elif isinstance(value, str) and "BETWEEN" in value.upper():
            if any(tok in value.upper() for tok in _BETWEEN_FORBIDDEN):
                reason = "unsafe BETWEEN expression"
        if reason:
            rejected.append(f"{key}: {reason}")
    if rejected and strict:
        raise InvalidConditionsError(f"Invalid filter entries: {rejected}. See qs_get_dialect_reference().")
    return rejected


def build_conditions(
    *,
    placeholders: dict[str, Any] | None,
    filter: dict[str, FilterValue] | None,
    fields: list[str] | None,
    ordering: list[str] | None,
    grouping: list[str] | None,
    limit: int | None,
    offset: int | None,
    refresh: bool,
    max_rows: int,
    forced: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the QS `conditions` payload deterministically; `forced` wins (query_slug.py:143 precedence)."""
    payload: dict[str, Any] = dict(placeholders or {})
    if filter:
        payload["filter"] = dict(filter)
    for key, val in (("fields", fields), ("ordering", ordering), ("grouping", grouping)):
        if val:
            payload[key] = list(val)
    payload["querylimit"] = min(limit or max_rows, max_rows)
    if offset:
        payload["_offset"] = int(offset)
    if refresh:
        payload["refresh"] = True
    if forced:
        payload = {**payload, **forced}
    return payload


def check_version_compatibility(installed: str) -> str | None:
    """Return a warning when installed major.minor differs from DIALECT_VERIFIED_AGAINST (S11)."""
    want = DIALECT_VERIFIED_AGAINST.split(".")[:2]
    have = str(installed).split(".")[:2]
    if have != want:
        return (
            f"querysource {installed} differs from the dialect reference version {DIALECT_VERIFIED_AGAINST}; "
            "the conditions reference may be inaccurate."
        )
    return None


def load_variables() -> dict[str, str]:
    """Return {'@name': doc} for the deployment's variable functions (services.py:29-33,94-96); never raises."""
    names: dict[str, Any] = {}
    try:
        settings = importlib.import_module("settings.settings")
        names = dict(getattr(settings, "QUERYSOURCE_VARIABLES", {}) or {})
    except Exception:  # noqa: BLE001 — optional deploying-app module
        try:
            names = dict(importlib.import_module("querysource.parsers").QS_VARIABLES)
        except Exception:  # noqa: BLE001
            return {}
    out: dict[str, str] = {}
    for name, target in names.items():
        # Resolve dotted-path strings via importlib (module:attr or module.attr), as services.load_library does;
        # callables are used as-is; doc = first docstring line or '' — never raise, log at debug and skip.
        try:
            if callable(target):
                fn = target
            else:
                path = str(target)
                if ":" in path:
                    module_path, _, attr = path.partition(":")
                else:
                    module_path, _, attr = path.rpartition(".")
                if not module_path or not attr:
                    raise ValueError(f"cannot resolve variable target {path!r}")
                module = importlib.import_module(module_path)
                fn = getattr(module, attr)
            doc_lines = (fn.__doc__ or "").strip().splitlines()
            out[f"@{name}"] = doc_lines[0].strip() if doc_lines else ""
        except Exception:  # noqa: BLE001 — a broken deployment variable must not break the dialect reference
            logger.debug("Skipping unresolved QuerySource variable %s -> %r", name, target, exc_info=True)
            out[f"@{name}"] = ""
    return out
