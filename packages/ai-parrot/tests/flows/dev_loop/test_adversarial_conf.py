"""Unit tests for FEAT-375 config keys (TASK-1904: Module 6 config + wiring)."""

from __future__ import annotations


def test_conf_defaults():
    from parrot import conf

    assert conf.DEV_LOOP_ADVERSARIAL_MODEL == "gpt-5.5"
    assert conf.DEV_LOOP_ADVERSARIAL_SCOPE == "uncommitted"
    assert conf.DEV_LOOP_CODEREVIEW_JUDGE is False
    assert conf.DEV_LOOP_GATE_TTL_REVIEW_ESCALATION == 86400
    # Code-review fix follow-up: DEV_LOOP_ADVERSARIAL_BASE_REF backs "base"
    # scope wiring in examples/dev_loop/server.py.
    assert conf.DEV_LOOP_ADVERSARIAL_BASE_REF == ""


def test_conf_new_envs_are_correct_types():
    from parrot import conf

    assert isinstance(conf.DEV_LOOP_ADVERSARIAL_MODEL, str)
    assert isinstance(conf.DEV_LOOP_ADVERSARIAL_SCOPE, str)
    assert isinstance(conf.DEV_LOOP_CODEREVIEW_JUDGE, bool)
    assert isinstance(conf.DEV_LOOP_GATE_TTL_REVIEW_ESCALATION, int)
    assert isinstance(conf.DEV_LOOP_ADVERSARIAL_BASE_REF, str)


def test_no_getattr_conf_shims_remain():
    """TASK-1902/1903 introduced getattr(conf, ..., fallback) shims — this
    task must replace them with direct conf.X references now that the keys
    exist (acceptance criterion)."""
    import inspect

    from parrot.flows.dev_loop import code_review
    from parrot.flows.dev_loop.nodes import qa

    for module in (code_review, qa):
        source = inspect.getsource(module)
        assert 'getattr(conf, "DEV_LOOP_ADVERSARIAL_MODEL"' not in source
        assert 'getattr(conf, "DEV_LOOP_GATE_TTL_REVIEW_ESCALATION"' not in source
