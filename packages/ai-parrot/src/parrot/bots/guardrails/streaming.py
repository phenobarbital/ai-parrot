"""Streaming adapter contract for output guardrails.

A ``StreamingGuardrail`` lets a TRANSFORM-capable output guardrail run on
individual chunks emitted by ``ask_stream`` while still producing the same
result a non-streaming ``check()`` call would produce on the fully
concatenated content.
"""
from abc import ABC, abstractmethod


class StreamingGuardrail(ABC):
    """Adapter contract for guardrails that operate on streamed chunks.

    Implementations may buffer content across ``feed()`` calls (e.g. to
    avoid splitting a secret or PII span across chunk boundaries) and must
    release any withheld content in ``flush()`` once the stream ends.

    Invariant: the concatenation of every non-empty ``feed()`` return value
    plus the final ``flush()`` return value must equal what a non-streaming
    ``Guardrail.check()`` transform would produce on the fully concatenated
    input.
    """

    @abstractmethod
    def feed(self, chunk: str) -> str:
        """Process one streamed chunk.

        Args:
            chunk: The next chunk of output text.

        Returns:
            The portion of (possibly transformed) text safe to emit now.
            Returns ``""`` while content is being withheld/buffered.
        """
        raise NotImplementedError

    @abstractmethod
    def flush(self) -> str:
        """Release any content withheld by prior ``feed()`` calls.

        Returns:
            The remaining (possibly transformed) text to emit at stream end.
        """
        raise NotImplementedError
