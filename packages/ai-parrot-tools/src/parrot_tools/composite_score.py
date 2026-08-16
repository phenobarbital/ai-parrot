"""Relocation shim — ``composite_score`` now lives in ``parrot.finance.tools``.

``CompositeScoreTool`` wraps ``TechnicalAnalysisTool``, which moved to the
**ai-parrot-finance** distribution because it depends on that package's
market-data toolkits. This module followed it.

See ``parrot_tools/technical_analysis.py`` for the full rationale. Delete this
shim once downstream consumers have migrated.
"""

raise ImportError(
    "parrot_tools.composite_score has moved to "
    "parrot.finance.tools.composite_score (ai-parrot-finance).\n"
    "  Install:  pip install ai-parrot-finance\n"
    "  Import:   from parrot.finance.tools.composite_score import "
    "CompositeScoreTool\n"
    "It moved with TechnicalAnalysisTool, which it wraps."
)
