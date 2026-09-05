"""Meta Model API data models for AI-Parrot.

Model enums and capability constants for Meta Model API
(https://api.meta.ai/v1). No Pydantic wrappers are needed — Meta's
Chat Completions response shape matches OpenAI's and is already covered
by the existing AIMessage / CompletionUsage models.

.. warning::
    Contributor-tier models (see ``CONTRIBUTOR_MODELS``) grant Meta
    permission to train on prompts and completions. They MUST NEVER be
    used as a library default — reserve them for synthetic end-to-end
    test prompts only.
"""

from enum import Enum


class MetaModel(str, Enum):
    """Meta Model API model identifiers.

    String-valued enum so members interchange with raw model strings
    in OpenAI SDK calls (e.g. ``model=MetaModel.MUSE_SPARK_1_3.value``
    or simply ``model=MetaModel.MUSE_SPARK_1_3`` since the class
    inherits from ``str``).

    Verified live against ``GET /v1/models`` on 2026-09-04 (finding
    F013 of the FEAT-526 research audit). Do not add, rename, or
    "correct" any of these ids without a fresh live verification.
    """

    MUSE_SPARK_1_3 = "muse-spark-1.3"
    MUSE_SPARK_1_3_CONTRIBUTOR = "muse-spark-1.3-contributor"
    MUSE_SPARK_1_2 = "muse-spark-1.2"
    MUSE_SPARK_1_2_CONTRIBUTOR = "muse-spark-1.2-contributor"
    MUSE_SPARK_1_1 = "muse-spark-1.1"  # NOTE: no contributor variant
    MUSE_IMAGE_1_0 = "muse-image-1.0"  # reserved — out of scope (Non-Goal)
    MUSE_VOICE_TRANSCRIBE_1_0 = "muse-voice-transcribe-1.0"  # reserved — out of scope


# Models on the "contributor" tier — a lower price in exchange for granting
# Meta permission to train on your prompts and completions. Never use one
# of these as a default anywhere in library code; synthetic e2e test
# prompts only.
CONTRIBUTOR_MODELS: frozenset[str] = frozenset(
    {
        MetaModel.MUSE_SPARK_1_3_CONTRIBUTOR.value,
        MetaModel.MUSE_SPARK_1_2_CONTRIBUTOR.value,
    }
)

# Muse Spark (text/agentic/coding) chat models — both Standard and
# Contributor tiers.
SPARK_MODELS: frozenset[str] = frozenset(
    {
        MetaModel.MUSE_SPARK_1_3.value,
        MetaModel.MUSE_SPARK_1_3_CONTRIBUTOR.value,
        MetaModel.MUSE_SPARK_1_2.value,
        MetaModel.MUSE_SPARK_1_2_CONTRIBUTOR.value,
        MetaModel.MUSE_SPARK_1_1.value,
    }
)

# Muse Image — reserved, out of scope (Non-Goal). No endpoint work exists
# for this model; the enum member is a placeholder only.
IMAGE_MODELS: frozenset[str] = frozenset(
    {
        MetaModel.MUSE_IMAGE_1_0.value,
    }
)

# Muse Voice Transcribe — reserved, out of scope (Non-Goal). No endpoint
# work exists for this model; the enum member is a placeholder only.
TRANSCRIBE_MODELS: frozenset[str] = frozenset(
    {
        MetaModel.MUSE_VOICE_TRANSCRIBE_1_0.value,
    }
)

# Context window (in tokens), uniform across all Muse Spark models.
CONTEXT_WINDOW: int = 1_048_576
