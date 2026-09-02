"""FEAT-481 — live structured-output regression tests across LLM providers.

These tests make **real, billable** provider calls. They are marked
``real_llm`` and are skipped unless ``PARROT_TEST_REAL_LLM=1`` is set (see
``tests/conftest.py``), and each individual test additionally skips when its
provider's credentials are not configured on the machine.

They lock in the three findings the ``artifacts/feat481_structured_output_matrix.py``
matrix established against live providers:

1. ``invoke()`` silently ignores the caller's model selection when the client
   defines ``_lightweight_model`` — see :func:`test_invoke_honours_selected_model`.
2. A response truncated at the output-token cap becomes a raw ``str`` rather
   than an error, so callers dereference a string as a model — see
   :func:`test_truncated_structured_output_is_not_silently_a_string`.
3. Given enough budget, mainstream models satisfy the schema; the failure is
   not schema-level — see :func:`test_model_satisfies_meeting_page_schema`.

Test 1 is the one that will fail today and should keep failing until the
resolution order in ``AbstractClient._resolve_invoke_model`` is fixed; it is
marked ``xfail(strict=False)`` so it records the defect without breaking a
live-test run, and flips to XPASS the moment the fix lands.

Run with::

    source .venv/bin/activate
    PARROT_TEST_REAL_LLM=1 pytest \\
        packages/ai-parrot/tests/clients/test_structured_output_live_matrix.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
_HARNESS_PATH = REPO_ROOT / "artifacts" / "feat481_structured_output_matrix.py"


def _load_harness():
    """Import the matrix harness as a module.

    It lives under ``artifacts/`` rather than in an installed package because
    it is a diagnostic tool, not shipped code — but the schemas, prompts and
    verdict logic in it are exactly what these tests need, and duplicating them
    here would let the test and the harness drift apart silently.

    Returns:
        The loaded harness module.
    """
    spec = importlib.util.spec_from_file_location("feat481_matrix", _HARNESS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["feat481_matrix"] = module
    spec.loader.exec_module(module)
    return module


pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.asyncio,
    pytest.mark.skipif(not _HARNESS_PATH.exists(), reason="matrix harness not present"),
]


@pytest.fixture(scope="module")
def harness():
    """The loaded matrix harness."""
    return _load_harness()


@pytest.fixture(scope="module")
def prompt(harness):
    """The real FEAT-481 extraction prompt over the committed large fixture."""
    meeting = harness.load_meeting(None, harness.DEFAULT_FIXTURE)
    return harness.build_prompt(meeting, transcript=False)


def _require(harness, spec: str) -> None:
    """Skip when *spec*'s provider has no credentials on this machine."""
    reason = harness.missing_credential(spec.split(":", 1)[0])
    if reason:
        pytest.skip(f"{spec}: {reason}")


#: Output budget for the satisfaction test. 4096 (``invoke()``'s default) is
#: too small for this schema on several models, and 12288 exceeds Nova Pro's
#: own 10000 cap — 8192 clears the schema on every model listed below while
#: staying inside every provider's per-model limit.
_BUDGET = 8192

#: Models the live matrix showed satisfying the schema when given a sufficient
#: output budget. Kept small on purpose — this is a regression guard, not a
#: re-run of the full matrix (use the harness for that).
SATISFYING_MODELS = [
    "google:gemini-2.5-pro",
    "google:gemini-2.5-flash-lite",
    "bedrock-converse:claude-haiku-4-5",
    "nova:nova-pro",
]


@pytest.mark.parametrize("spec", SATISFYING_MODELS)
async def test_model_satisfies_meeting_page_schema(harness, prompt, spec):
    """A mainstream model returns the typed model, not a raw string.

    Guards the finding that ``MeetingPageExtraction`` is satisfiable: if this
    starts failing broadly, the schema really has become the problem.
    """
    _require(harness, spec)
    row = await harness.probe_cell(
        spec, "page", prompt, pin_model=True, max_tokens=_BUDGET, timeout=300.0
    )
    if row["verdict"] in ("UNAVAIL", "SKIP"):
        pytest.skip(f"{spec}: {row['detail']}")
    assert row["verdict"] == "OK", (
        f"{spec} did not satisfy MeetingPageExtraction: {row['verdict']} — {row['detail']} "
        f"(finish_reason={row.get('finish_reason')!r})"
    )


@pytest.mark.parametrize("spec", ["google:gemini-2.5-pro", "google:gemini-2.5-flash"])
async def test_invoke_honours_selected_model(harness, prompt, spec):
    """``invoke()`` must run the model the caller selected.

    ``LLMFactory.create("google:gemini-2.5-pro")`` sets ``self.model``, but
    ``_resolve_invoke_model()`` ranks ``self._lightweight_model`` above it, so
    an ``invoke()`` call with no explicit ``model=`` silently runs
    ``gemini-3.1-flash-lite`` instead. That substitution is what made three
    different Gemini tiers produce byte-identical failures in the original
    FEAT-481 probe and led to the wrong "schema-level" conclusion.

    Marked non-strict xfail: it documents the defect today and turns XPASS
    when the resolution order is fixed.
    """
    _require(harness, spec)
    requested = spec.split(":", 1)[1]
    row = await harness.probe_cell(
        spec, "classification", prompt, pin_model=False, max_tokens=4096, timeout=300.0
    )
    if row["verdict"] in ("UNAVAIL", "SKIP"):
        pytest.skip(f"{spec}: {row['detail']}")
    effective = row["effective_model"]
    if requested not in effective:
        pytest.xfail(
            f"known FEAT-481 defect: invoke() ran {effective!r} instead of the "
            f"selected {requested!r} (_lightweight_model outranks self.model in "
            f"AbstractClient._resolve_invoke_model)"
        )
    assert requested in effective


async def test_truncated_structured_output_is_not_silently_a_string(harness, prompt):
    """A response cut off at the token cap must not surface as a raw ``str``.

    ``gemini-3.1-flash-lite`` degenerates into a repetition loop on this
    schema and is truncated at the cap every time. Whatever the client does
    about that — reformat, retry, raise — it must not hand the caller a
    ``str`` typed as ``MeetingPageExtraction``, because the caller then
    dereferences it and crashes far from the cause.

    Marked non-strict xfail on ``dev``, where ``invoke()`` still returns the
    string; it flips to XPASS once a guard lands.
    """
    spec = "google:gemini-3.1-flash-lite"
    _require(harness, spec)
    row = await harness.probe_cell(
        spec, "page", prompt, pin_model=True, max_tokens=4096, timeout=300.0
    )
    if row["verdict"] in ("UNAVAIL", "SKIP"):
        pytest.skip(f"{spec}: {row['detail']}")
    if row["verdict"] == "OK":
        pytest.skip("model did not degenerate on this run — nothing to assert about the leak")
    if row["verdict"] == "STR-LEAK":
        pytest.xfail(
            "known FEAT-481 defect: a MAX_TOKENS-truncated response is returned as a raw "
            f"str ({row['detail']}); finish_reason={row.get('finish_reason')!r}"
        )
    assert row["verdict"] == "INVOKE-ERROR", (
        f"expected a raised error rather than a leaked string, got {row['verdict']}"
    )
