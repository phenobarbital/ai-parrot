"""Curated catalog of supported embedding models.

Single source of truth for all embedding models available in the system.
Add new models here — they become available to APIs and frontends automatically.

Each entry includes a ``use_case`` list so consumers can filter models by
intended workload (similarity, retrieval, clustering, multilingual, code,
qa, long-context, instruct, asymmetric, symmetric).

Schema validation is performed at module import time via ``EmbeddingModelEntry``
(Pydantic v2). The runtime object remains a plain ``list[dict]`` for
JSON-serialisation compatibility with the consumer API.
"""
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, model_validator


# ── Literal type aliases ─────────────────────────────────────────────────────

Metric = Literal["cosine", "dot", "l2"]
Provider = Literal["huggingface", "openai", "google"]
UseCaseTag = Literal[
    "similarity",
    "retrieval",
    "clustering",
    "multilingual",
    "code",
    "qa",
    "long-context",
    "instruct",
    "asymmetric",
    "symmetric",
]


class EmbeddingModelEntry(BaseModel):
    """Validation schema for a single catalog entry.

    Used at module import time to guarantee every entry in
    EMBEDDING_MODELS is well-formed. The runtime exposed object remains
    a plain dict for JSON-serialisation compatibility with the consumer API.

    Attributes:
        model: HuggingFace model identifier or provider model ID.
        provider: One of ``"huggingface"``, ``"openai"``, ``"google"``.
        name: Human-readable display name.
        dimension: Embedding vector dimensionality (must be > 0).
        multilingual: Whether the model supports multiple languages.
        language: Primary language code (``"en"``, ``"multi"``, etc.).
        use_case: List of applicable use-case tags.
        description: Short prose description for operator UIs.
        metric_recommended: Similarity metric the model was trained with.
        requires_prefix: Whether query / passage prefixes are required.
        prefix_query: Prefix prepended to query text (if any).
        prefix_passage: Prefix prepended to passage text (if any).
        normalized_output: Whether the model outputs L2-normalised vectors.
        max_seq_length: Maximum input token length supported by the model.
        hnsw_compatible: Whether pgvector HNSW indexing is supported
            (dimension <= 2000).
        license: SPDX license identifier or ``"proprietary"``.
        recommended_score_threshold: Minimum similarity score below which
            retrieved chunks should be discarded by RAG consumers. Units
            match ``metric_recommended`` — for cosine/L2-normalised models
            the value sits in ``[0.0, 1.0]``; for raw dot product on
            non-normalised models (e.g. ``multi-qa-mpnet-base-dot-v1``)
            it can exceed 1.0. The global default of 0.7 is too aggressive
            for several models — for example ``multi-qa-mpnet-base-cos-v1``
            naturally produces scores in the 0.30-0.55 range.
        recommended_search_limit: Default top-k for vector retrieval that
            consumers should use when the operator has not configured one.
            Heavyweight instruct/long-context models warrant a smaller
            pool than fast lightweight encoders.
        matryoshka_dimensions: Optional list of supported Matryoshka dims.
    """

    model: str
    provider: Provider
    name: str
    dimension: int = Field(gt=0)
    multilingual: bool
    language: str
    use_case: list[UseCaseTag]
    description: str
    # New required fields
    metric_recommended: Metric
    requires_prefix: bool
    prefix_query: Optional[str] = None
    prefix_passage: Optional[str] = None
    normalized_output: bool
    max_seq_length: int = Field(gt=0)
    hnsw_compatible: bool
    license: str
    recommended_score_threshold: float = Field(ge=0.0, le=100.0)
    recommended_search_limit: int = Field(ge=1, le=100)
    # Existing optional field
    matryoshka_dimensions: Optional[list[int]] = None

    @model_validator(mode="after")
    def _prefix_consistency(self) -> "EmbeddingModelEntry":
        """Enforce prefix <-> requires_prefix contract.

        If ``requires_prefix=True``, at least one of ``prefix_query`` /
        ``prefix_passage`` must be non-empty. If ``False``, both must be
        ``None``.

        Returns:
            Self, after validation.

        Raises:
            ValueError: When the prefix fields are inconsistent with
                ``requires_prefix``.
        """
        if self.requires_prefix:
            if not (self.prefix_query or self.prefix_passage):
                raise ValueError(
                    f"{self.model}: requires_prefix=True but both prefixes are None"
                )
        else:
            if self.prefix_query or self.prefix_passage:
                raise ValueError(
                    f"{self.model}: requires_prefix=False but a prefix is set"
                )
        return self

    @model_validator(mode="after")
    def _recommended_threshold_metric_consistency(self) -> "EmbeddingModelEntry":
        """Bound ``recommended_score_threshold`` to the metric's natural range.

        Cosine and L2 distances on L2-normalised outputs always fall within
        ``[0.0, 1.0]``; only raw dot product on non-normalised vectors can
        legitimately exceed ``1.0``. Catching out-of-range values here
        prevents typos like ``70`` (intended as ``0.7``) sneaking into the
        catalog and silently disabling retrieval for cosine models.

        Returns:
            Self, after validation.

        Raises:
            ValueError: When threshold > 1.0 on a cosine/L2 entry.
        """
        if self.metric_recommended in ("cosine", "l2") and self.recommended_score_threshold > 1.0:
            raise ValueError(
                f"{self.model}: recommended_score_threshold="
                f"{self.recommended_score_threshold} > 1.0 is not valid for "
                f"metric_recommended={self.metric_recommended!r}"
            )
        return self

    @model_validator(mode="after")
    def _hnsw_dimension_consistency(self) -> "EmbeddingModelEntry":
        """Enforce hnsw_compatible <-> dimension contract.

        ``hnsw_compatible`` must be ``True`` iff ``dimension <= 2000``
        (pgvector HNSW cap).

        Returns:
            Self, after validation.

        Raises:
            ValueError: When ``hnsw_compatible`` contradicts the dimension.
        """
        expected = self.dimension <= 2000
        if self.hnsw_compatible != expected:
            raise ValueError(
                f"{self.model}: hnsw_compatible={self.hnsw_compatible} but "
                f"dimension={self.dimension} (pgvector HNSW cap is 2000)"
            )
        return self


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
        "use_case": ["similarity", "clustering", "symmetric"],
        "description": (
            "768-dim high-quality English model. Best overall quality among "
            "sentence-transformers for semantic similarity, clustering, and search."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.50,
        "recommended_search_limit": 10,
    },
    {
        "model": "sentence-transformers/all-MiniLM-L12-v2",
        "provider": "huggingface",
        "name": "MiniLM L12 v2",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["similarity", "clustering", "symmetric"],
        "description": (
            "384-dim lightweight English model. Good balance between speed "
            "and quality for general-purpose semantic search."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.45,
        "recommended_search_limit": 10,
    },
    {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "provider": "huggingface",
        "name": "MiniLM L6 v2",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["similarity", "symmetric"],
        "description": (
            "384-dim fast English model. Prioritizes speed over accuracy; "
            "ideal for real-time applications with limited resources."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 256,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.40,
        "recommended_search_limit": 10,
    },

    # -- Information Retrieval -------------------------------------------
    {
        "model": "thenlper/gte-small",
        "provider": "huggingface",
        "name": "GTE Small",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "similarity"],
        "description": (
            "384-dim compact GTE model. Fast inference with solid retrieval "
            "quality; good entry point for resource-constrained environments."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.50,
        "recommended_search_limit": 10,
    },
    {
        "model": "thenlper/gte-base",
        "provider": "huggingface",
        "name": "GTE Base",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "similarity"],
        "description": (
            "768-dim general-purpose English model, great for information "
            "retrieval and text re-ranking. Hard truncation at 512 tokens — "
            "long documents (PDFs, articles) require upstream chunking."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },
    {
        "model": "thenlper/gte-large",
        "provider": "huggingface",
        "name": "GTE Large",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "similarity"],
        "description": (
            "1024-dim large GTE model. Highest quality in the GTE family; "
            "strong for information retrieval, re-ranking, and semantic search. "
            "Hard truncation at 512 tokens — long documents (PDFs, articles) "
            "require upstream chunking."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.50,
        "recommended_search_limit": 10,
    },
    {
        "model": "sentence-transformers/multi-qa-mpnet-base-dot-v1",
        "provider": "huggingface",
        "name": "Multi QA MPNet Base",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "qa", "asymmetric"],
        "description": (
            "768-dim model trained on 215M question-answer pairs from diverse "
            "sources. Excellent for semantic search and question answering."
        ),
        "metric_recommended": "dot",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": False,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 30.0,
        "recommended_search_limit": 10,
    },
    {
        "model": "sentence-transformers/multi-qa-mpnet-base-cos-v1",
        "provider": "huggingface",
        "name": "Multi QA MPNet Base Cosine",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "qa", "asymmetric"],
        "description": (
            "768-dim model trained on 215M question-answer pairs from diverse "
            "sources. Cosine-similarity variant; normalized outputs. "
            "Excellent for semantic search and question answering."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.30,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.50,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },

    # -- E5 family -------------------------------------------------------
    {
        "model": "intfloat/e5-base-v2",
        "provider": "huggingface",
        "name": "E5 Base v2",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "asymmetric"],
        "description": (
            "768-dim English model trained with weakly-supervised contrastive "
            "pre-training. Strong for asymmetric retrieval (query vs passage)."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "query: ",
        "prefix_passage": "passage: ",
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.75,
        "recommended_search_limit": 10,
    },
    {
        "model": "intfloat/e5-large-v2",
        "provider": "huggingface",
        "name": "E5 Large v2",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "asymmetric"],
        "description": (
            "1024-dim large English model. Higher quality than e5-base for "
            "retrieval and ranking tasks with asymmetric query-passage pairs."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "query: ",
        "prefix_passage": "passage: ",
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.75,
        "recommended_search_limit": 10,
    },
    {
        "model": "intfloat/multilingual-e5-base",
        "provider": "huggingface",
        "name": "Multilingual E5 Base",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual", "asymmetric"],
        "description": (
            "768-dim multilingual model supporting 100+ languages. "
            "Solid cross-lingual retrieval for asymmetric search tasks."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "query: ",
        "prefix_passage": "passage: ",
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.75,
        "recommended_search_limit": 10,
    },
    {
        "model": "intfloat/multilingual-e5-large",
        "provider": "huggingface",
        "name": "Multilingual E5 Large",
        "dimension": 1024,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual", "asymmetric"],
        "description": (
            "1024-dim high-quality multilingual model (100+ languages). "
            "Best E5 option for cross-lingual retrieval and semantic search."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "query: ",
        "prefix_passage": "passage: ",
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.75,
        "recommended_search_limit": 10,
    },

    # -- BGE family (BAAI) -----------------------------------------------
    {
        "model": "BAAI/bge-small-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Small EN v1.5",
        "dimension": 384,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering", "asymmetric"],
        "description": (
            "384-dim compact English model from BAAI. Fast inference with "
            "good quality; suitable for resource-constrained environments."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "Represent this sentence for searching relevant passages: ",
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.65,
        "recommended_search_limit": 10,
    },
    {
        "model": "BAAI/bge-base-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Base EN v1.5",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering", "asymmetric"],
        "description": (
            "768-dim English model from BAAI. Competitive with larger models; "
            "strong for retrieval, classification, and clustering."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "Represent this sentence for searching relevant passages: ",
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.65,
        "recommended_search_limit": 10,
    },
    {
        "model": "BAAI/bge-large-en-v1.5",
        "provider": "huggingface",
        "name": "BGE Large EN v1.5",
        "dimension": 1024,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering", "asymmetric"],
        "description": (
            "1024-dim large English model from BAAI. Highest quality among "
            "BGE family; best for accuracy-critical retrieval pipelines."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "Represent this sentence for searching relevant passages: ",
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.65,
        "recommended_search_limit": 10,
    },
    {
        "model": "BAAI/bge-m3",
        "provider": "huggingface",
        "name": "BGE M3",
        "dimension": 1024,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual", "long-context"],
        "description": (
            "1024-dim multi-granularity multilingual model (100+ languages). "
            "Supports dense, sparse, and ColBERT retrieval in a single model."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 8192,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },

    # -- Multilingual ----------------------------------------------------
    {
        "model": "Alibaba-NLP/gte-multilingual-base",
        "provider": "huggingface",
        "name": "GTE Multilingual Base",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "multilingual", "long-context"],
        "description": (
            "768-dim multilingual model supporting 50+ languages. "
            "Strong for cross-lingual retrieval and semantic search."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 8192,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },
    {
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "provider": "huggingface",
        "name": "Paraphrase Multilingual MiniLM L12",
        "dimension": 384,
        "multilingual": True,
        "language": "multi",
        "use_case": ["similarity", "multilingual", "symmetric"],
        "description": (
            "384-dim lightweight multilingual model (50+ languages). "
            "Good for paraphrase detection and cross-lingual similarity."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 128,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.40,
        "recommended_search_limit": 10,
    },
    {
        "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "provider": "huggingface",
        "name": "Paraphrase Multilingual MPNet",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "use_case": ["similarity", "multilingual", "clustering", "symmetric"],
        "description": (
            "768-dim high-quality multilingual model (50+ languages). "
            "Best multilingual option for semantic similarity and clustering."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 128,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.45,
        "recommended_search_limit": 10,
    },

    # -- Code / Technical ------------------------------------------------
    {
        "model": "jinaai/jina-embeddings-v2-base-code",
        "provider": "huggingface",
        "name": "Jina Embeddings v2 Code",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["code", "retrieval", "long-context"],
        "description": (
            "768-dim code-specific model with 8192-token context. "
            "Trained on code-text pairs; ideal for code search, "
            "documentation retrieval, and technical content."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 8192,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },
    {
        "model": "jinaai/jina-embeddings-v2-base-en",
        "provider": "huggingface",
        "name": "Jina Embeddings v2 Base EN",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "similarity", "long-context"],
        "description": (
            "768-dim English model with 8192-token context window. "
            "Handles long documents without chunking; strong for "
            "retrieval and semantic similarity."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 8192,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },

    # -- Jina v3 (prefix-requiring) --------------------------------------
    {
        "model": "jinaai/jina-embeddings-v3",
        "provider": "huggingface",
        "name": "Jina Embeddings v3",
        "dimension": 1024,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "long-context", "asymmetric", "multilingual"],
        "description": (
            "1024-dim multilingual model with 8192-token context. "
            "Supports task-specific instruction prefixes for asymmetric "
            "retrieval. Strong multilingual performance."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "Represent the query for retrieving evidence documents: ",
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 8192,
        "hnsw_compatible": True,
        "license": "cc-by-nc-4.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },

    # -- Matryoshka / Flexible Dimensions --------------------------------
    {
        "model": "nomic-ai/nomic-embed-text-v1.5",
        "provider": "huggingface",
        "name": "Nomic Embed Text v1.5",
        "dimension": 768,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "clustering", "similarity", "long-context", "asymmetric"],
        "matryoshka_dimensions": [64, 128, 256, 512, 768],
        "description": (
            "768-dim model with Matryoshka support (64 to 768 dims) and "
            "8192-token context. Requires task-specific instruction prefixes: "
            "'search_query: ' for queries and 'search_document: ' for passages "
            "in RAG/retrieval pipelines. Also supports 'clustering: ' for "
            "clustering tasks and 'classification: ' for classification "
            "(these alternate prefixes must be applied manually). "
            "Uses trust_remote_code=True. Truncate embeddings to lower "
            "dimensions with minimal quality loss for flexible storage."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": "search_query: ",
        "prefix_passage": "search_document: ",
        "normalized_output": True,
        "max_seq_length": 8192,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },

    # -- Gemma Embeddings ------------------------------------------------
    {
        "model": "google/embeddinggemma-300m",
        "provider": "huggingface",
        "name": "EmbeddingGemma 300M",
        "dimension": 768,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "similarity", "clustering", "multilingual"],
        "matryoshka_dimensions": [128, 256, 512, 768],
        "description": (
            "768-dim lightweight Gemma-based model (300M params, 100+ languages). "
            "Matryoshka support (128 to 768 dims). Designed for on-device and "
            "resource-constrained deployment; strong for retrieval, clustering, "
            "and multilingual semantic search."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "gemma",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 512,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.60,
        "recommended_search_limit": 10,
    },

    # -- Instruct-Tuned --------------------------------------------------
    {
        "model": "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "provider": "huggingface",
        "name": "GTE Qwen2 1.5B Instruct",
        "dimension": 1536,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "qa", "instruct", "asymmetric", "long-context"],
        "description": (
            "1536-dim instruction-tuned retrieval model based on Qwen2. "
            "Requires task-specific instruction prefix on queries. "
            "32768-token context; strong for long-document RAG pipelines."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": (
            "Instruct: Given a web search query, retrieve relevant passages "
            "that answer the query\nQuery: "
        ),
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 32768,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 5,
    },
    {
        "model": "intfloat/e5-mistral-7b-instruct",
        "provider": "huggingface",
        "name": "E5 Mistral 7B Instruct",
        "dimension": 4096,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "instruct", "asymmetric", "long-context"],
        "description": (
            "4096-dim instruction-tuned retrieval model based on Mistral-7B. "
            "Requires task-specific instruction prefix on queries. "
            "4096-token context. Cannot be HNSW-indexed in pgvector (>2000d)."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": (
            "Instruct: Given a web search query, retrieve relevant passages "
            "that answer the query\nQuery: "
        ),
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 4096,
        "hnsw_compatible": False,
        "license": "mit",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 5,
    },

    # -- High-Dimension / Specialized ------------------------------------
    {
        "model": "nvidia/NV-Embed-v2",
        "provider": "huggingface",
        "name": "NV-Embed v2",
        "dimension": 4096,
        "multilingual": False,
        "language": "en",
        "use_case": ["retrieval", "qa", "instruct", "asymmetric", "long-context"],
        "description": (
            "4096-dim state-of-the-art retrieval model from NVIDIA. "
            "Requires task-specific instruction prefix on queries. "
            "32768-token context. Cannot be HNSW-indexed in pgvector (>2000d). "
            "License: CC-BY-NC-4.0 (non-commercial use only)."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": (
            "Instruct: Given a question, retrieve passages that answer the "
            "question\nQuery: "
        ),
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 32768,
        "hnsw_compatible": False,
        "license": "cc-by-nc-4.0",
        "recommended_score_threshold": 0.60,
        "recommended_search_limit": 5,
    },

    # -- Microsoft Harrier (Instruct, multilingual) ----------------------
    {
        "model": "microsoft/harrier-oss-v1-0.6b",
        "provider": "huggingface",
        "name": "Harrier-OSS v1 0.6B",
        "dimension": 1024,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "instruct", "asymmetric", "multilingual", "long-context"],
        "description": (
            "1024-dim 0.6B-parameter multilingual retrieval model from "
            "Microsoft (94 languages). Decoder-only with last-token pooling "
            "and 32K-token context. Instruction-tuned: queries require an "
            "'Instruct: ...\\nQuery: ' template; documents are encoded "
            "without prefix. MTEB v2 score 69.0. HNSW-compatible in "
            "pgvector; MIT license."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": True,
        "prefix_query": (
            "Instruct: Given a web search query, retrieve relevant passages "
            "that answer the query\nQuery: "
        ),
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 32768,
        "hnsw_compatible": True,
        "license": "mit",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },

    # -- Domain-Specialized (Vertical) -----------------------------------
    {
        "model": "Octen/Octen-Embedding-0.6B",
        "provider": "huggingface",
        "name": "Octen Embedding 0.6B",
        "dimension": 1024,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "long-context", "multilingual"],
        "description": (
            "1024-dim 0.6B-parameter retrieval model fine-tuned (LoRA) on top "
            "of Qwen3-Embedding-0.6B for vertical domains: legal, finance, "
            "healthcare, and code. 32K-token context — strong for long "
            "policies, contracts, and regulatory docs. RTEB public score "
            "0.7241. HNSW-compatible in pgvector and lightweight enough for "
            "CPU or modest GPU deployment; good default when domain expertise "
            "on legal/fiscal corpora matters."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 32768,
        "hnsw_compatible": True,
        "license": "apache-2.0",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },

    # ── OpenAI ───────────────────────────────────────────────────────────
    {
        "model": "text-embedding-3-large",
        "provider": "openai",
        "name": "Text Embedding 3 Large",
        "dimension": 3072,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "similarity", "clustering", "multilingual", "long-context"],
        "description": (
            "3072-dim flagship OpenAI model. Highest quality for search, "
            "clustering, and classification. Supports dimension reduction."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 8191,
        "hnsw_compatible": False,
        "license": "proprietary",
        "recommended_score_threshold": 0.55,
        "recommended_search_limit": 10,
    },
    {
        "model": "text-embedding-3-small",
        "provider": "openai",
        "name": "Text Embedding 3 Small",
        "dimension": 1536,
        "multilingual": True,
        "language": "multi",
        "use_case": ["retrieval", "similarity", "multilingual", "long-context"],
        "description": (
            "1536-dim cost-efficient OpenAI model. Good quality at lower "
            "cost and latency; supports dimension reduction."
        ),
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 8191,
        "hnsw_compatible": True,
        "license": "proprietary",
        "recommended_score_threshold": 0.50,
        "recommended_search_limit": 10,
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
        "metric_recommended": "cosine",
        "requires_prefix": False,
        "prefix_query": None,
        "prefix_passage": None,
        "normalized_output": True,
        "max_seq_length": 2048,
        "hnsw_compatible": False,
        "license": "proprietary",
        "recommended_score_threshold": 0.60,
        "recommended_search_limit": 10,
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
    "qa": (
        "Question-answering retrieval — models trained or fine-tuned "
        "specifically on Q&A pairs (e.g. multi-qa-mpnet, NV-Embed-v2)."
    ),
    "long-context": (
        "Long-context embedding — models that natively handle "
        "≥4096-token inputs (e.g. bge-m3, jina-embeddings-v3)."
    ),
    "instruct": (
        "Instruction-tuned retrievers — require a task-specific "
        "instruction template prepended to queries (e.g. gte-Qwen2-instruct, "
        "e5-mistral-7b-instruct, NV-Embed-v2)."
    ),
    "asymmetric": (
        "Asymmetric retrieval — query and passage are encoded with "
        "different prompts/prefixes (e.g. E5, BGE-EN-v1.5, Jina v3)."
    ),
    "symmetric": (
        "Symmetric similarity — query and passage encoded the same way "
        "(e.g. paraphrase-multilingual-mpnet, all-mpnet-base-v2)."
    ),
}


def get_embedding_models(
    provider: Optional[str] = None,
    use_case: Optional[str] = None,
    metric: Optional[str] = None,
    max_dims: Optional[int] = None,
    hnsw_compatible: Optional[bool] = None,
    requires_prefix: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Return the curated list of embedding models, optionally filtered.

    All active filters compose with AND semantics — only entries satisfying
    every non-``None`` filter are returned.

    Args:
        provider: Filter by provider name (``"huggingface"``, ``"openai"``,
            ``"google"``). If ``None``, no provider filtering is applied.
        use_case: Filter by use case tag (``"similarity"``, ``"retrieval"``,
            ``"clustering"``, ``"multilingual"``, ``"code"``, ``"qa"``,
            ``"long-context"``, ``"instruct"``, ``"asymmetric"``,
            ``"symmetric"``). If ``None``, no use-case filtering is applied.
        metric: Filter by recommended similarity metric (``"cosine"``,
            ``"dot"``, ``"l2"``). If ``None``, no metric filtering is applied.
        max_dims: Keep only models whose ``dimension <= max_dims``.
            If ``None``, no dimension cap is applied.
        hnsw_compatible: If ``True``, return only models whose
            ``hnsw_compatible`` flag is ``True`` (dimension <= 2000 for
            pgvector HNSW). If ``False``, return only non-HNSW-compatible
            models. If ``None``, no filtering on this field.
        requires_prefix: If ``True``, return only prefix-requiring models.
            If ``False``, return only models that do not require prefixes.
            If ``None``, no filtering on this field.

    Returns:
        List of embedding model descriptor dicts satisfying all active filters.
    """
    models: List[Dict[str, Any]] = EMBEDDING_MODELS
    if provider is not None:
        models = [m for m in models if m["provider"] == provider]
    if use_case is not None:
        models = [m for m in models if use_case in m.get("use_case", [])]
    if metric is not None:
        models = [m for m in models if m["metric_recommended"] == metric]
    if max_dims is not None:
        models = [m for m in models if m["dimension"] <= max_dims]
    if hnsw_compatible is not None:
        models = [m for m in models if m["hnsw_compatible"] is hnsw_compatible]
    if requires_prefix is not None:
        models = [m for m in models if m["requires_prefix"] is requires_prefix]
    return list(models)


def get_use_cases() -> Dict[str, str]:
    """Return available use-case categories and their descriptions."""
    return dict(USE_CASE_DESCRIPTIONS)


def get_model_recommendations(model_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return per-model retrieval recommendations from the catalog.

    Provides default ``score_threshold`` and ``search_limit`` values that
    consumers (chatbots, RAG pipelines, vector-store handlers) should use
    when the operator has not configured them explicitly. The global
    fallback of ``0.7`` is too aggressive for several models — e.g.
    ``multi-qa-mpnet-base-cos-v1`` produces scores in the 0.30-0.55 range
    and would silently return empty result sets.

    Args:
        model_name: HuggingFace model identifier or provider model ID.
            ``None`` or unknown names return ``None``.

    Returns:
        A dict with keys ``recommended_score_threshold`` (float) and
        ``recommended_search_limit`` (int) when ``model_name`` matches a
        catalog entry; ``None`` otherwise.
    """
    if not model_name:
        return None
    for entry in EMBEDDING_MODELS:
        if entry["model"] == model_name:
            return {
                "recommended_score_threshold": entry["recommended_score_threshold"],
                "recommended_search_limit": entry["recommended_search_limit"],
            }
    return None


# ── Import-time validation ────────────────────────────────────────────
# Validate every entry against the Pydantic schema. If any entry is
# malformed, the module fails to import — catching catalog regressions
# at the earliest possible point. The Pydantic instances are discarded
# immediately after validation; the runtime list stays plain dicts.
for _entry in EMBEDDING_MODELS:
    EmbeddingModelEntry.model_validate(_entry)
# Clean up the loop variable from the module namespace.
# Guard against an empty EMBEDDING_MODELS list (e.g. in stripped test fixtures).
try:
    del _entry
except NameError:
    pass
