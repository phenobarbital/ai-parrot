# Langchain:
from langchain import hub
from ..exceptions import ConfigError  # pylint: disable=E0611

## LLM configuration
from .abstract import AbstractLLM

# Vertex
try:
    from ..llms.vertex import VertexLLM
    VERTEX_ENABLED = True
except (ModuleNotFoundError, ImportError):
    VERTEX_ENABLED = False

# Anthropic:
try:
    from ..llms.anthropic import Anthropic
    ANTHROPIC_ENABLED = True
except (ModuleNotFoundError, ImportError):
    ANTHROPIC_ENABLED = False

# OpenAI
try:
    from ..llms.openai import OpenAILLM
    OPENAI_ENABLED = True
except (ModuleNotFoundError, ImportError):
    OPENAI_ENABLED = False

# LLM Transformers
try:
    from  ..llms.pipes import PipelineLLM
    TRANSFORMERS_ENABLED = True
except (ModuleNotFoundError, ImportError):
    TRANSFORMERS_ENABLED = False

# HuggingFaces Hub:
try:
    from  ..llms.hf import HuggingFace
    HF_ENABLED = True
except (ModuleNotFoundError, ImportError):
    HF_ENABLED = False

# GroQ:
try:
    from ..llms.groq import GroqLLM
    GROQ_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GROQ_ENABLED = False

# Mixtral:
try:
    from ..llms.groq import GroqLLM
    MIXTRAL_ENABLED = True
except (ModuleNotFoundError, ImportError):
    MIXTRAL_ENABLED = False

# Google
try:
    from ..llms.google import GoogleGenAI
    GOOGLE_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GOOGLE_ENABLED = False


def get_llm(llm_name: str, model_name: str, **kwargs) -> AbstractLLM:
    """get_llm.

    Load the Language Model for the Chatbot.
    """
    print('LLM > ', llm_name)
    if llm_name == 'VertexLLM':
        if VERTEX_ENABLED is False:
            raise ConfigError(
                "VertexAI enabled but not installed."
            )
        return VertexLLM(model=model_name, **kwargs)
    if llm_name == 'Anthropic':
        if ANTHROPIC_ENABLED is False:
            raise ConfigError(
                "ANTHROPIC is enabled but not installed."
            )
        return Anthropic(model=model_name, **kwargs)
    if llm_name == 'OpenAI':
        if OPENAI_ENABLED is False:
            raise ConfigError(
                "OpenAI is enabled but not installed."
            )
        return OpenAILLM(model=model_name, **kwargs)
    if llm_name == 'hf':
        if HF_ENABLED is False:
            raise ConfigError(
                "Hugginfaces Hub is enabled but not installed."
            )
        return HuggingFace(model=model_name, **kwargs)
    if llm_name == 'pipe':
        if TRANSFORMERS_ENABLED is False:
            raise ConfigError(
                "Transformes Pipelines are enabled, but not installed."
            )
        return PipelineLLM(model=model_name, **kwargs)
    if llm_name in ('Groq', 'llama3', 'mixtral'):
        if GROQ_ENABLED is False:
            raise ConfigError(
                "Groq is enabled but not installed."
            )
        return GroqLLM(model=model_name, **kwargs)
    if llm_name == 'Google':
        if GOOGLE_ENABLED is False:
            raise ConfigError(
                "Google is enabled but not installed."
            )
        return GoogleGenAI(model=model_name, **kwargs)
    else:
        # TODO: Add more LLMs
        return hub.pull(llm_name)
