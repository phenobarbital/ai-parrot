"""Curated catalog of supported embedding models.

Single source of truth for all embedding models available in the system.
Add new models here — they become available to APIs and frontends automatically.

Each entry includes a ``use_case`` list so consumers can filter models by
intended workload (similarity, retrieval, clustering, multilingual, code).
"""
from typing import List, Dict, Any


EMBEDDING_MODELS: List[Dict[str, Any]] = [
    # ── HuggingFace / Sentence-Transformers ──────────────────────────────

    # -- General-purpose / Similarity ------------------------------------
    {
        "model": "sentence-transformers/all-mpnet-base-v2",
        "provider": "huggingface",
        "name": "All MPNet Base v2",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["similarity", "clustering"],
        "description": (
            "768-dim high-quality English model. Best overall quality among "
            "sentence-transformers for semantic similarity, clustering, and search."
        ),
    },
    {
        "model": "sentence-transformers/all-MiniLM-L12-v2",
        "provider": "huggingface",
        "name": "MiniLM L12 v2",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["similarity", "clustering"],
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
        "use_case": ["similarity"],
        "description": (
            "384-dim fast English model. Prioritizes speed over accuracy; "
            "ideal for real-time applications with limited resources."
        ),
    },

    # -- Information Retrieval -------------------------------------------
    {
        "model": "thenlper/gte-base",
        "provider": "huggingface",
        "name": "GTE Base",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "similarity"],
        "description": (
            "768-dim general-purpose model, great for information retrieval "
            "and text re-ranking."
        ),
    },
    {
        "model": "sentence-transformers/msmarco-MiniLM-L12-v3",
        "provider": "huggingface",
        "name": "MSMARCO MiniLM L12 v3",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "384-dim model fine-tuned on MS MARCO passage ranking. "
            "Optimized for search and question-answer retrieval."
        ),
    },
    {
        "model": "sentence-transformers/multi-qa-mpnet-base-dot-v1",
        "provider": "huggingface",
        "name": "Multi QA MPNet Base",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "768-dim model trained on 215M question-answer pairs from diverse "
            "sources. Excellent for semantic search and question answering."
        ),
    },
    {
        "model": "sentence-transformers/msmarco-distilbert-base-v4",
        "provider": "huggingface",
        "name": "MSMARCO DistilBERT Base v4",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "768-dim DistilBERT model fine-tuned on MS MARCO passages. "
            "Strong passage retrieval with moderate compute requirements."
        ),
    },
    {
        "model": "sentence-transformers/gtr-t5-large",
        "provider": "huggingface",
        "name": "GTR T5 Large",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "768-dim T5-based retrieval model trained on community QA pairs. "
            "Strong for long document retrieval and passage ranking."
        ),
    },

    # -- E5 family -------------------------------------------------------
    {
        "model": "intfloat/e5-base-v2",
        "provider": "huggingface",
        "name": "E5 Base v2",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "768-dim English model trained with weakly-supervised contrastive "
            "pre-training. Strong for asymmetric retrieval (query vs passage)."
        ),
    },
    {
        "model": "intfloat/e5-large-v2",
        "provider": "huggingface",
        "name": "E5 Large v2",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "1024-dim large English model. Higher quality than e5-base for "
            "retrieval and ranking tasks with asymmetric query-passage pairs."
        ),
    },
    {
        "model": "intfloat/multilingual-e5-base",
        "provider": "huggingface",
        "name": "Multilingual E5 Base",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual"],
        "description": (
            "768-dim multilingual model supporting 100+ languages. "
            "Solid cross-lingual retrieval for asymmetric search tasks."
        ),
    },
    {
        "model": "intfloat/multilingual-e5-large",
        "provider": "huggingface",
        "name": "Multilingual E5 Large",
        "dimension": 1024,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual"],
        "description": (
            "1024-dim high-quality multilingual model (100+ languages). "
            "Best E5 option for cross-lingual retrieval and semantic search."
        ),
    },

    # -- BGE family (BAAI) -----------------------------------------------
    {
        "model": "BAAI/bge-small-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Small EN v1.5",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering"],
        "description": (
            "384-dim compact English model from BAAI. Fast inference with "
            "good quality; suitable for resource-constrained environments."
        ),
    },
    {
        "model": "BAAI/bge-base-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Base EN v1.5",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering"],
        "description": (
            "768-dim English model from BAAI. Competitive with larger models; "
            "strong for retrieval, classification, and clustering."
        ),
    },
    {
        "model": "BAAI/bge-large-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Large EN v1.5",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering"],
        "description": (
            "1024-dim large English model from BAAI. Highest quality among "
            "BGE family; best for accuracy-critical retrieval pipelines."
        ),
    },
    {
        "model": "BAAI/bge-m3",
        "provider": "huggingface",
        "name": "BGE M3",
        "dimension": 1024,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual"],
        "description": (
            "1024-dim multi-granularity multilingual model (100+ languages). "
            "Supports dense, sparse, and ColBERT retrieval in a single model."
        ),
    },

    # -- Multilingual ----------------------------------------------------
    {
        "model": "Alibaba-NLP/gte-multilingual-base",
        "provider": "huggingface",
        "name": "GTE Multilingual Base",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual"],
        "description": (
            "768-dim multilingual model supporting 50+ languages. "
            "Strong for cross-lingual retrieval and semantic search."
        ),
    },
    {
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "provider": "huggingface",
        "name": "Paraphrase Multilingual MiniLM L12",
        "dimension": 384,
        "multilingual": True,
        "language": "multi",
        "use_case": ["similarity", "multilingual"],
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
        "use_case": ["similarity", "multilingual", "clustering"],
        "description": (
            "768-dim high-quality multilingual model (50+ languages). "
            "Best multilingual option for semantic similarity and clustering."
        ),
    },

    # -- Code / Technical ------------------------------------------------
    {
        "model": "jinaai/jina-embeddings-v2-base-code",
        "provider": "huggingface",
        "name": "Jina Embeddings v2 Code",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["code", "retrieval"],
        "description": (
            "768-dim code-specific model with 8192-token context. "
            "Trained on code-text pairs; ideal for code search, "
            "documentation retrieval, and technical content."
        ),
    },
    {
        "model": "jinaai/jina-embeddings-v2-base-en",
        "provider": "huggingface",
        "name": "Jina Embeddings v2 Base EN",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "similarity"],
        "description": (
            "768-dim English model with 8192-token context window. "
            "Handles long documents without chunking; strong for "
            "retrieval and semantic similarity."
        ),
    },

    # -- Matryoshka / Flexible Dimensions --------------------------------
    {
        "model": "nomic-ai/nomic-embed-text-v1.5",
        "provider": "huggingface",
        "name": "Nomic Embed Text v1.5",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering", "similarity"],
        "matryoshka_dimensions": [64, 128, 256, 512, 768],
        "description": (
            "768-dim model with Matryoshka support (64 to 768 dims). "
            "Long 8192-token context. Truncate embeddings to lower "
            "dimensions with minimal quality loss for flexible storage."
        ),
    },
    {
        "model": "mixedbread-ai/mxbai-embed-large-v1",
        "provider": "huggingface",
        "name": "mxbai Embed Large v1",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering"],
        "matryoshka_dimensions": [128, 256, 512, 768, 1024],
        "description": (
            "1024-dim model with Matryoshka support (128 to 1024 dims). "
            "Top-tier retrieval and clustering; truncate to lower "
            "dimensions for efficient storage without retraining."
        ),
    },

    # -- Snowflake Arctic ------------------------------------------------
    {
        "model": "Snowflake/snowflake-arctic-embed-s",
        "provider": "huggingface",
        "name": "Arctic Embed S",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "384-dim compact retrieval model. Fast and efficient; "
            "strong retrieval quality for its size class."
        ),
    },
    {
        "model": "Snowflake/snowflake-arctic-embed-m-v1.5",
        "provider": "huggingface",
        "name": "Arctic Embed M v1.5",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering"],
        "matryoshka_dimensions": [128, 256, 384, 512, 768],
        "description": (
            "768-dim mid-size retrieval model with Matryoshka support "
            "(128 to 768 dims). Good balance between quality and "
            "compute for production retrieval systems."
        ),
    },
    {
        "model": "Snowflake/snowflake-arctic-embed-l",
        "provider": "huggingface",
        "name": "Arctic Embed L",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval"],
        "description": (
            "1024-dim large retrieval model. Top-tier retrieval quality "
            "on MTEB benchmarks; best for accuracy-critical search."
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
        "use_case": ["retrieval", "similarity", "clustering", "multilingual"],
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
        "use_case": ["retrieval", "similarity", "multilingual"],
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
        "use_case": ["retrieval", "similarity", "multilingual"],
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
        "use_case": ["retrieval", "similarity", "multilingual"],
        "description": (
            "3072-dim Google Gemini embedding model. Strong multilingual "
            "support with configurable output dimensionality."
        ),
    },
]


# ── Use-case descriptions (for frontends / documentation) ────────────
USE_CASE_DESCRIPTIONS: Dict[str, str] = {
    "similarity": (
        "Semantic similarity — compare meaning between texts, "
        "find paraphrases, and measure textual relatedness."
    ),
    "retrieval": (
        "Information retrieval — search, question answering, "
        "passage ranking, and asymmetric query-document matching."
    ),
    "clustering": (
        "Clustering and classification — group texts by topic, "
        "detect near-duplicates, and categorize content."
    ),
    "multilingual": (
        "Multilingual and cross-lingual — embed text in multiple "
        "languages into a shared vector space."
    ),
    "code": (
        "Code and technical content — search source code, match "
        "code to documentation, and embed technical text."
    ),
}


def get_embedding_models(
    provider: str = None,
    use_case: str = None,
) -> List[Dict[str, Any]]:
    """Return the curated list of embedding models, optionally filtered.

    Args:
        provider: Filter by provider name (huggingface, openai, google).
                  If None, no provider filtering is applied.
        use_case: Filter by use case (similarity, retrieval, clustering,
                  multilingual, code). If None, no use-case filtering is
                  applied.

    Returns:
        List of embedding model descriptors.
    """
    models = EMBEDDING_MODELS
    if provider:
        models = [m for m in models if m["provider"] == provider]
    if use_case:
        models = [m for m in models if use_case in m.get("use_case", [])]
    return list(models)


def get_use_cases() -> Dict[str, str]:
    """Return available use-case categories and their descriptions."""
    return dict(USE_CASE_DESCRIPTIONS)
