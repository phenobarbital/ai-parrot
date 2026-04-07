"""Curated catalog of supported embedding models.

Single source of truth for all embedding models available in the system.
Add new models here — they become available to APIs and frontends automatically.
"""
from typing import List, Dict, Any


EMBEDDING_MODELS: List[Dict[str, Any]] = [
    # ── HuggingFace / Sentence-Transformers ──────────────────────────────
    {
        "model": "thenlper/gte-base",
        "provider": "huggingface",
        "name": "GTE Base",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "description": (
            "768-dim general-purpose model, great for information retrieval "
            "and text re-ranking."
        ),
    },
    {
        "model": "Alibaba-NLP/gte-multilingual-base",
        "provider": "huggingface",
        "name": "GTE Multilingual Base",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "description": (
            "768-dim multilingual model supporting 50+ languages. "
            "Strong for cross-lingual retrieval and semantic search."
        ),
    },
    {
        "model": "sentence-transformers/all-mpnet-base-v2",
        "provider": "huggingface",
        "name": "All MPNet Base v2",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "description": (
            "768-dim high-quality English model. Best overall quality among "
            "sentence-transformers for semantic similarity and search."
        ),
    },
    {
        "model": "sentence-transformers/all-MiniLM-L12-v2",
        "provider": "huggingface",
        "name": "MiniLM L12 v2",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "description": (
            "384-dim lightweight English model. Good balance between speed "
            "and quality for general-purpose semantic search."
        ),
    },
    {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "provider": "huggingface",
        "name": "MiniLM L6 v2",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "description": (
            "384-dim fast English model. Prioritizes speed over accuracy; "
            "ideal for real-time applications with limited resources."
        ),
    },
    {
        "model": "sentence-transformers/msmarco-MiniLM-L12-v3",
        "provider": "huggingface",
        "name": "MSMARCO MiniLM L12 v3",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "description": (
            "384-dim model fine-tuned on MS MARCO passage ranking. "
            "Optimized for search and question-answer retrieval."
        ),
    },
    {
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "provider": "huggingface",
        "name": "Paraphrase Multilingual MiniLM L12",
        "dimension": 384,
        "multilingual": True,
        "language": "multi",
        "description": (
            "384-dim lightweight multilingual model (50+ languages). "
            "Good for paraphrase detection and cross-lingual similarity."
        ),
    },
    {
        "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "provider": "huggingface",
        "name": "Paraphrase Multilingual MPNet",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "description": (
            "768-dim high-quality multilingual model (50+ languages). "
            "Best multilingual option for semantic similarity and clustering."
        ),
    },
    {
        "model": "intfloat/e5-base-v2",
        "provider": "huggingface",
        "name": "E5 Base v2",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "description": (
            "768-dim English model trained with weakly-supervised contrastive "
            "pre-training. Strong for asymmetric retrieval (query vs passage)."
        ),
    },
    {
        "model": "BAAI/bge-base-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Base EN v1.5",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "description": (
            "768-dim English model from BAAI. Competitive with larger models; "
            "strong for retrieval, classification, and clustering."
        ),
    },
    {
        "model": "BAAI/bge-small-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Small EN v1.5",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "description": (
            "384-dim compact English model from BAAI. Fast inference with "
            "good quality; suitable for resource-constrained environments."
        ),
    },
    {
        "model": "BAAI/bge-large-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Large EN v1.5",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "description": (
            "1024-dim large English model from BAAI. Highest quality among "
            "BGE family; best for accuracy-critical retrieval pipelines."
        ),
    },
    # ── OpenAI ───────────────────────────────────────────────────────────
    {
        "model": "text-embedding-3-large",
        "provider": "openai",
        "name": "Text Embedding 3 Large",
        "dimension": 3072,
        "multilingual": True,
        "language": "multi",
        "description": (
            "3072-dim flagship OpenAI model. Highest quality for search, "
            "clustering, and classification. Supports dimension reduction."
        ),
    },
    {
        "model": "text-embedding-3-small",
        "provider": "openai",
        "name": "Text Embedding 3 Small",
        "dimension": 1536,
        "multilingual": True,
        "language": "multi",
        "description": (
            "1536-dim cost-efficient OpenAI model. Good quality at lower "
            "cost and latency; supports dimension reduction."
        ),
    },
    {
        "model": "text-embedding-ada-002",
        "provider": "openai",
        "name": "Text Embedding Ada 002",
        "dimension": 1536,
        "multilingual": True,
        "language": "multi",
        "description": (
            "1536-dim legacy OpenAI model. Widely adopted and battle-tested; "
            "consider text-embedding-3-small as a newer alternative."
        ),
    },
    # ── Google ───────────────────────────────────────────────────────────
    {
        "model": "gemini-embedding-001",
        "provider": "google",
        "name": "Gemini Embedding 001",
        "dimension": 3072,
        "multilingual": True,
        "language": "multi",
        "description": (
            "3072-dim Google Gemini embedding model. Strong multilingual "
            "support with configurable output dimensionality."
        ),
    },
]


def get_embedding_models(provider: str = None) -> List[Dict[str, Any]]:
    """Return the curated list of embedding models, optionally filtered by provider.

    Args:
        provider: Filter by provider name (huggingface, openai, google).
                  If None, returns all models.

    Returns:
        List of embedding model descriptors.
    """
    if provider:
        return [m for m in EMBEDDING_MODELS if m["provider"] == provider]
    return list(EMBEDDING_MODELS)
