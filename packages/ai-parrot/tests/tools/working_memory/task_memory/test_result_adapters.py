"""Unit tests for the typed result adapters (FEAT-538 / TASK-2982).

Required case from the task's Test Specification:

- ``test_typed_results`` — denied/error/cancelled/partial results preserve
  outcome semantics, and business dictionaries are not globally mistaken
  for envelopes.

Implemented as focused functions plus an aggregate carrying the required
name, so a failure names the invariant that broke.

The adapters recognise envelopes and manifests structurally rather than
by ``isinstance``, so several tests deliberately exercise the **real**
``ToolResult``, ``ArtifactRef`` and ``ExecutionManifest`` classes: that is
what stops the duck-typing and the real shapes from drifting apart
silently.
"""

from __future__ import annotations

import asyncio

import pytest
from parrot.bots.flows.plan.models import ArtifactRef, ExecutionManifest
from parrot.memory.compaction.models import ToolStatus
from parrot.tools.abstract import ToolResult
from parrot.tools.working_memory.task_memory.adapters import (
    DispatchOutcome,
    OutcomeSource,
    classify,
    classify_exception,
    classify_result,
    looks_like_error_mapping,
    looks_like_manifest,
    looks_like_tool_result,
    to_tool_invocation,
)
from parrot.tools.working_memory.task_memory.models import CallOutcome, Limits

# ─────────────────────────────────────────────────────────────
# Ordinary values
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "a plain string",
        42,
        3.14,
        True,
        None,
        ["a", "list"],
        {"rows": 12, "name": "sales"},
        b"raw bytes",
    ],
    ids=["str", "int", "float", "bool", "none", "list", "dict", "bytes"],
)
def test_typed_results_ordinary_values_succeed(value: object) -> None:
    """A value carrying no typed failure signal is a success."""
    outcome = classify_result(value)
    assert outcome.outcome is CallOutcome.SUCCESS
    assert outcome.executed is True
    assert outcome.source is OutcomeSource.ORDINARY_VALUE
    assert outcome.error is None


@pytest.mark.parametrize(
    "text",
    [
        "Error: the database is unreachable",
        "FAILED to connect",
        "Traceback (most recent call last): ...",
        "status: error",
        "exception raised while processing",
        "the request was denied",
    ],
)
def test_typed_results_never_infers_failure_from_prose(text: str) -> None:
    """Free text is never parsed to infer an outcome.

    This is the specification's explicit prohibition. A tool that
    *returns* a string describing an error has returned a value and
    succeeded — a search tool reporting on an outage must not have its
    step marked failed.
    """
    outcome = classify_result(text)
    assert outcome.outcome is CallOutcome.SUCCESS, "prose must never decide an outcome"
    assert outcome.source is OutcomeSource.ORDINARY_VALUE


def test_typed_results_business_dicts_are_not_envelopes() -> None:
    """A mapping is an envelope only when its status is a known failure."""
    for business in (
        {"status": "shipped", "order": 7},
        {"status": "ok", "rows": 3},
        {"status": "success", "rows": 3},
        {"result": None, "error": None},
        {"success": False, "note": "a business flag, not an envelope"},
        {"errors": ["validation failed"]},
        {"error": "a business field with no status"},
        {},
    ):
        assert not looks_like_error_mapping(business), business
        assert classify_result(business).outcome is CallOutcome.SUCCESS, business


def test_typed_results_shape_predicates_are_mutually_exclusive() -> None:
    """A mapping is never mistaken for a ``ToolResult`` model."""
    envelope_shaped_dict = {"success": False, "status": "error", "result": None, "error": "boom"}
    assert looks_like_tool_result(envelope_shaped_dict) is False
    assert looks_like_manifest(envelope_shaped_dict) is False
    # It is still an error *mapping*, which is a different, narrower rule.
    assert looks_like_error_mapping(envelope_shaped_dict) is True

    real = ToolResult(success=False, status="error", result=None, error="boom")
    assert looks_like_tool_result(real) is True
    assert looks_like_error_mapping(real) is False


# ─────────────────────────────────────────────────────────────
# ToolResult envelopes — verified against the real class
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "expected_outcome", "expected_executed"),
    [
        ("success", CallOutcome.SUCCESS, True),
        ("error", CallOutcome.ERROR, True),
        ("not_found", CallOutcome.NOT_EXECUTED, False),
        ("authorization_required", CallOutcome.NOT_EXECUTED, False),
        ("forbidden", CallOutcome.DENIED, False),
        ("cancelled", CallOutcome.CANCELLED, True),
        ("timeout", CallOutcome.UNKNOWN, True),
        ("pending", CallOutcome.UNKNOWN, True),
    ],
)
def test_typed_results_tool_result_statuses(
    status: str, expected_outcome: CallOutcome, expected_executed: bool
) -> None:
    """Every status the dispatcher can return maps to a typed outcome."""
    envelope = ToolResult(
        success=status == "success",
        status=status,
        result=None,
        error=None if status == "success" else f"{status} happened",
    )
    outcome = classify_result(envelope)
    assert outcome.outcome is expected_outcome
    assert outcome.executed is expected_executed
    assert outcome.status == status
    assert outcome.source is OutcomeSource.TOOL_RESULT


def test_typed_results_early_returns_never_claim_a_body_ran() -> None:
    """The dispatcher's early returns are unsuccessful *dispatch* outcomes.

    An unknown tool, a guard denial and an authorization requirement all
    return before any tool body is entered, so nothing downstream may
    record that one ran.
    """
    for status in ("not_found", "forbidden", "authorization_required"):
        envelope = ToolResult(success=False, status=status, result=None, error="nope")
        outcome = classify_result(envelope)
        assert outcome.executed is False, f"{status} must not claim a tool body ran"
        assert outcome.outcome is not CallOutcome.ERROR, f"{status} is not a failed tool"


def test_typed_results_both_dispatch_modes_agree() -> None:
    """Default mode and full-result mode reach the same outcome.

    Verified against the real dispatcher's behaviour: the ``AbstractTool``
    branch **raises** ``ValueError`` for a ``status == "error"`` envelope
    in default mode, while ``return_tool_result=True`` **returns** that
    envelope. Enabling full-result mode must not change a step's history.
    """
    full_result_mode = classify_result(ToolResult(success=False, status="error", result=None, error="boom"))
    default_mode = classify_exception(ValueError("boom"))

    assert full_result_mode.outcome is default_mode.outcome is CallOutcome.ERROR
    assert full_result_mode.executed is default_mode.executed is True


def test_typed_results_success_flag_overrides_a_success_status() -> None:
    """An explicit ``success=False`` beats an optimistic status label."""
    envelope = ToolResult(success=False, status="success", result=None, error="actually failed")
    assert classify_result(envelope).outcome is CallOutcome.ERROR


def test_typed_results_unfamiliar_status_is_not_guessed_as_failure() -> None:
    """An unrecognised status on a typed envelope defaults to success."""
    envelope = ToolResult(success=True, status="throttled_but_ok", result=1, error=None)
    assert classify_result(envelope).outcome is CallOutcome.SUCCESS


def test_typed_results_error_text_is_clipped() -> None:
    """Typed error text is bounded before it can reach a journal payload."""
    envelope = ToolResult(success=False, status="error", result=None, error="x" * 50_000)
    outcome = classify_result(envelope)
    assert outcome.error is not None
    assert len(outcome.error) <= Limits.MAX_REASON


# ─────────────────────────────────────────────────────────────
# Toolkit error dictionaries
# ─────────────────────────────────────────────────────────────


def test_typed_results_toolkit_error_dicts() -> None:
    """The documented ``{"status": "error"}`` toolkit convention is honoured."""
    outcome = classify_result({"status": "error", "detail": "Invalid layout"})
    assert outcome.outcome is CallOutcome.ERROR
    assert outcome.executed is True
    assert outcome.error == "Invalid layout"
    assert outcome.source is OutcomeSource.ERROR_MAPPING


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ({"status": "error", "error": "e"}, "e"),
        ({"status": "error", "detail": "d"}, "d"),
        ({"status": "error", "message": "m"}, "m"),
        ({"status": "error", "errors": ["first", "second"]}, "first"),
        ({"status": "error"}, None),
    ],
)
def test_typed_results_error_dict_message_fields(mapping: dict, expected: object) -> None:
    """The message is taken from a typed field, in a documented order."""
    assert classify_result(mapping).error == expected


def test_typed_results_error_dict_status_variants() -> None:
    """Case and whitespace in a status do not change its meaning."""
    for status in ("ERROR", " error ", "Error"):
        assert classify_result({"status": status}).outcome is CallOutcome.ERROR


# ─────────────────────────────────────────────────────────────
# Plan manifests — verified against the real classes
# ─────────────────────────────────────────────────────────────


def test_typed_results_manifest_all_ok_succeeds() -> None:
    """A manifest whose nodes all succeeded is a success."""
    manifest = ExecutionManifest(
        plan_name="p",
        objective="o",
        artifacts=[ArtifactRef(node_id="a", status="ok"), ArtifactRef(node_id="b", status="skipped")],
        nodes_total=2,
        nodes_ok=1,
        nodes_skipped=1,
        nodes_failed=0,
    )
    outcome = classify_result(manifest)
    assert outcome.outcome is CallOutcome.SUCCESS
    assert outcome.partial is False
    assert outcome.source is OutcomeSource.PLAN_MANIFEST


def test_typed_results_manifest_partial_is_not_completion_evidence() -> None:
    """A partial manifest is explicitly not valid completion evidence."""
    manifest = ExecutionManifest(
        plan_name="p",
        objective="o",
        artifacts=[ArtifactRef(node_id="a", status="partial", errors=["item 3 failed"])],
        nodes_total=1,
        nodes_ok=1,
        nodes_failed=0,
    )
    outcome = classify_result(manifest)
    assert outcome.outcome is CallOutcome.ERROR
    assert outcome.partial is True
    assert outcome.status == "partial"
    assert outcome.error is not None and "item 3 failed" in outcome.error


def test_typed_results_manifest_failed_nodes() -> None:
    """A manifest reporting failed nodes is a failure."""
    manifest = ExecutionManifest(
        plan_name="p",
        objective="o",
        artifacts=[ArtifactRef(node_id="a", status="error", errors=["boom"])],
        nodes_total=1,
        nodes_failed=1,
    )
    outcome = classify_result(manifest)
    assert outcome.outcome is CallOutcome.ERROR
    assert outcome.partial is False
    assert outcome.error is not None and "a: boom" in outcome.error


def test_typed_results_manifest_failed_count_alone_is_enough() -> None:
    """``nodes_failed`` is honoured even when no artifact ref says so."""
    manifest = ExecutionManifest(plan_name="p", objective="o", nodes_total=1, nodes_failed=1)
    assert classify_result(manifest).outcome is CallOutcome.ERROR


# ─────────────────────────────────────────────────────────────
# Exceptions and cancellation
# ─────────────────────────────────────────────────────────────


def test_typed_results_exceptions_fail() -> None:
    """A raised exception is a failure, and its type is recorded."""
    outcome = classify_exception(RuntimeError("kaboom"))
    assert outcome.outcome is CallOutcome.ERROR
    assert outcome.executed is True
    assert outcome.error == "RuntimeError: kaboom"
    assert outcome.source is OutcomeSource.EXCEPTION


def test_typed_results_cancellation_is_unresolved() -> None:
    """Cancellation is neither success nor failure — it is unresolved."""
    outcome = classify_exception(asyncio.CancelledError())
    assert outcome.outcome is CallOutcome.CANCELLED
    assert outcome.is_resolved is False
    assert outcome.source is OutcomeSource.CANCELLATION


def test_typed_results_unresolved_outcomes_are_not_retryable_failures() -> None:
    """Timeout, pending and cancellation all stay unresolved."""
    for value in (
        ToolResult(success=False, status="timeout", result=None, error="t"),
        ToolResult(success=False, status="pending", result=None, error="p"),
        ToolResult(success=False, status="cancelled", result=None, error="c"),
    ):
        assert classify_result(value).is_resolved is False


def test_typed_results_exception_before_execution() -> None:
    """A dispatcher failure before execution does not claim a body ran."""
    outcome = classify_exception(RuntimeError("resolver exploded"), executed=False)
    assert outcome.executed is False


def test_typed_results_classify_dispatches_on_what_happened() -> None:
    """``classify`` picks the value or exception path."""
    assert classify(value="ok").outcome is CallOutcome.SUCCESS
    assert classify(exception=RuntimeError("x")).outcome is CallOutcome.ERROR
    # An exception always wins, since a raising dispatch returned nothing.
    assert classify(value="ok", exception=RuntimeError("x")).outcome is CallOutcome.ERROR


# ─────────────────────────────────────────────────────────────
# Canonical invocation payload
# ─────────────────────────────────────────────────────────────


def test_typed_results_tool_invocation_uses_only_existing_statuses() -> None:
    """``ToolInvocation`` keeps its two statuses; richness lives elsewhere.

    ``ToolStatus`` has only ``COMPLETED`` and ``ERROR``. The adapters must
    not invent members on it — cancellation, unknown, denied and
    not-executed are carried by ``InvocationRecord`` and journal events.
    """
    assert {s.value for s in ToolStatus} == {"completed", "error"}

    for outcome_value, expected in (
        (CallOutcome.SUCCESS, ToolStatus.COMPLETED),
        (CallOutcome.ERROR, ToolStatus.ERROR),
        (CallOutcome.DENIED, ToolStatus.ERROR),
        (CallOutcome.CANCELLED, ToolStatus.ERROR),
        (CallOutcome.UNKNOWN, ToolStatus.ERROR),
        (CallOutcome.NOT_EXECUTED, ToolStatus.ERROR),
    ):
        outcome = DispatchOutcome(outcome=outcome_value, executed=True)
        assert outcome.tool_status is expected


def test_typed_results_to_tool_invocation_builds_the_shared_payload() -> None:
    """One canonical payload feeds both the journal and the turn."""
    outcome = classify_result(ToolResult(success=False, status="error", result=None, error="boom"))
    invocation = to_tool_invocation(
        tool_name="wm_store",
        arguments={"key": "sales"},
        outcome=outcome,
        output="partial output",
        elapsed_ms=17,
        wm_key="__tee__:wm_store:1",
    )
    assert invocation.tool_name == "wm_store"
    assert invocation.input == {"key": "sales"}
    assert invocation.status is ToolStatus.ERROR
    assert invocation.error == "boom"
    assert invocation.elapsed_ms == 17
    assert invocation.output_chars == len("partial output")
    assert invocation.wm_key == "__tee__:wm_store:1"


def test_typed_results_to_tool_invocation_copies_arguments() -> None:
    """The payload never aliases the caller's argument mapping."""
    arguments = {"key": "sales"}
    invocation = to_tool_invocation(tool_name="t", arguments=arguments, outcome=classify_result("ok"))
    arguments["key"] = "mutated"
    assert invocation.input == {"key": "sales"}


def test_typed_results() -> None:
    """Required aggregate case: typed outcomes preserved, business dicts respected."""
    test_typed_results_business_dicts_are_not_envelopes()
    test_typed_results_shape_predicates_are_mutually_exclusive()
    test_typed_results_early_returns_never_claim_a_body_ran()
    test_typed_results_both_dispatch_modes_agree()
    test_typed_results_success_flag_overrides_a_success_status()
    test_typed_results_unfamiliar_status_is_not_guessed_as_failure()
    test_typed_results_error_text_is_clipped()
    test_typed_results_toolkit_error_dicts()
    test_typed_results_error_dict_status_variants()
    test_typed_results_manifest_all_ok_succeeds()
    test_typed_results_manifest_partial_is_not_completion_evidence()
    test_typed_results_manifest_failed_nodes()
    test_typed_results_manifest_failed_count_alone_is_enough()
    test_typed_results_exceptions_fail()
    test_typed_results_cancellation_is_unresolved()
    test_typed_results_unresolved_outcomes_are_not_retryable_failures()
    test_typed_results_tool_invocation_uses_only_existing_statuses()
    for prose in ("Error: boom", "FAILED", "denied"):
        test_typed_results_never_infers_failure_from_prose(prose)
