"""Shared fixtures for parrot.metrics tests (FEAT-756)."""

from __future__ import annotations

import re
from datetime import date
from typing import Sequence

import numpy as np
import pytest

from parrot.metrics.models import MetricDefinition


@pytest.fixture
def frozen_today() -> date:
    """Return a fixed date for metric-period tests."""
    return date(2026, 10, 27)


@pytest.fixture
def worked_hours_def() -> MetricDefinition:
    """Return a query-slug worked-hours KPI definition."""
    return MetricDefinition.model_validate(
        {
            "id": "worked_hours",
            "name": "Worked Hours",
            "aliases": ["hours worked", "horas trabajadas", "worked hrs"],
            "example_phrases": ["show me worked hours this month", "cuántas horas trabajamos este mes"],
            "unit": "h",
            "format": "number",
            "higher_is_better": None,
            "program": "flex",
            "dimensions": [
                {"name": "cost center", "column": "cost_center", "aliases": ["cc"]},
                {"name": "pay code", "column": "pay_code"},
            ],
            "time": {
                "grain": "month",
                "default_period": "this_month",
                "series_grain": "day",
                "binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"},
            },
            "comparison": {"mode": "previous_period"},
            "default_shape": {"component": "KPICard", "value_column": "hours", "aggregate": "sum"},
            "source": {"kind": "query_slug", "slug": "flex_hours"},
        }
    )


class _BagOfWordsEncoder:
    """Deterministic normalized bag-of-words encoder for router tests."""

    dim = 256

    def encode(self, texts: Sequence[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Encode text values after removing e5 query and passage prefixes."""
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for index, text in enumerate(texts):
            text = re.sub(r"^(query|passage):\s*", "", text.lower())
            for token in re.findall(r"\w+", text):
                out[index, hash(token) % self.dim] += 1.0
            norm = np.linalg.norm(out[index])
            if norm:
                out[index] /= norm
        return out


@pytest.fixture
def stub_encoder() -> _BagOfWordsEncoder:
    """Return an encoder suitable for ``EmbeddingIntentRouter(..., encoder=...)``."""
    return _BagOfWordsEncoder()
