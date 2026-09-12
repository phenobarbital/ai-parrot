"""Turn-budget defaults (FEAT-553, spec AC-9)."""

from parrot.flows.dev_loop.agent_builder import DEFAULT_LLM_MAX_TURNS
from parrot.flows.dev_loop.models.grok import GrokCodeDispatchProfile
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile


def test_profile_default_max_turns_is_40():
    assert LLMCodeDispatchProfile().max_turns == 40
    assert GrokCodeDispatchProfile().max_turns == 40


def test_wiring_default_unchanged():
    assert DEFAULT_LLM_MAX_TURNS == 60
