"""Relocation shim — ``technical_analysis`` now lives in ``parrot.finance.tools``.

``TechnicalAnalysisTool`` builds its OHLCV feeds from three market-data toolkits
(Alpaca, CoinGecko, CryptoQuant) that are owned by the **ai-parrot-finance**
distribution, not by ai-parrot-tools. While this module lived here it imported
them as ``.alpaca`` / ``.coingecko`` / ``.cryptoquant`` — modules that never
existed in ``parrot_tools`` — so importing it always raised a bare
``ModuleNotFoundError: No module named 'parrot_tools.alpaca'``, taking
``parrot_tools.composite_score`` down with it.

This shim exists to replace that opaque failure with an actionable one. Delete
it once downstream consumers have migrated.
"""

raise ImportError(
    "parrot_tools.technical_analysis has moved to "
    "parrot.finance.tools.technical_analysis (ai-parrot-finance).\n"
    "  Install:  pip install ai-parrot-finance\n"
    "  Import:   from parrot.finance.tools.technical_analysis import "
    "TechnicalAnalysisTool\n"
    "It moved because TechnicalAnalysisTool instantiates the Alpaca, CoinGecko "
    "and CryptoQuant toolkits, which ship with ai-parrot-finance."
)
