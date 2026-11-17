"""FEAT-796 TASK-5137 — DEFAULT_LLM replaces the dead DEFAULT_LLM_MODEL_NAME."""

from navconfig import config

from parrot import conf


def test_default_llm_model_name_removed() -> None:
    """The obsolete, model-only default setting is not exported."""
    assert not hasattr(conf, "DEFAULT_LLM_MODEL_NAME")


def test_default_llm_attribute_exists() -> None:
    """The global LLM default mirrors navconfig and is None when unset."""
    expected_default = config.get("DEFAULT_LLM", fallback=None)

    assert hasattr(conf, "DEFAULT_LLM")
    assert conf.DEFAULT_LLM == expected_default
    if expected_default is None:
        assert conf.DEFAULT_LLM is None
