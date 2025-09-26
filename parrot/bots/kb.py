from typing import Any, Dict, List, Tuple
import json
from pydantic import BaseModel, Field
from ..stores.kb.abstract import AbstractKnowledgeBase
from ..stores.kb.prompt import SELECTION_PROMPT
from ..clients.base import AbstractClient


class KBSelected(BaseModel):
    """Model for a selected KB."""
    name: str = Field(..., description="Name of the selected KB")
    reason: str = Field(..., description="Reason for selection")
    confidence: float = Field(..., description="Confidence score for selection")


class KBOutput(BaseModel):
    """Structured output model for KB selection."""
    selected_kbs: List[KBSelected] = Field(
        ..., description="List of selected KBs with name, reason, and confidence"
    )
    reasoning: str = Field(..., description="Overall reasoning for selections")


class KBSelector:
    """Add KB selection capabilities to a bot."""
    def __init__(
        self,
        llm_client: AbstractClient,
        min_confidence: float = 0.6,
        kbs: List[AbstractKnowledgeBase] = None,
        **kwargs: Any
    ):
        # TODO: migrate to faster LLM (e.g. Groq)
        self.llm: AbstractClient = llm_client
        self.min_confidence = min_confidence
        self.knowledge_bases: List[AbstractKnowledgeBase] = kbs or []
        self._cache = {}
        self.selection_prompt = kwargs.get('selection_prompt', SELECTION_PROMPT)
        # Format KB descriptions
        self.kb_descriptions = self._get_kb_descriptions()
        super().__init__(**kwargs)

    def _get_kb_descriptions(self) -> str:
        """Get list of KB descriptions."""
        descriptions = []
        for i, kb in enumerate(self.knowledge_bases, 1):
            if isinstance(kb, AbstractKnowledgeBase):
                descriptions.append(f"{i}. {kb.name}: {kb.description}")
        return "\n".join(descriptions)

    async def select_kbs(
        self,
        question: str,
        available_kbs: List[Dict[str, str]]
    ) -> KBOutput:
        """
        Select relevant KBs using LLM reasoning.

        Args:
            question: User's question
            available_kbs: List of dicts with 'name' and 'description'
            use_cache: Whether to use cached selections

        Returns:
            List of tuples (kb_name, confidence)
        """
        # Check cache
        cache_key = self._get_cache_key(question)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Build prompt
        prompt = self.selection_prompt.format(
            kb_descriptions=self.kb_descriptions,
            question=question
        )

        try:
            async with self.llm:
                # Call LLM for selection
                response = await self.llm.ask(
                    prompt=prompt,
                    temperature=0.3,
                    max_tokens=4096,
                    structured_output=KBOutput,
                    stateless=True,
                    use_tools=False,
                )
                # Parse response
                selections = response.output
                if isinstance(selections, str):
                    if "```json" in selections:
                        json_str = selections.split("```json")[1].split("```")[0]
                    elif "```" in selections:
                        json_str = selections.split("```")[1].split("```")[0]
                    else:
                        json_str = selections
                    selections = json.loads(json_str)

            # Cache result
            self._cache[cache_key] = selections
            # Limit cache size
            if len(self._cache) > 100:
                self._cache.pop(
                    next(iter(self._cache))
                )

            return selections

        except Exception:
            # Fallback to rule-based selection
            return self._fallback_selection(question, available_kbs)

    def _format_kb_list(self, kbs: List[Dict]) -> str:
        """Format KB list for prompt."""
        lines = []
        for i, kb in enumerate(kbs, 1):
            if isinstance(kb, AbstractKnowledgeBase):
                kb = {
                    "name": kb.name,
                    "description": kb.description
                }
            lines.append(
                f"{i}. {kb['name']}: {kb['description']}"
            )
        return "\n".join(lines)

    def _fallback_selection(
        self,
        question: str,
        available_kbs: List[Dict]
    ) -> List[Tuple[str, float]]:
        """Rule-based fallback selection."""
        question_lower = question.lower()
        selections = []

        for kb in available_kbs:
            confidence = 0.0
            kb_name = kb['name']

            # Check for keyword matches
            keywords = kb.get('keywords', [])
            for keyword in keywords:
                if keyword.lower() in question_lower:
                    confidence = max(confidence, 0.8)

            # Check for pattern matches
            patterns = kb.get('activation_patterns', [])
            for pattern in patterns:
                if pattern.lower() in question_lower:
                    confidence = max(confidence, 0.9)

            if confidence >= self.min_confidence:
                selections.append((kb_name, confidence))

        return selections

    def _get_cache_key(self, question: str) -> str:
        """Generate cache key for question."""
        # Simple normalization for caching
        return question.lower().strip()[:100]
