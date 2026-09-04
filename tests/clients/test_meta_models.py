"""Unit tests for the Meta Model API catalog (parrot.clients.meta.models).

Pure data tests — no I/O, no network. Model ids were verified live
against ``GET /v1/models`` on 2026-09-04 (FEAT-526 research finding F013).
"""

import pytest

from parrot.clients.meta import (
    MetaModel,
    CONTRIBUTOR_MODELS,
    SPARK_MODELS,
    CONTEXT_WINDOW,
)
from parrot.clients.meta.models import MetaModel as MetaModelDirect

LIVE_CATALOG = {
    "muse-spark-1.3",
    "muse-spark-1.3-contributor",
    "muse-spark-1.2",
    "muse-spark-1.2-contributor",
    "muse-spark-1.1",
    "muse-image-1.0",
    "muse-voice-transcribe-1.0",
}


class TestMetaModel:
    def test_matches_live_catalog_exactly(self):
        assert {m.value for m in MetaModel} == LIVE_CATALOG

    def test_str_enum_interchanges_with_raw_string(self):
        assert MetaModel.MUSE_SPARK_1_3 == "muse-spark-1.3"

    def test_muse_spark_1_1_has_no_contributor_variant(self):
        assert "muse-spark-1.1-contributor" not in {m.value for m in MetaModel}

    def test_contributor_frozenset(self):
        assert CONTRIBUTOR_MODELS == {
            "muse-spark-1.3-contributor",
            "muse-spark-1.2-contributor",
        }

    def test_spark_models_frozenset(self):
        assert SPARK_MODELS == {
            "muse-spark-1.3",
            "muse-spark-1.3-contributor",
            "muse-spark-1.2",
            "muse-spark-1.2-contributor",
            "muse-spark-1.1",
        }

    def test_context_window(self):
        assert CONTEXT_WINDOW == 1_048_576

    def test_package_init_reexports(self):
        assert MetaModelDirect is MetaModel

    def test_no_enum_left_under_parrot_models(self):
        with pytest.raises(ImportError):
            __import__("parrot.models.meta")
