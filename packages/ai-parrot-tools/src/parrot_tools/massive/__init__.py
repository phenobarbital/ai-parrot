"""
MassiveToolkit - Premium market data enrichment from Massive.com (ex-Polygon.io).

Provides institutional-grade data not available from free APIs:
- Options chains with exchange-computed Greeks and IV
- FINRA short interest and short volume data
- Benzinga earnings with revenue estimates/actuals
- Benzinga analyst ratings with individual analyst actions
"""

from .cache import MassiveCache
from .models import (
    OptionsChainInput,
    ShortInterestInput,
    ShortVolumeInput,
    EarningsDataInput,
    AnalystRatingsInput,
    GreeksData,
    OptionsContract,
    OptionsChainOutput,
    ShortInterestRecord,
    ShortInterestDerived,
    ShortInterestOutput,
    ShortVolumeRecord,
    ShortVolumeDerived,
    ShortVolumeOutput,
    EarningsRecord,
    EarningsDerived,
    EarningsOutput,
    AnalystAction,
    ConsensusRating,
    AnalystRatingsDerived,
    AnalystRatingsOutput,
)
from .toolkit import MassiveToolkit

__all__ = [
    # Toolkit
    "MassiveToolkit",
    # Cache
    "MassiveCache",
    # Input models
    "OptionsChainInput",
    "ShortInterestInput",
    "ShortVolumeInput",
    "EarningsDataInput",
    "AnalystRatingsInput",
    # Output models
    "GreeksData",
    "OptionsContract",
    "OptionsChainOutput",
    "ShortInterestRecord",
    "ShortInterestDerived",
    "ShortInterestOutput",
    "ShortVolumeRecord",
    "ShortVolumeDerived",
    "ShortVolumeOutput",
    "EarningsRecord",
    "EarningsDerived",
    "EarningsOutput",
    "AnalystAction",
    "ConsensusRating",
    "AnalystRatingsDerived",
    "AnalystRatingsOutput",
]

