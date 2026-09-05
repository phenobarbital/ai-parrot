"""HuggingFace transformers model catalogue (FEAT-523 folder convention,
TASK-2845).

``TransformersModel`` relocated byte-identical from ``clients/hf.py:27``.
Pure data — no I/O, no imports from ``client.py``.
"""

from enum import Enum


class TransformersModel(Enum):
    """Enum for supported transformer models."""

    DIALOPT_MEDIUM = "microsoft/DialoGPT-medium"
    DIALOPT_SMALL = "microsoft/DialoGPT-small"
    DIALOPT_LARGE = "microsoft/DialoGPT-large"
    TINY_LLM = "arnir0/Tiny-LLM"
    GEMMA_2B = "google/gemma-2-2b-it"
    GEMMA_9B = "google/gemma-2-9b-it"
    GEMMA_3_4B = "google/gemma-3-4b-it"
    GEMMA_3_1B = "google/gemma-3-1b-pt"
    QWEN_1_5B = "Qwen/Qwen2.5-1.5B-Instruct"
    QWEN_3B = "Qwen/Qwen2.5-3B-Instruct"
    QWEN_7B = "Qwen/Qwen2.5-7B-Instruct"
    BCCARD_QWEN_32B = "BCCard/Qwen2.5-VL-32B-Instruct-FP8-Dynamic"
    PHI_3_MINI = "microsoft/Phi-3-mini-4k-instruct"
    PHI_3_SMALL = "microsoft/Phi-3-small-8k-instruct"
    PHI_3_5_MINI = "microsoft/Phi-3.5-mini-instruct"
    OPENAI_GPT_20B = "openai/gpt-oss-20b"
    HUGGINGFACE_TB_SMOLLM2_1_7B = "HuggingFaceTB/SmolLM2-1.7B"
    DEEPSEEK_R1_1B = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
    DEEPSEEK_R1_7B = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"


__all__ = ["TransformersModel"]
