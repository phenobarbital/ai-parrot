"""Shared submission pipeline for HTTP, A2UI and audio (FEAT-649 Module 9).

Behaviour-preserving extraction of ``FormAPIHandler.submit_data``'s tail
(validate → plausibility → persist → forward → cleanup → events), so every channel reaches
the same sinks, lifecycle events and forwarder.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict

from ..core.audit_trail import AuditDetail, AuditTrailConfig, ValidationTrace
from ..core.events import FormEventAbort
from ..core.llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    implausible_fields,
    llm_validation_enabled,
)
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
from .validation_trace import ValidationTraceCollector, cap_trace
from .validators import FormValidator, ValidationResult

if TYPE_CHECKING:
    from .llm_quota import QuotaDecision
    from aiohttp import web

    from .forwarder import SubmissionForwarder
    from .partial_saves import PartialSaveStore
    from .sinks.factory import SinkFactory

__all__ = [
    "SubmissionPipeline",
    "SubmitOutcome",
    "SubmitSinkError",
    "ValidationFailed",
    "PlausibilityBlocked",
    "ImplausibleSubmission",
    "PlausibilityRateLimited",
]


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


_DEFAULT_IMPLAUSIBLE_MESSAGE = "This answer does not appear to answer the question."


class ImplausibleSubmission(Exception):
    """Gate refusal (422 class): answers flagged under a non-``annotate`` policy."""

    def __init__(
        self,
        *,
        policy: Literal["review", "reject"],
        fields: list[str],
        report: PlausibilityReport,
    ) -> None:
        self.policy = policy
        self.fields = list(fields)
        self.report = report
        self.errors: dict[str, list[str]] = {
            field_id: [report.items[field_id].reason or _DEFAULT_IMPLAUSIBLE_MESSAGE]
            for field_id in self.fields
            if field_id in report.items
        }
        super().__init__(f"Implausible answers ({policy}): {', '.join(self.fields)}")

    @property
    def code(self) -> str:
        """Return the client-facing refusal code for the enforcement policy."""
        return "PLAUSIBILITY_REVIEW" if self.policy == "review" else "PLAUSIBILITY_REJECTED"


class PlausibilityRateLimited(Exception):
    """The LLM quota denied a plausibility check that the policy cannot skip (429 class)."""

    def __init__(self, retry_after_s: int) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(f"Plausibility check rate limited; retry after {retry_after_s}s")


QuotaCheck = Callable[[], Awaitable["QuotaDecision"]]


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

    @staticmethod
    def _audit_config(form: FormSchema) -> AuditTrailConfig:
        """Return the form's audit config, or the ``summary`` default when absent (FEAT-732)."""
        return form.audit_trail or AuditTrailConfig()

    def _new_collector(self, form: FormSchema, *, locale: str) -> ValidationTraceCollector | None:
        """Build a collector, or ``None`` when detail is OFF — so an audit-off form pays nothing."""
        config = self._audit_config(form)
        if config.detail is AuditDetail.OFF:
            return None
        return ValidationTraceCollector(detail=config.detail, locale=locale)

    def gate_for(
        self, form: FormSchema, report: PlausibilityReport | None, *, ack: bool = False
    ) -> ImplausibleSubmission | None:
        """Return the pure enforcement decision for one plausibility report.

        Args:
            form: The form whose ``llm_validation.on_implausible`` decides.
            report: The plausibility outcome, or ``None`` when no check ran.
            ack: The client reconfirmed these answers (``review`` only).

        Returns:
            The gate exception to raise, or ``None`` when submission may proceed.
        """
        if report is None:
            return None
        policy = form.llm_validation.on_implausible if form.llm_validation else "annotate"
        if policy == "annotate":
            return None
        flagged = implausible_fields(report)
        if not flagged:
            return None
        if policy == "review" and ack:
            return None
        return ImplausibleSubmission(policy=policy, fields=flagged, report=report)

    async def _charge_quota(
        self, form: FormSchema, quota_check: "QuotaCheck | None", *, skippable: bool
    ) -> PlausibilityReport | None:
        """Charge the LLM quota immediately before a plausibility call (FEAT-728).

        Called only once every deterministic step passed and a check is about to
        run, so invalid submissions and LLM-less pipelines never burn quota.

        Args:
            form: The form being checked.
            quota_check: Awaitable returning the limiter decision, or ``None`` for no quota.
            skippable: True when an ``annotate`` form may continue without a verdict.

        Returns:
            ``None`` when the check may run, or a ``skipped`` report when it must be skipped.

        Raises:
            PlausibilityRateLimited: When denied and the call cannot be skipped.
        """
        if quota_check is None:
            return None
        decision = await quota_check()
        if decision.allowed:
            return None
        policy = form.llm_validation.on_implausible if form.llm_validation else "annotate"
        if skippable and policy == "annotate":
            config = form.llm_validation or LLMValidationConfig()
            return PlausibilityReport(status="skipped", reason="rate_limited", threshold=config.threshold)
        raise PlausibilityRateLimited(decision.retry_after_s)

    async def validate(
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str,
        auth_context: AuthContext | None,
        llm_validation: bool = False,
        visit_context: dict[str, Any] | None = None,
        quota_check: "QuotaCheck | None" = None,
    ) -> tuple[ValidationResult, PlausibilityReport | None]:
        """Prepare step: deterministic validation, then plausibility only when valid and requested."""
        result = await self.validator.validate(
            form, data, locale=locale, auth_context=auth_context, visit_context=visit_context
        )
        report: PlausibilityReport | None = None
        if llm_validation and result.is_valid and self.plausibility is not None and self._plausibility_enabled(form):
            await self._charge_quota(form, quota_check, skippable=False)
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
        plausibility_ack: bool = False,
        request: "web.Request | None" = None,
        visit_context: dict[str, Any] | None = None,
        submission_id: str | None = None,
        quota_check: "QuotaCheck | None" = None,
    ) -> SubmitOutcome:
        """Commit step. Raises ValidationFailed, SubmitSinkError, PlausibilityBlocked or FormEventAbort."""
        # Some internal callers use model_copy(update=...), which skips Pydantic validation.
        # Keep the audit fingerprint's enum contract intact at this shared commit boundary.
        if not isinstance(form.unknown_fields, UnknownFieldsPolicy):
            form = form.model_copy(update={"unknown_fields": UnknownFieldsPolicy(form.unknown_fields)})
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
                form,
                data,
                locale=locale,
                auth_context=auth_context,
                visit_context=visit_context,
                trace=self._new_collector(form, locale=locale),
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
                plausibility = await self._charge_quota(form, quota_check, skippable=True)
                if plausibility is None:
                    plausibility = await self.plausibility.check(
                        form, unwrap_voice(result.sanitized_data), locale=locale
                    )

            gate = self.gate_for(form, plausibility, ack=plausibility_ack)
            if gate is not None:
                self.logger.info(
                    "Submission refused by plausibility policy %s for form %s (%d field(s))",
                    gate.policy,
                    form.form_id,
                    len(gate.fields),
                )
                if gate.policy == "reject":
                    await _on_error(gate, "plausibility reject")
                raise gate

            # Storage/wire asymmetry is DELIBERATE (FEAT-458): extras are stored in their own column but
            # flat-merged into the outbound payload. Declared answers win a key collision.
            outbound = {**result.sanitized_data, **extras} if extras else result.sanitized_data

            stored_data = self.attach_verdicts(result.sanitized_data, plausibility)
            ctx = dict(context or {})
            # FEAT-732 — capped BEFORE the merge, so llm_validation is never what gets truncated.
            if isinstance(result.trace, ValidationTrace):
                ctx["validation"] = cap_trace(result.trace, max_bytes=self._audit_config(form).effective_max_bytes)
            if plausibility is not None:
                ctx["llm_validation"] = plausibility.model_dump(mode="json")
                review_policy = form.llm_validation.on_implausible if form.llm_validation else "annotate"
                if plausibility_ack and review_policy == "review" and implausible_fields(plausibility):
                    ctx["llm_validation"]["acknowledged"] = True
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
        except (
            FormEventAbort,
            ValidationFailed,
            SubmitSinkError,
            PlausibilityBlocked,
            ImplausibleSubmission,
            PlausibilityRateLimited,
        ):
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

    def attach_verdicts(self, data: dict[str, Any], report: PlausibilityReport | None) -> dict[str, Any]:
        """Public (audio client-submit mode): copy each verdict into its spoken envelope (``VoiceEvidenceEnvelope.plausibility``); scalars untouched."""
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
