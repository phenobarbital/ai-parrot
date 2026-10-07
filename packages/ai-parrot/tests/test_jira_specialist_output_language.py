"""FEAT-638: the real JiraSpecialist system prompt across languages (TASK-4127)."""
from unittest.mock import patch

import pytest

from parrot.bots.jira_specialist import JiraSpecialist
from parrot.bots.prompts.domain_layers import GROUNDING_SENTINELS

PLACEHOLDERS = ("$output_language", "$sentinel_not_found", "$sentinel_error")


async def _rendered_prompt(language):
    """Build a real JiraSpecialist, run configure-time prompt resolution, return the prompt."""
    with patch("redis.asyncio.from_url"), \
         patch("parrot.bots.jira_specialist.JiraToolkit"), \
         patch("parrot.bots.jira_specialist.config") as mock_config, \
         patch("parrot.bots.abstract.dynamic_values") as mock_dv:
        mock_config.get.return_value = "dummy"
        mock_dv.get_all_names.return_value = []
        agent = JiraSpecialist(language=language) if language is not None else JiraSpecialist()
        await agent._configure_prompt_builder()
        return agent, agent._build_prompt()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "language,directive,sentinel_lang",
    [
        (None, None, "en"),
        ("en", "English", "en"),
        ("es", "Spanish", "es"),
        ("es-MX", "Spanish", "es"),
        ("fr", None, "en"),            # unsupported -> treated as unset
    ],
)
async def test_jira_specialist_prompt_language_matrix(language, directive, sentinel_lang):
    agent, prompt = await _rendered_prompt(language)
    assert isinstance(prompt, str)
    for token in PLACEHOLDERS:
        assert token not in prompt, token
    sentinels = GROUNDING_SENTINELS[sentinel_lang]
    assert sentinels["not_found"] in prompt
    assert sentinels["error"] in prompt
    if directive is None:
        assert "<output_language_policy>" not in prompt
    else:
        assert "<output_language_policy>" in prompt
        assert directive in prompt
    if sentinel_lang == "es":
        assert GROUNDING_SENTINELS["en"]["not_found"] not in prompt
        assert GROUNDING_SENTINELS["en"]["error"] not in prompt
    names = agent.prompt_builder.layer_names
    assert "jira_workflow" in names
    assert "jira_grounding" in names


@pytest.mark.asyncio
async def test_language_survives_into_clone_kwargs():
    agent, _ = await _rendered_prompt("es")
    assert agent._init_kwargs.get("language") == "es"   # clone_for_user rebuilds from _init_kwargs
