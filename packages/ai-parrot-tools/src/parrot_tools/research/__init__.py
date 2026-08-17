"""
Research tools for AI-Parrot agents (FEAT-426).

Direct, structured access to authoritative open-data and academic-research
sources — ``OpenDataToolkit``, ``AcademicResearchToolkit``, and the
cross-category ``ResearchRouter`` dispatch tool.

These imports are side-effect free: every optional third-party library
(``wbgapi``, ``sdmx1``, ``habanero``, ``biopython``, ``arxiv``) is guarded
by ``try/except ImportError`` inside its owning module, so importing this
package works even without the ``research`` extra installed — the guarded
methods simply report a clear, actionable error instead of raising.
"""
from .academic import AcademicResearchToolkit
from .base import BaseResearchToolkit
from .models import Citation, DatasetResult, IndicatorValue, PaperResult, ResearchResult
from .open_data import OpenDataToolkit
from .router import ResearchRouter, ResearchRouterArgs

__all__ = [
    "AcademicResearchToolkit",
    "BaseResearchToolkit",
    "Citation",
    "DatasetResult",
    "IndicatorValue",
    "OpenDataToolkit",
    "PaperResult",
    "ResearchResult",
    "ResearchRouter",
    "ResearchRouterArgs",
]
