from enum import Enum

class GroqModel(Enum):
    """Description for Enabled Groq models.

    Only these models are supporting Structured Output:
    - meta-llama/llama-4-maverick-17b-128e-instruct
    - meta-llama/llama-4-scout-17b-16e-instruct

    Also, streaming output is not supported with structured outputs.
    """
    KIMI_K2_INSTRUCT = "moonshotai/kimi-k2-instruct-0905"
    LLAMA_4_SCOUT_17B = "meta-llama/llama-4-scout-17b-16e-instruct"
    LLAMA_4_MAVERICK_17B = "meta-llama/llama-4-maverick-17b-128e-instruct"
    MISTRAL_SABA_24B = "mistral-saba-24b"
    DEEPSEEK_R1_DISTILL_70B = "deepseek-r1-distill-llama-70b"
    LLAMA_3_3_70B_VERSATILE = "llama-3.3-70b-versatile"
    LLAMA_3_1_8B_INSTANT = "llama-3.1-8b-instant"
    GEMMA2_9B_IT = "gemma2-9b-it"
    QWEN_QWEN3_32B = "qwen/qwen3-32b"
    OPENAI_GPT_OSS_20B = "openai/gpt-oss-20b"
    OPENAI_GPT_OSS_120B = "openai/gpt-oss-120b"
    OPENAI_GPT_OSS_SAFEGUARD_20B = "openai/gpt-oss-safeguard-20b"
