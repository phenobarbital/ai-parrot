"""Tools for querying investment memos.

These tools enable agents to reference historical investment decisions
and recommendations during deliberation.
"""

import dataclasses
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from parrot.tools import tool

from ..memo_store import get_memo_store


def _serialize_memo(obj: Any) -> Any:
    """Recursively serialize a memo object to a JSON-compatible dict.

    Handles dataclasses, enums, datetime objects, and nested structures.

    Args:
        obj: Object to serialize.

    Returns:
        JSON-serializable representation.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: _serialize_memo(getattr(obj, field.name))
            for field in dataclasses.fields(obj)
        }
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_serialize_memo(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_memo(v) for k, v in obj.items()}
    return obj


@tool()
async def get_recent_memos(
    days: int = 7,
    ticker: Optional[str] = None,
) -> list[dict]:
    """Get recent investment memos.

    Use this tool to review past investment decisions and recommendations.
    Returns summaries of memos created in the last N days, optionally
    filtered by ticker symbol.

    Args:
        days: Number of days to look back (default 7).
        ticker: Optional ticker symbol to filter by (e.g., "AAPL", "BTC/USDT").

    Returns:
        List of memo summaries, each containing:
        - id: Unique memo identifier
        - date: ISO format creation timestamp
        - consensus: Final consensus level (unanimous, majority, etc.)
        - summary: Truncated executive summary (first 200 chars)
        - recommendations: Total number of recommendations
        - actionable: Number of actionable recommendations
        - tickers: List of ticker symbols in recommendations
    """
    store = get_memo_store()
    start = datetime.now(timezone.utc) - timedelta(days=days)
    memos = await store.get_by_date(start)

    if ticker:
        ticker_upper = ticker.upper()
        memos = [
            m for m in memos
            if any(r.asset.upper() == ticker_upper for r in m.recommendations)
        ]

    return [
        {
            "id": m.id,
            "date": m.created_at.isoformat(),
            "consensus": (
                m.final_consensus.value
                if hasattr(m.final_consensus, "value")
                else str(m.final_consensus)
            ),
            "summary": (
                m.executive_summary[:200] + "..."
                if len(m.executive_summary) > 200
                else m.executive_summary
            ),
            "recommendations": len(m.recommendations),
            "actionable": len(m.actionable_recommendations),
            "tickers": [r.asset for r in m.recommendations if r.asset],
        }
        for m in memos
    ]


@tool()
async def get_memo_detail(memo_id: str) -> Optional[dict]:
    """Get full details of an investment memo by ID.

    Use this to retrieve the complete memo including all recommendations,
    market conditions, portfolio snapshot, and deliberation details.
    Call get_recent_memos first to find relevant memo IDs, then use this
    tool to access the full content.

    Args:
        memo_id: The memo identifier (from get_recent_memos).

    Returns:
        Full memo data as a dict, or None if the memo is not found.
        The dict contains:
        - id: Unique memo identifier
        - created_at: ISO format creation timestamp
        - valid_until: ISO format expiry timestamp (or null)
        - executive_summary: Full narrative summary from the Secretary
        - market_conditions: Market context at decision time
        - portfolio_snapshot: Portfolio state when memo was created
        - recommendations: List of actionable recommendations with consensus,
            sizing, entry/stop/target prices, and analyst votes
        - deliberation_rounds: Number of CIO challenge rounds
        - final_consensus: Overall committee consensus level
        - source_report_ids: IDs of analyst reports used
        - deliberation_round_ids: IDs of deliberation round records
    """
    store = get_memo_store()
    memo = await store.get(memo_id)

    if memo is None:
        return None

    return _serialize_memo(memo)
