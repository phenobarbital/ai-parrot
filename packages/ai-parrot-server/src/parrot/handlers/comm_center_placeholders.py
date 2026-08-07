"""Static placeholder catalog for the CommCenter bulk notification sender.

Served by ``GET /api/v1/comm_center/placeholders`` (wired in
``handlers/comm_center.py``, TASK-2159). A template author has no other way
to discover which record fields and computed functions a template body may
reference, so this module documents all three groups plus the two safety
disclosures that are not cosmetic (spec §3 Module 3, §7 Known Risks):

- The bare-placeholder limitation of ``DebugUndefined`` (no filters or
  conditionals over record fields survive pass 1).
- The reserved names (``recipient``/``message``/``subject``) that are bound
  by Notify itself and render an object repr rather than a value.

Pure/stdlib module plus :func:`resolve_date` — no aiohttp/DB imports, so it
can be imported and unit tested without any web or database side effects.
"""
from datetime import UTC, datetime
from typing import Any

from parrot.outputs.a2ui.recipes.params import DATE_RESOLVERS, resolve_date

#: Group 1 — recipient fields resolved worker-side (pass 2), sourced from
#: the ingested row. Spec §3 Module 3.
_RECIPIENT_FIELDS: list[dict[str, Any]] = [
    {
        "name": "name",
        "required": True,
        "description": "The only mandatory column.",
        "example": "Ana Gomez",
    },
    {
        "name": "username",
        "required": False,
        "description": (
            "Always emitted by the service; falls back to the row's `name` "
            "when the column is absent, so `{{username}}` can never render "
            "an internal object representation."
        ),
        "example": "agomez",
    },
    {
        "name": "email",
        "required": "conditional",
        "description": "Required when the resolved provider is email-like.",
        "example": "ana@example.com",
    },
    {
        "name": "phone",
        "required": "conditional",
        "description": "Required when the resolved provider is SMS-like.",
        "example": "+34600000000",
    },
    {
        "name": "address",
        "required": False,
        "description": "Free-form postal/other address.",
        "example": "123 Main St",
    },
]

#: Group 3 — reserved names bound by Notify's own render context; must never
#: be used as template placeholders. Spec §2 pass-2 binding precedence.
_RESERVED: list[dict[str, str]] = [
    {
        "name": "recipient",
        "description": (
            "Bound by NotifyWorker to the internal recipient object. "
            "`{{recipient}}` renders an object repr, never a name."
        ),
    },
    {
        "name": "message",
        "description": "Bound by NotifyWorker's render context. Do not use.",
    },
    {
        "name": "subject",
        "description": "Bound by NotifyWorker's render context. Do not use.",
    },
]

_LIMITATION = (
    "Record placeholders must be written as bare `{{ field }}`. Filters and "
    "conditionals over an unresolved value (e.g. `{{ name|upper }}`, "
    "`{% if email %}`) are not supported in the batch-level partial render "
    "pass, because it uses Jinja2's DebugUndefined to preserve unresolved "
    "fields literally for the worker's second pass."
)

_EXTRA_COLUMNS = (
    "Any recipient column beyond the canonical five above (name, username, "
    "email, phone, address) is forwarded verbatim as an additional "
    "pass-2 placeholder."
)


def _build_computed_functions(now: datetime | None = None) -> list[dict[str, Any]]:
    """Build Group 2 — computed functions resolved handler-side (pass 1).

    Delegates every date-based entry to :func:`resolve_date` — date math is
    never reimplemented here. ``now`` and ``current_year`` are module-local
    extras layered on top of the five verbatim ``DATE_RESOLVERS``.

    Args:
        now: Injectable current time for deterministic sample values.

    Returns:
        One dict per computed function: ``name``, ``description``,
        ``example``, and a live ``sample`` value.
    """
    moment = now if now is not None else datetime.now(UTC)
    functions: list[dict[str, Any]] = []
    for resolver in DATE_RESOLVERS:
        functions.append(
            {
                "name": resolver,
                "description": f"Resolves to the {resolver.replace('_', ' ')} date.",
                "example": "{{ " + resolver + " }}",
                "sample": resolve_date(resolver, now=moment),
            }
        )
    functions.append(
        {
            "name": "now",
            "description": "The current timestamp, ISO-8601 formatted.",
            "example": "{{ now }}",
            "sample": moment.isoformat(),
        }
    )
    functions.append(
        {
            "name": "current_year",
            "description": "The current calendar year.",
            "example": "{{ current_year }}",
            "sample": str(moment.year),
        }
    )
    return functions


def build_catalog(now: datetime | None = None) -> dict[str, Any]:
    """Build the full, serializable placeholder catalog payload.

    Args:
        now: Injectable current time threaded into every computed-function
            sample, so callers (and tests) get deterministic output.

    Returns:
        A dict with keys ``recipient_fields``, ``computed_functions``,
        ``reserved``, ``limitation``, and ``extra_columns``.
    """
    return {
        "recipient_fields": _RECIPIENT_FIELDS,
        "computed_functions": _build_computed_functions(now=now),
        "reserved": _RESERVED,
        "limitation": _LIMITATION,
        "extra_columns": _EXTRA_COLUMNS,
    }
