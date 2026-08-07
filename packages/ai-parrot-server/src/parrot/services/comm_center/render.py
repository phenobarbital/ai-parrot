"""Render + validation core — the CommCenter "partial-render gateway".

This is the heart of the feature (spec §2 Overview, §3 Module 5). Everything
downstream — bulk send, single send, and dry-run — routes through
:func:`prepare`, so it must be pure: no Redis, no DB, no aiohttp. That purity
is what makes ``dry_run`` (TASK-2162) a free short-circuit and what makes
:class:`~parrot.services.comm_center.CommCenterService` usable outside HTTP
(spec G12).

Two-pass render contract (spec §2): pass 1 (this module, once per batch)
resolves computed functions (``{{today}}``) while leaving ``{{name}}``,
``{{email}}``, etc. literal via Jinja2's ``DebugUndefined``; pass 2
(``NotifyWorker`` -> ``AbstractProvider._render_``, once per recipient)
resolves the record placeholders from the row kwargs. Both passes run with
``autoescape=False`` — pass 2 is fixed that way by ``notify.templates``, so
pass 1 must match it or the preserved ``{{ }}`` braces would be HTML-escaped
and corrupted.

Three verified traps live in :func:`build_wire_payload` (spec §6):

1. ``username`` defaults to the Actor **object** in Notify's pass-2 context
   when a row has no ``username`` — always emit it, falling back to ``name``.
2. The wire key is ``recipient`` (**singular**) — ``NotifyWrapper`` pops
   exactly that key; a plural key silently sends to nobody.
3. ``team_id`` is checked before ``channel_id`` — a dict carrying both
   always becomes a ``TeamsChannel``, never a ``Channel``.
"""
from datetime import UTC, datetime

from jinja2 import DebugUndefined, Environment, TemplateSyntaxError
from parrot.outputs.a2ui.recipes.params import DATE_RESOLVERS, resolve_date

from .models import PreparedBatch, PreparedMessage, RecipientIn, SkippedRow

#: Providers whose contact field is an email address (spec §2 shape table).
_EMAIL_PROVIDERS = frozenset(
    {"email", "gmail", "smtp", "ses", "sendgrid", "office365", "outlook"}
)
#: Providers whose contact field is a phone number.
_SMS_PROVIDERS = frozenset({"twilio"})
#: Providers keyed by a Microsoft Teams channel.
_TEAMS_PROVIDERS = frozenset({"teams"})
#: Providers keyed by a Telegram chat.
_TELEGRAM_PROVIDERS = frozenset({"telegram"})
#: Providers keyed by a generic named channel (Slack, Zoom).
_CHANNEL_PROVIDERS = frozenset({"slack", "zoom"})

_KNOWN_PROVIDERS = (
    _EMAIL_PROVIDERS
    | _SMS_PROVIDERS
    | _TEAMS_PROVIDERS
    | _TELEGRAM_PROVIDERS
    | _CHANNEL_PROVIDERS
)

#: Wire-payload keys that are structural to the publish contract (spec §2's
#: wire format + per-provider shape table). ``build_wire_payload`` must
#: never let an ingested extra column silently overwrite one of these --
#: e.g. a spreadsheet column literally named "template" would otherwise
#: replace the real partially-rendered message body per-row with arbitrary
#: cell content, with the batch still reporting every row as `queued`.
#: Deliberately a superset of (and distinct from) the placeholder catalog's
#: three *reserved template placeholders* (spec §3 Module 3 Group 3 —
#: ``recipient``/``message``/``subject``, a closed, spec-approved list
#: guarded separately in ``ingest._RESERVED_NAMES``): this set protects the
#: wire payload's own structural keys, not template-placeholder bindings.
_PROTECTED_PAYLOAD_KEYS = frozenset(
    {
        "provider",
        "recipient",
        "template",
        "subject",
        "name",
        "username",
        "email",
        "phone",
        "address",
    }
)


class RenderError(ValueError):
    """Raised when the template body fails to parse (handler maps to 400).

    Nothing may be published when this is raised — it must surface before
    a single recipient is processed.
    """


def resolve_functions(*, now: datetime | None = None) -> dict:
    """Resolve every computed function for the batch-level (pass 1) render.

    Delegates every date-based entry to :func:`resolve_date` — date math is
    never reimplemented here. ``now`` and ``current_year`` are the two
    module-local extras (spec §3 Module 3).

    Args:
        now: Injectable current time for deterministic output.

    Returns:
        A dict mapping each computed-function name to its resolved string
        value (``{"today": "2026-08-06", "now": "...", ...}``).
    """
    moment = now if now is not None else datetime.now(UTC)
    functions = {resolver: resolve_date(resolver, now=moment) for resolver in DATE_RESOLVERS}
    functions["now"] = moment.isoformat()
    functions["current_year"] = str(moment.year)
    return functions


def partial_render(template_string: str, context: dict) -> str:
    """Render ``template_string`` once, binding only the computed-function context.

    Uses ``Environment(undefined=DebugUndefined, autoescape=False)`` so
    every placeholder not present in ``context`` (i.e. every per-recipient
    field) is re-emitted literally for the worker's second pass.

    Deliberate deviation from the task/spec's literal
    ``enable_async=True`` on this Environment (see this task's Completion
    Note for the full reproduction): with ``enable_async=True``, Jinja2's
    synchronous ``Template.render()`` internally calls ``asyncio.run(...)``,
    which raises ``RuntimeError: asyncio.run() cannot be called from a
    running event loop`` whenever this function is invoked from
    :func:`prepare` — an ``async def`` that is always awaited from within
    an already-running event loop in real usage (the aiohttp handler).
    Verified byte-for-byte identical rendered output with and without
    ``enable_async`` for the exact string from spec §6's executed
    verification; omitting it is required for :func:`prepare` to work at
    all and changes no rendered content.

    Args:
        template_string: The raw Jinja2 template body (stored, inline, or
            from a ``TEMPLATE_DIR`` file's contents).
        context: The computed-function values to bind, typically the
            output of :func:`resolve_functions`.

    Returns:
        The partially-rendered string: computed functions substituted,
        record placeholders preserved as literal ``{{ field }}`` text.

    Raises:
        RenderError: The template body is not valid Jinja2. Nothing may be
            published when this is raised.
    """
    env = Environment(undefined=DebugUndefined, autoescape=False)
    try:
        template = env.from_string(template_string)
    except TemplateSyntaxError as exc:
        raise RenderError(f"Malformed template: {exc}") from exc
    return template.render(**context)


def _contact_ok(recipient: RecipientIn, provider: str) -> tuple:
    """Check whether ``recipient`` carries the contact field ``provider`` needs.

    Args:
        recipient: The normalized recipient row.
        provider: The already-resolved (row override or global default)
            provider name.

    Returns:
        ``(ok, missing_field_description)`` — ``missing_field_description``
        is only meaningful when ``ok`` is ``False``.
    """
    if provider in _EMAIL_PROVIDERS:
        return (bool(recipient.email), "email")
    if provider in _SMS_PROVIDERS:
        return (bool(recipient.phone), "phone")
    if provider in _TEAMS_PROVIDERS:
        has_both = bool(recipient.extra.get("team_id")) and bool(
            recipient.extra.get("channel_id")
        )
        return (has_both, "team_id/channel_id")
    if provider in _TELEGRAM_PROVIDERS:
        return (bool(recipient.extra.get("chat_id")), "chat_id")
    if provider in _CHANNEL_PROVIDERS:
        return (bool(recipient.extra.get("channel_id")), "channel_id")
    return (False, None)


def validate_and_resolve_provider(
    recipients: list, default_provider: str
) -> tuple:
    """Resolve each recipient's effective provider and validate its contact field.

    Args:
        recipients: The normalized recipient rows to validate.
        default_provider: The batch/request-level provider, used when a row
            does not override it.

    Returns:
        A ``(resolved, skipped)`` tuple: ``resolved`` is a list of
        ``(row_number, recipient, provider)`` for rows that passed
        validation; ``skipped`` is a list of :class:`SkippedRow`. Unknown
        providers are always skipped, never silently defaulted (spec G5).
    """
    resolved: list = []
    skipped: list = []
    for row_number, recipient in enumerate(recipients):
        provider = recipient.provider or default_provider
        if provider not in _KNOWN_PROVIDERS:
            skipped.append(
                SkippedRow(
                    row=row_number,
                    reason=f"Unknown provider '{provider}'; row skipped, not defaulted",
                )
            )
            continue
        ok, missing_field = _contact_ok(recipient, provider)
        if not ok:
            skipped.append(
                SkippedRow(
                    row=row_number,
                    reason=f"Missing required '{missing_field}' for provider '{provider}'",
                )
            )
            continue
        resolved.append((row_number, recipient, provider))
    return resolved, skipped


def build_wire_payload(
    recipient: RecipientIn,
    provider: str,
    template: str,
    subject: str | None,
) -> dict:
    """Build the exact dict published via ``NotifyClient.stream()`` (one ``xadd``).

    Implements the per-provider recipient shape table (spec §2) and guards
    all three verified traps: the wire key is ``recipient`` (singular,
    Trap 2); ``username`` is always emitted, falling back to ``name``
    (Trap 1); only the keys the target provider needs are emitted, so
    ``team_id`` is never accidentally present for a ``channel_id``-based
    provider (Trap 3).

    Args:
        recipient: The normalized, already-validated recipient row.
        provider: The resolved provider for this recipient (row override
            or batch default).
        template: The already partially-rendered template string (pass 1
            output) — the same string for every recipient in the batch.
        subject: The message subject, if any.

    Returns:
        The complete wire payload dict, ready to be JSON-encoded and
        ``xadd``-ed unchanged.
    """
    if provider in _EMAIL_PROVIDERS:
        shape = {
            "name": recipient.name,
            "account": {"provider": provider, "address": recipient.email},
        }
    elif provider in _SMS_PROVIDERS:
        shape = {
            "name": recipient.name,
            "account": {"provider": provider, "number": recipient.phone},
        }
    elif provider in _TEAMS_PROVIDERS:
        shape = {
            "name": recipient.name,
            "team_id": recipient.extra.get("team_id"),
            "channel_id": recipient.extra.get("channel_id"),
        }
    elif provider in _TELEGRAM_PROVIDERS:
        shape = {
            "chat_name": recipient.name,
            "chat_id": recipient.extra.get("chat_id"),
        }
    elif provider in _CHANNEL_PROVIDERS:
        shape = {
            "channel_name": recipient.name,
            "channel_id": recipient.extra.get("channel_id"),
        }
    else:
        # Defensive: build_wire_payload is only ever called after
        # validate_and_resolve_provider has already rejected unknown
        # providers, but never guess a shape for one we don't recognize.
        raise RenderError(f"Cannot build a wire payload for unknown provider '{provider}'")

    payload = {
        "provider": provider,
        "recipient": [shape],  # singular key, list value — Trap 2
        "template": template,
        "subject": subject,
        "name": recipient.name,
        "username": recipient.username or recipient.name,  # Trap 1 guard
        "email": recipient.email,
        "phone": recipient.phone,
        "address": recipient.address,
    }
    # Extra columns are forwarded as pass-2 placeholders (spec §3 Module 3),
    # but never allowed to shadow a structural wire-payload key -- see
    # _PROTECTED_PAYLOAD_KEYS. Applied *after* building `payload` so this
    # filter is the definitive, order-independent guard.
    safe_extra = {
        key: value
        for key, value in recipient.extra.items()
        if key not in _PROTECTED_PAYLOAD_KEYS
    }
    payload.update(safe_extra)
    return payload


def build_preview(payload: dict) -> str:
    """Render the exact text pass 2 would produce for one recipient (spec §3 Module 9).

    Simulates ``AbstractProvider._render_``'s context
    (``notify/providers/base.py:177-183``): ``{"recipient": to, "username":
    to, "message": message, "subject": subject, **kwargs}``, where
    ``**kwargs`` is bound **last** and overrides the defaults. Uses the
    *same* ``payload`` :func:`build_wire_payload` produced — never a
    separately-constructed context — so the preview is guaranteed to match
    what a real send would deliver (spec §5 preview-fidelity criterion).
    Because ``build_wire_payload`` always emits a real ``username`` string
    (Trap 1 guard), the simulated default Actor-object binding is always
    overridden here too, exactly as it is in the real pass 2.

    Args:
        payload: A wire payload from :func:`build_wire_payload` (the first
            queued recipient's, by convention).

    Returns:
        The fully-rendered preview text.
    """
    env = Environment(undefined=DebugUndefined, autoescape=False)
    template = env.from_string(payload.get("template") or "")
    context = {
        "recipient": None,  # reserved; never meaningfully used in a template
        "username": None,
        "message": None,
        "subject": payload.get("subject"),
    }
    # Row fields forwarded as pass-2 kwargs — last, so they override the
    # defaults above, exactly like the real `**kwargs` in providers/base.py.
    context.update(
        {
            key: value
            for key, value in payload.items()
            if key not in ("provider", "recipient", "template")
        }
    )
    return template.render(**context)


async def prepare(
    *,
    recipients: list,
    provider: str,
    template_source: str,
    subject: str | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> PreparedBatch:
    """Run every step short of publishing: render, validate, build payloads.

    Shared by ``POST /sender``, ``POST /message``, and both endpoints'
    ``dry_run`` short-circuit (spec §2 "Shared-core requirement"). Performs
    no I/O and publishes nothing — it is safe to call from a plain unit
    test or a future non-HTTP caller (spec G12).

    Args:
        recipients: The already-ingested, normalized recipient rows.
        provider: The batch/request-level default provider.
        template_source: The already-resolved template body (stored,
            inline, or file contents) — resolving *which* template to use
            is the caller's job; this function only renders it.
        subject: The message subject, if any.
        now: Injectable current time, threaded into :func:`resolve_functions`.
        dry_run: When ``True``, the returned :class:`PreparedBatch` carries
            ``dry_run=True`` and a ``preview`` of the first queued
            recipient's fully-rendered (both passes) text — ``None`` when
            nothing is queued (spec §3 Module 9). This flag is only ever
            *recorded*, never acted on here — :func:`prepare` never
            publishes regardless; the actual publish refusal is enforced
            in :mod:`parrot.services.comm_center.dispatch` (defense in
            depth), and the handler is what actually skips
            persistence/fan-out for a dry run.

    Returns:
        A :class:`PreparedBatch` with the resolved functions, the
        partially-rendered template, and the queued/skipped split.

    Raises:
        RenderError: ``template_source`` is not valid Jinja2.
    """
    functions = resolve_functions(now=now)
    rendered_template = partial_render(template_source, functions)

    resolved, skipped = validate_and_resolve_provider(recipients, provider)

    queued: list = []
    for row_number, recipient, resolved_provider in resolved:
        payload = build_wire_payload(recipient, resolved_provider, rendered_template, subject)
        queued.append(
            PreparedMessage(recipient=recipient, payload=payload, row_number=row_number)
        )

    preview = build_preview(queued[0].payload) if dry_run and queued else None

    return PreparedBatch(
        resolved_functions=functions,
        template=rendered_template,
        subject=subject,
        queued=queued,
        skipped=skipped,
        dry_run=dry_run,
        preview=preview,
    )
