"""Unit tests for the ``TOOL_CALL`` guardrail stage (FEAT-406 / TASK-2109).

Verifies the new pre-execution pipeline stage: the enum member exists,
``build_pipelines_from_config()`` builds a pipeline for it automatically
(via enum iteration in ``config.py``), and an empty ``TOOL_CALL`` pipeline
short-circuits with zero overhead.
"""
from parrot.bots.guardrails import (
    GuardrailStage,
    build_pipelines_from_config,
)


def test_tool_call_stage_member():
    assert GuardrailStage.TOOL_CALL == "tool_call"
    assert GuardrailStage.TOOL_CALL.value == "tool_call"


def test_build_pipelines_includes_tool_call():
    pipelines = build_pipelines_from_config()
    assert GuardrailStage.TOOL_CALL in pipelines


def test_empty_tool_call_pipeline_zero_overhead():
    pipelines = build_pipelines_from_config()
    pipeline = pipelines[GuardrailStage.TOOL_CALL]
    assert not pipeline.has_guardrails
