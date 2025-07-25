from typing import List, Callable, Optional, Any, Union
import tiktoken
from .base import BaseTextSplitter


class TokenTextSplitter(BaseTextSplitter):
    """
    Text splitter that splits based on token count using various tokenizers.

    Supports:
    - OpenAI tiktoken tokenizers (gpt-3.5-turbo, gpt-4, etc.)
    - Hugging Face transformers tokenizers
    - Custom tokenization functions
    """

    def __init__(
        self,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        model_name: str = "gpt-3.5-turbo",
        encoding_name: Optional[str] = None,
        tokenizer: Optional[Any] = None,
        tokenizer_function: Optional[Callable[[str], List[str]]] = None,
        allowed_special: Union[str, set] = "all",
        disallowed_special: Union[str, set, List] = (),
        **kwargs
    ):
        """
        Initialize TokenTextSplitter.

        Args:
            chunk_size: Maximum number of tokens per chunk
            chunk_overlap: Number of tokens to overlap between chunks
            model_name: Name of the model for tiktoken (e.g., 'gpt-3.5-turbo', 'gpt-4')
            encoding_name: Specific encoding name for tiktoken (e.g., 'cl100k_base')
            tokenizer: Custom tokenizer object (Hugging Face or other)
            tokenizer_function: Custom function that takes text and returns tokens
            allowed_special: Special tokens allowed during encoding
            disallowed_special: Special tokens that raise errors during encoding
        """
        super().__init__(chunk_size, chunk_overlap, **kwargs)

        self.model_name = model_name
        self.encoding_name = encoding_name
        self.allowed_special = allowed_special
        self.disallowed_special = disallowed_special

        # Initialize tokenizer
        if tokenizer_function:
            self._tokenize = tokenizer_function
            self._encode = lambda text: tokenizer_function(text)
            self._decode = lambda tokens: " ".join(tokens)
        elif tokenizer:
            # Hugging Face tokenizer
            self._tokenizer = tokenizer
            self._tokenize = self._hf_tokenize
            self._encode = self._hf_encode
            self._decode = self._hf_decode
        else:
            # Use tiktoken
            try:
                if encoding_name:
                    self._enc = tiktoken.get_encoding(encoding_name)
                else:
                    self._enc = tiktoken.encoding_for_model(model_name)

                self._tokenize = self._tiktoken_tokenize
                self._encode = self._tiktoken_encode
                self._decode = self._tiktoken_decode
            except Exception as e:
                raise ValueError(f"Could not load tokenizer for model {model_name}: {e}")

    def _tiktoken_tokenize(self, text: str) -> List[str]:
        """Tokenize using tiktoken and return string tokens"""
        tokens = self._enc.encode(
            text,
            allowed_special=self.allowed_special,
            disallowed_special=self.disallowed_special
        )
        return [self._enc.decode([token]) for token in tokens]

    def _tiktoken_encode(self, text: str) -> List[int]:
        """Encode text to token IDs using tiktoken"""
        return self._enc.encode(
            text,
            allowed_special=self.allowed_special,
            disallowed_special=self.disallowed_special
        )

    def _tiktoken_decode(self, tokens: List[int]) -> str:
        """Decode token IDs to text using tiktoken"""
        return self._enc.decode(tokens)

    def _hf_tokenize(self, text: str) -> List[str]:
        """Tokenize using Hugging Face tokenizer"""
        return self._tokenizer.tokenize(text)

    def _hf_encode(self, text: str) -> List[int]:
        """Encode text using Hugging Face tokenizer"""
        return self._tokenizer.encode(text, add_special_tokens=False)

    def _hf_decode(self, tokens: List[int]) -> str:
        """Decode tokens using Hugging Face tokenizer"""
        return self._tokenizer.decode(tokens, skip_special_tokens=True)

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        return len(self._encode(text))

    def split_text(self, text: str) -> List[str]:
        """Split text based on token count"""
        if not text:
            return []

        # Encode the entire text
        tokens = self._encode(text)

        if len(tokens) <= self.chunk_size:
            return [text]

        chunks = []
        start_idx = 0

        while start_idx < len(tokens):
            # Determine end index for this chunk
            end_idx = min(start_idx + self.chunk_size, len(tokens))

            # Get tokens for this chunk
            chunk_tokens = tokens[start_idx:end_idx]

            # Decode back to text
            chunk_text = self._decode(chunk_tokens)
            chunks.append(chunk_text)

            # Move start index with overlap
            if end_idx == len(tokens):
                break

            start_idx = end_idx - self.chunk_overlap
            if start_idx < 0:
                start_idx = 0

        return chunks
