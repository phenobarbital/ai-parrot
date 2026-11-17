"""Shared helpers for tests that must pin the injection-scoring engine.

`PromptInjectionGuardrail.__init__` resolves its engine through the
module-level `_resolve_injection_engine()`
(`bots/guardrails/builtin/prompt_injection.py:617`), whose precedence chain
prefers ONNX when a graph is cached. A suite that mocks a *detector* without
pinning the *engine* gets `_pytector_detector = None`
(`prompt_injection.py:730`) on exactly those machines, and every assertion
driving that alias dies with `AttributeError: 'NoneType'` — `issue:d6027c24b96d`.

Import it relatively from a test inside a package (`from .._injection_test_helpers import mock_pytector_engine`),
or load it by file path from a directory that is not a package (see `tests/unit/test_guardrails_prompt_injection.py`).
The tests directory is deliberately NOT on `sys.path` (FEAT-720).
"""
from typing import Any

from parrot.bots.guardrails.builtin import prompt_injection as pi_module


def mock_pytector_engine(detector: Any) -> Any:
    """Wrap *detector* as a resolved pytector engine.

    Args:
        detector: Usually a `MagicMock` whose `detect_injection` returns a
            `(bool, float)` tuple.

    Returns:
        A `_PytectorInjectionEngine` the guardrail ctor will unwrap back into
        `self._pytector_detector`, so a test can keep driving the mock it
        already holds.
    """
    return pi_module._PytectorInjectionEngine(detector, model_id="mock-pytector")
