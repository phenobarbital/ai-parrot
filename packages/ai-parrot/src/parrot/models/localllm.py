from enum import Enum


class LocalLLMModel(Enum):
    """Common local LLM model identifiers.

    Enumerates popular open-weight models typically served via
    Ollama, vLLM, llama.cpp, or LM Studio. Values match the model
    name strings expected by these servers.
    """

    # Llama 3.x family
    LLAMA3_8B = "llama3:8b"
    LLAMA3_70B = "llama3:70b"
    LLAMA3_1_8B = "llama3.1:8b"
    LLAMA3_1_70B = "llama3.1:70b"
    LLAMA3_2_3B = "llama3.2:3b"
    LLAMA3_2_11B = "llama3.2:11b"
    LLAMA3_3_70B = "llama3.3:70b"

    # Mistral / Mixtral
    MISTRAL_7B = "mistral:7b"
    MIXTRAL_8X7B = "mixtral:8x7b"
    MISTRAL_SMALL = "mistral-small:latest"

    # Code models
    CODELLAMA_13B = "codellama:13b"
    CODELLAMA_34B = "codellama:34b"

    # Qwen
    QWEN2_5_7B = "qwen2.5:7b"
    QWEN2_5_72B = "qwen2.5:72b"
    QWEN2_5_CODER_7B = "qwen2.5-coder:7b"

    # DeepSeek
    DEEPSEEK_R1 = "deepseek-r1"
    DEEPSEEK_V3 = "deepseek-v3"

    # Microsoft Phi
    PHI3_MINI = "phi3:mini"
    PHI3_MEDIUM = "phi3:medium"

    # Google Gemma
    GEMMA2_9B = "gemma2:9b"
    GEMMA2_27B = "gemma2:27b"

    # Generic placeholder for any custom model
    CUSTOM = "custom"
