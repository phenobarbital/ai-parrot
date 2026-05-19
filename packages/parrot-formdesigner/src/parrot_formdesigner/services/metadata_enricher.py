"""Before-save submission metadata enrichment.

Given a validated submission, a form schema with declared
``metadata`` entries, and the inbound aiohttp request, this module
resolves every declared field, splits the resulting keys into the
"core" set (promoted to typed ``FormSubmission`` columns) and the
"extra" set (flat-merged into the submission ``data`` JSONB).

The enricher is intentionally a pure function — no HTTP, no DB —
so it is trivial to unit-test against stubbed requests.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .callback_registry import get_form_callback
from .metadata_callbacks import MetadataCallbackInput, MetadataCallbackOutput
from .metadata_sources import (
    BUILTIN_METADATA_SOURCES,
    _extract_org_id,
    _extract_programs,
    _user_attr,
)
from .submissions import CORE_METADATA_COLUMNS

if TYPE_CHECKING:
    from aiohttp import web

    from ..core.schema import FormMetadataField, FormSchema
    from .auth_context import AuthContext
    from .submissions import FormSubmission


logger = logging.getLogger(__name__)


class MetadataResolutionError(Exception):
    """Raised when a required metadata field cannot be resolved.

    The handler maps this to HTTP 422 with the message in
    ``errors._metadata``.
    """


async def enrich_submission(
    *,
    request: "web.Request",
    form: "FormSchema",
    submission: "FormSubmission",
    answers: dict[str, Any],
    auth_context: "AuthContext",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve declared metadata for a pending submission.

    Iterates ``form.metadata`` in declaration order, dispatching each
    entry to either the built-in source resolver
    (:data:`BUILTIN_METADATA_SOURCES`) or a registered async callback
    looked up via :func:`get_form_callback` with tenant fallback.

    Args:
        request: Inbound aiohttp request, used by built-in resolvers
            to read session / user / headers.
        form: The form definition; its ``tenant`` field drives callback
            lookup.
        submission: The in-flight ``FormSubmission`` (constructed but
            not yet stored). Resolvers may read its existing fields
            (e.g. ``submission_id``, ``created_at``).
        answers: Sanitized form answers from the validator.
        auth_context: Runtime auth context forwarded to callbacks.

    Returns:
        Tuple ``(core_overrides, extra_flat)`` where ``core_overrides``
        is a dict whose keys are a subset of ``CORE_METADATA_COLUMNS``
        (to be applied via ``submission.model_copy(update=...)``) and
        ``extra_flat`` is a dict of remaining keys to merge into
        ``submission.data``.

    Raises:
        MetadataResolutionError: When a ``required=True`` entry cannot
            be resolved, or when a callback fan-out returns an invalid
            identifier as a key, or when a resolved key would collide
            with an existing answer in ``answers``.
    """
    core_overrides: dict[str, Any] = {}
    extra_flat: dict[str, Any] = {}

    if not form.metadata:
        return core_overrides, extra_flat

    # Pre-compute identity fields so callbacks see consistent context.
    base_user_id = _user_attr(request, "user_id") or _user_attr(request, "id")
    base_user_id = None if base_user_id is None else str(base_user_id)
    base_username = _user_attr(request, "username") or _user_attr(
        request, "email"
    )
    base_username = None if base_username is None else str(base_username)
    base_org_id = _extract_org_id(request)
    base_programs = _extract_programs(request)
    base_tenant = submission.tenant or form.tenant

    for entry in form.metadata:
        resolved: dict[str, Any] = {}

        try:
            if entry.source == "callback":
                output = await _invoke_callback(
                    entry=entry,
                    submission=submission,
                    form=form,
                    answers=answers,
                    auth_context=auth_context,
                    base_user_id=base_user_id,
                    base_username=base_username,
                    base_org_id=base_org_id,
                    base_tenant=base_tenant,
                    base_programs=base_programs,
                )
                if not output.success:
                    if entry.required:
                        raise MetadataResolutionError(
                            f"required metadata {entry.key!r} failed: "
                            f"{output.error or 'callback returned success=False'}"
                        )
                    logger.warning(
                        "metadata callback %r failed (key=%r): %s — using default",
                        entry.callback_ref,
                        entry.key,
                        output.error,
                    )
                    resolved = {entry.key: entry.default}
                elif output.values is not None:
                    resolved = dict(output.values)
                else:
                    resolved = {entry.key: output.value}
            else:
                resolver = BUILTIN_METADATA_SOURCES.get(entry.source)
                if resolver is None:
                    # Should be unreachable given MetadataSource Literal.
                    raise MetadataResolutionError(
                        f"unknown metadata source {entry.source!r}"
                    )
                value = await resolver(request, submission, form, entry)
                resolved = {entry.key: value}
        except MetadataResolutionError:
            raise
        except Exception as exc:
            if entry.required:
                raise MetadataResolutionError(
                    f"required metadata {entry.key!r} raised: {exc}"
                ) from exc
            logger.warning(
                "metadata resolver for %r raised %s — using default",
                entry.key,
                exc,
                exc_info=True,
            )
            resolved = {entry.key: entry.default}

        # Default substitution + required enforcement happens per key so
        # callback fan-out works the same way as single-value resolvers.
        for key, value in list(resolved.items()):
            if value is None:
                value = entry.default
                resolved[key] = value
            if value is None and entry.required and key == entry.key:
                raise MetadataResolutionError(
                    f"required metadata {entry.key!r} resolved to None"
                )

        for key, value in resolved.items():
            if key in CORE_METADATA_COLUMNS and key == entry.key:
                core_overrides[key] = value
            else:
                if key in answers:
                    raise MetadataResolutionError(
                        f"metadata key {key!r} collides with form answer"
                    )
                extra_flat[key] = value

    return core_overrides, extra_flat


async def _invoke_callback(
    *,
    entry: "FormMetadataField",
    submission: "FormSubmission",
    form: "FormSchema",
    answers: dict[str, Any],
    auth_context: "AuthContext",
    base_user_id: str | None,
    base_username: str | None,
    base_org_id: int | None,
    base_tenant: str | None,
    base_programs: list[str],
) -> MetadataCallbackOutput:
    """Invoke a registered metadata callback and normalise its output.

    Always returns a ``MetadataCallbackOutput``: callbacks that raise or
    return a plain value are wrapped so the caller has a uniform
    surface to interrogate.
    """
    callback_ref = entry.callback_ref or ""
    try:
        callback = get_form_callback(
            callback_ref, tenant=base_tenant
        )
    except KeyError:
        return MetadataCallbackOutput(
            success=False,
            error=f"callback {callback_ref!r} is not registered",
        )

    payload = MetadataCallbackInput(
        form_id=form.form_id,
        submission_id=submission.submission_id,
        user_id=base_user_id,
        username=base_username,
        org_id=base_org_id,
        tenant=base_tenant,
        programs=list(base_programs),
        submitted_at=submission.created_at,
        answers=dict(answers),
        field=entry,
    )

    try:
        result = await callback(payload, auth_context)
    except Exception as exc:
        return MetadataCallbackOutput(
            success=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    if isinstance(result, MetadataCallbackOutput):
        return result
    # Lenient: a bare value is treated as a successful single-value return.
    return MetadataCallbackOutput(success=True, value=result)
