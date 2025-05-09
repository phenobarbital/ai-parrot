from .groq import GroqLLM

class GemmaLLM(GroqLLM):
    """GemmaLLM.
        Using Google Gemma Open-source LLM Model.

    """
    model: str = "gemma2-9b-it"
    max_tokens: int = 1024
    top_k: float = 50
    top_p: float = 0.9

    def __init__(self, *args, **kwargs):
        self.model = "gemma2-9b-it"
        super().__init__(*args, **kwargs)
