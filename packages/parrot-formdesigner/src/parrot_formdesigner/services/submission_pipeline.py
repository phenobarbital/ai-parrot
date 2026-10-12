"""Shared submission pipeline for HTTP, A2UI and audio (FEAT-649 Module 9).

Behaviour-preserving extraction of ``FormAPIHandler.submit_data``'s tail
(validate → plausibility → persist → forward → cleanup → events), so every channel reaches
the same sinks, lifecycle events and forwarder.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from ..core.events import FormEventAbort
from ..core.llm_validation import PlausibilityReport, llm_validation_enabled
from ..core.schema import FormSchema, UnknownFieldsPolicy
from ..core.voice_answer import VoiceEvidenceEnvelope, is_voice_envelope, unwrap_voice
from .auth_context import AuthContext
from .event_dispatcher import dispatch
from .metadata_enricher import MetadataResolutionError, enrich_submission
from .plausibility import AnswerPlausibilityChecker, PlausibilityBlocked
from .sinks.base import SinkNotCapableError, SinkTargetMismatchError, SinkUnavailableError
from .sinks.mapper import flatten_submission, nest_submission
from .submissions import FormSubmission, FormSubmissionStorage
from .unknown_fields import ExtrasCapExceeded, enforce_extras_cap
from .validators import FormValidator, ValidationResult

if TYPE_CHECKING:
    from aiohttp import web

    from .forwarder import SubmissionForwarder
    from .partial_saves import PartialSaveStore
    from .sinks.factory import SinkFactory

__all__ = ["SubmissionPipeline", "SubmitOutcome", "SubmitSinkError", "ValidationFailed", "PlausibilityBlocked"]


class SubmitOutcome(BaseModel):
    """Composite result of a committed submission."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    submission_id: str
    stored_in: Literal["sink", "generic", "none"]
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    plausibility: PlausibilityReport | None = None
    validation: ValidationResult


class ValidationFailed(Exception):
    """Deterministic rejection (422 class). ``errors`` is the exact dict submit_data returns today."""

    def __init__(self, errors: dict[str, Any]) -> None:
        super().__init__(f"Validation failed: {errors}")
        self.errors = errors


class SubmitSinkError(Exception):
    """Sink failure already reported via onError; carries today's HTTP mapping."""

    def __init__(self, message: str, *, status: int, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


class SubmissionPipeline:
    """Validate → plausibility → persist → forward → cleanup → events, for every channel."""

    def __init__(
        self,
        *,
        validator: FormValidator,
        submission_storage: "FormSubmissionStorage | None",
        forwarder: "SubmissionForwarder | None",
        partial_store: "PartialSaveStore | None",
        plausibility: AnswerPlausibilityChecker | None,
        sink_factory: "SinkFactory | None" = None,
        logger: logging.Logger | None = None,
        dispatch_fn: Any = None,
    ) -> None:
        self._dispatch = dispatch_fn or dispatch
        self.validator = validator
        self.submission_storage = submission_storage
        self.forwarder = forwarder
        self.partial_store = partial_store
        self.plausibility = plausibility
        self.sink_factory = sink_factory
        self.logger = logger or logging.getLogger(__name__)

    def _plausibility_enabled(self, form: FormSchema) -> bool:
        """True when any field resolves llm_validation on (field override or form default)."""
        return any(llm_validation_enabled(form, f) for f in form.iter_fields_recursive())

    async def validate(
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str,
        auth_context: AuthContext | None,
        llm_validation: bool = False,
        visit_context: dict[str, Any] | None = None,
    ) -> tuple[ValidationResult, PlausibilityReport | None]:
        """Prepare step: deterministic validation, then plausibility only when valid and requested."""
        result = await self.validator.validate(
            form, data, locale=locale, auth_context=auth_context, visit_context=visit_context
        )
        report: PlausibilityReport | None = None
        if llm_validation and result.is_valid and self.plausibility is not None and self._plausibility_enabled(form):
            report = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale)
        return result, report

    async def submit(
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        tenant: str | None,
        user_id: str | None,
        locale: str,
        context: dict[str, Any] | None,
        extra_data: dict[str, Any] | None,
        auth_context: AuthContext | None,
        merge_session_id: str | None,
        plausibility: PlausibilityReport | None = None,
        request: "web.Request | None" = None,
        visit_context: dict[str, Any] | None = None,
        submission_id: str | None = None,
    ) -> SubmitOutcome:
        """Commit step. Raises ValidationFailed, SubmitSinkError, PlausibilityBlocked or FormEventAbort."""
        auth = auth_context or AuthContext(scheme="none")

        async def _on_error(exc: BaseException, where: str) -> None:
            try:
                await self._dispatch("onError", form=form, request=request, tenant=tenant, auth_context=auth, error=exc)
            except Exception:
                self.logger.exception("onError handler raised during %s", where)

        try:
            # lifecycle: onBeforeSubmit — may mutate payload or abort (abort is never routed to onError)
            resolution = await self._dispatch(
                "onBeforeSubmit", form=form, request=request, tenant=tenant, auth_context=auth, payload=data
            )
            if resolution.payload is not None:
                data = dict(resolution.payload)

            result = await self.validator.validate(
                form, data, locale=locale, auth_context=auth_context, visit_context=visit_context
            )
            if not result.is_valid:
                await _on_error(ValueError(f"Validation failed: {result.errors}"), "validation")
                raise ValidationFailed(result.errors)

            # FEAT-458 — the unknown-fields policy applies to the payload-side diff the validator
            # reported (and never judged); computed AFTER onBeforeSubmit may have replaced the payload.
            policy = form.unknown_fields
            extras: dict[str, Any] = {}
            if result.extra_data:
                if policy == UnknownFieldsPolicy.REJECT:
                    await _on_error(
                        ValueError(f"Unknown fields rejected: {sorted(result.extra_data)}"), "unknown-field reject"
                    )
                    raise ValidationFailed({"__unknown__": sorted(result.extra_data)})
                if policy == UnknownFieldsPolicy.KEEP:
                    try:
                        enforce_extras_cap(result.extra_data)
                    except ExtrasCapExceeded as exc:
                        await _on_error(exc, "extras cap rejection")
                        raise ValidationFailed(
                            {"__unknown__": [f"extras {exc.limit} cap exceeded: {exc.actual} > {exc.maximum}"]}
                        ) from exc
                    extras = result.extra_data
                else:  # DROP — today's behaviour, but no longer silent
                    self.logger.debug(
                        "Discarded %d undeclared field(s) for form %s (unknown_fields=drop)",
                        len(result.extra_data),
                        form.form_id,
                    )

            # Plausibility sits after every deterministic 422 so an invalid submission never costs an LLM call.
            # A report passed in by the caller (audio REVIEW) is used as-is. PlausibilityBlocked propagates.
            if plausibility is None and self.plausibility is not None and self._plausibility_enabled(form):
                plausibility = await self.plausibility.check(form, unwrap_voice(result.sanitized_data), locale=locale)

            # Storage/wire asymmetry is DELIBERATE (FEAT-458): extras are stored in their own column but
            # flat-merged into the outbound payload. Declared answers win a key collision.
            outbound = {**result.sanitized_data, **extras} if extras else result.sanitized_data

            stored_data = self._attach_verdicts(result.sanitized_data, plausibility)
            ctx = dict(context or {})
            if plausibility is not None:
                ctx["llm_validation"] = plausibility.model_dump(mode="json")
            submission = FormSubmission(
                submission_id=submission_id or str(uuid.uuid4()),
                form_uid=form.form_uid,
                form_id=form.form_id,
                form_version=form.version,
                data=stored_data,
                is_valid=True,
                created_at=datetime.now(timezone.utc),
                user_id=user_id,
                locale=locale,
                extra_data=extras or None,
                context=ctx or None,
            )

            # Metadata enrichment runs between validation and storage.
            if form.metadata:
                try:
                    core_overrides, extra_flat = await enrich_submission(
                        request=request,
                        form=form,
                        submission=submission,
                        answers=result.sanitized_data,
                        auth_context=auth,
                    )
                except MetadataResolutionError as exc:
                    await _on_error(exc, "metadata")
                    raise ValidationFailed({"_metadata": str(exc)}) from exc
                if core_overrides:
                    submission = submission.model_copy(update=core_overrides)
                if extra_flat:
                    submission.data = {**submission.data, **extra_flat}

            # Persist (FEAT-457): a form declaring `persistence` writes EXCLUSIVELY to its own sink —
            # the generic storage is never called and a sink failure never falls back to it.
            stored_in: Literal["sink", "generic", "none"]
            if form.persistence is not None:
                try:
                    if self.sink_factory is None:
                        raise SinkUnavailableError(
                            "Form declares persistence but no sink_factory is configured on this handler"
                        )
                    sink = await self.sink_factory.get(form, tenant=tenant)
                    await sink.ensure_target(form)
                    payload = (
                        nest_submission(form, submission)
                        if sink.family == "document"
                        else flatten_submission(form, submission)
                    )
                    await sink.write(submission, payload)
                except SinkUnavailableError as exc:
                    await _on_error(exc, "sink write")
                    raise SubmitSinkError(str(exc), status=503, headers={"Retry-After": "30"}) from exc
                except SinkTargetMismatchError as exc:
                    await _on_error(exc, "sink write")
                    raise SubmitSinkError(str(exc), status=422) from exc
                except SinkNotCapableError as exc:
                    await _on_error(exc, "sink write")
                    raise SubmitSinkError(str(exc), status=501) from exc
                stored_in = "sink"
            elif self.submission_storage is not None:
                await self.submission_storage.store(submission)
                stored_in = "generic"
            else:
                self.logger.debug(
                    "No submission_storage configured — skipping local storage for %s", submission.submission_id
                )
                stored_in = "none"

            # Forward to endpoint (FEAT-458: flat-merged outbound payload on the wire, DELIBERATELY).
            forwarded = False
            forward_status: int | None = None
            forward_error: str | None = None
            if form.submit is not None and form.submit.action_type == "endpoint" and self.forwarder is not None:
                fwd_result = await self.forwarder.forward(outbound, form.submit)
                forwarded = fwd_result.success
                forward_status = fwd_result.status_code
                forward_error = fwd_result.error
                if not forwarded:
                    self.logger.warning("Forward failed for submission %s: %s", submission.submission_id, forward_error)

            # Cleanup: delete cached partial after successful submission
            if merge_session_id and self.partial_store is not None:
                try:
                    await self.partial_store.delete(str(form.form_uid), merge_session_id)
                except Exception as exc:
                    self.logger.warning(
                        "Failed to delete partial after submit %s/%s: %s", form.form_uid, merge_session_id, exc
                    )

            # lifecycle: onAfterSubmit — under `keep`, handlers see the same merged view as the endpoint.
            after_submit_payload = {**submission.data, **extras} if extras else submission.data
            await self._dispatch(
                "onAfterSubmit",
                form=form,
                request=request,
                tenant=tenant,
                auth_context=auth,
                payload=after_submit_payload,
            )

            return SubmitOutcome(
                submission_id=submission.submission_id,
                stored_in=stored_in,
                forwarded=forwarded,
                forward_status=forward_status,
                forward_error=forward_error,
                plausibility=plausibility,
                validation=result,
            )
        except (FormEventAbort, ValidationFailed, SubmitSinkError, PlausibilityBlocked):
            raise
        except Exception as exc:
            user_message: str | None = None
            try:
                err_res = await self._dispatch(
                    "onError", form=form, request=request, tenant=tenant, auth_context=auth, error=exc
                )
                user_message = err_res.user_message
            except Exception:
                self.logger.exception("onError handler itself raised")
            if user_message and request is not None:
                request["_lifecycle_user_message"] = user_message
            self.logger.exception("submit failed for form %r: %s", form.form_uid, type(exc).__name__)
            raise

    def _attach_verdicts(self, data: dict[str, Any], report: PlausibilityReport | None) -> dict[str, Any]:
        """Copy each verdict into its spoken envelope (``VoiceEvidenceEnvelope.plausibility``); scalars untouched."""
        if report is None or not report.items:
            return data
        out = dict(data)
        for field_id, verdict in report.items.items():
            value = out.get(field_id)
            if is_voice_envelope(value):
                raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
                raw["plausibility"] = verdict.model_dump(mode="json")
                out[field_id] = VoiceEvidenceEnvelope.model_validate(raw).model_dump(mode="json")
        return out
