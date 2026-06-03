"""Unit tests for parrot.eval.registry (TASK-1416)."""
import pytest

from parrot.eval.registry import (
    _EVALUATORS,
    _METRICS,
    get_evaluator,
    get_metric,
    list_evaluators,
    list_metrics,
    register_evaluator,
    register_metric,
)


def test_register_and_resolve_evaluator():
    """Registered evaluator can be resolved by name."""
    name = "_test_dummy_eval_1416_a"
    _EVALUATORS.pop(name, None)  # clean up any leftover

    @register_evaluator(name)
    class DummyEval:
        pass

    assert get_evaluator(name) is DummyEval
    _EVALUATORS.pop(name, None)


def test_duplicate_evaluator_raises():
    """Registering two classes under the same name raises ValueError."""
    name = "_test_dup_eval_1416"
    _EVALUATORS.pop(name, None)

    @register_evaluator(name)
    class A:
        pass

    with pytest.raises(ValueError, match=name):

        @register_evaluator(name)
        class B:
            pass

    _EVALUATORS.pop(name, None)


def test_unknown_evaluator_raises_key_error():
    """Asking for an unregistered name raises KeyError."""
    with pytest.raises(KeyError):
        get_evaluator("__totally_unknown__")


def test_list_evaluators_sorted():
    """list_evaluators returns sorted keys."""
    names = list_evaluators()
    assert names == sorted(names)


def test_register_and_resolve_metric():
    """Registered metric can be resolved by name."""
    name = "_test_dummy_metric_1416_a"
    _METRICS.pop(name, None)

    @register_metric(name)
    class DummyMetric:
        pass

    assert get_metric(name) is DummyMetric
    _METRICS.pop(name, None)


def test_duplicate_metric_raises():
    """Registering two metric classes under the same name raises ValueError."""
    name = "_test_dup_metric_1416"
    _METRICS.pop(name, None)

    @register_metric(name)
    class M1:
        pass

    with pytest.raises(ValueError, match=name):

        @register_metric(name)
        class M2:
            pass

    _METRICS.pop(name, None)


def test_unknown_metric_raises_key_error():
    """Asking for an unregistered metric name raises KeyError."""
    with pytest.raises(KeyError):
        get_metric("__totally_unknown_metric__")


def test_list_metrics_sorted():
    """list_metrics returns sorted keys."""
    names = list_metrics()
    assert names == sorted(names)
