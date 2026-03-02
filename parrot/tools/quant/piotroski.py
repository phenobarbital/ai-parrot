"""
Piotroski F-Score Calculator for QuantToolkit.

The Piotroski F-Score is a fundamental quality scoring system that evaluates
company financial health using 9 binary accounting criteria:

Profitability (4 points):
1. Positive Net Income
2. Positive ROA (Return on Assets)
3. Positive Operating Cash Flow
4. Cash Flow > Net Income (quality of earnings)

Leverage/Liquidity/Source of Funds (3 points):
5. Lower Long-Term Debt (YoY)
6. Higher Current Ratio (YoY)
7. No New Shares Issued

Operating Efficiency (2 points):
8. Higher Gross Margin (YoY)
9. Higher Asset Turnover (YoY)

Score Interpretation:
- 8-9: Excellent (strong buy signal)
- 6-7: Good (positive outlook)
- 4-5: Fair (neutral)
- 0-3: Poor (avoid or sell)
"""

from .models import PiotroskiInput


def calculate_piotroski_score(input_data: PiotroskiInput) -> dict:
    """Calculate Piotroski F-Score (0-9) for fundamental quality.

    The F-Score measures financial strength using 9 binary criteria
    across three categories:
    - Profitability (4 points)
    - Leverage/Liquidity/Source of Funds (3 points)
    - Operating Efficiency (2 points)

    Args:
        input_data: PiotroskiInput with quarterly and prior year financials.

    Returns:
        Dictionary with:
        - total_score: int (0-9)
        - criteria: dict with details for each criterion
        - data_completeness_pct: float (0-100)
        - interpretation: str (Excellent/Good/Fair/Poor)
        - category_scores: dict with profitability, leverage_liquidity, operating_efficiency
    """
    q = input_data.quarterly_financials
    p = input_data.prior_year_financials

    criteria = {}
    total_score = 0
    criteria_with_data = 0

    # =========================================================================
    # PROFITABILITY (4 criteria)
    # =========================================================================

    # 1. Positive Net Income
    if "net_income" in q:
        criteria_with_data += 1
        ni = q["net_income"]
        score = 1 if ni > 0 else 0
        criteria["positive_net_income"] = {
            "score": score,
            "value": ni,
            "threshold": "> 0",
        }
        total_score += score

    # 2. Positive ROA (Return on Assets)
    if "net_income" in q and "total_assets" in q and q["total_assets"] > 0:
        criteria_with_data += 1
        roa = q["net_income"] / q["total_assets"]
        score = 1 if roa > 0 else 0
        criteria["positive_roa"] = {
            "score": score,
            "value": round(roa, 4),
            "threshold": "> 0",
        }
        total_score += score

    # 3. Positive Operating Cash Flow
    if "operating_cash_flow" in q:
        criteria_with_data += 1
        ocf = q["operating_cash_flow"]
        score = 1 if ocf > 0 else 0
        criteria["positive_ocf"] = {
            "score": score,
            "value": ocf,
            "threshold": "> 0",
        }
        total_score += score

    # 4. Cash Flow > Net Income (quality of earnings)
    if "operating_cash_flow" in q and "net_income" in q:
        criteria_with_data += 1
        ocf = q["operating_cash_flow"]
        ni = q["net_income"]
        score = 1 if ocf > ni else 0
        criteria["ocf_greater_than_ni"] = {
            "score": score,
            "value": f"OCF={ocf}, NI={ni}",
            "threshold": "OCF > NI",
        }
        total_score += score

    # =========================================================================
    # LEVERAGE / LIQUIDITY / SOURCE OF FUNDS (3 criteria)
    # =========================================================================

    # 5. Lower Long-Term Debt YoY
    if "long_term_debt" in q and "long_term_debt" in p:
        criteria_with_data += 1
        current_debt = q["long_term_debt"]
        prior_debt = p["long_term_debt"]
        score = 1 if current_debt <= prior_debt else 0
        criteria["lower_debt"] = {
            "score": score,
            "value": f"Current={current_debt}, Prior={prior_debt}",
            "threshold": "current <= prior",
        }
        total_score += score

    # 6. Higher Current Ratio YoY
    current_ratio = None
    if (
        "current_assets" in q
        and "current_liabilities" in q
        and q["current_liabilities"] > 0
    ):
        current_ratio = q["current_assets"] / q["current_liabilities"]

    if current_ratio is not None and "current_ratio" in p:
        criteria_with_data += 1
        prior_ratio = p["current_ratio"]
        score = 1 if current_ratio > prior_ratio else 0
        criteria["higher_current_ratio"] = {
            "score": score,
            "value": f"Current={round(current_ratio, 2)}, Prior={prior_ratio}",
            "threshold": "current > prior",
        }
        total_score += score

    # 7. No New Shares Issued (no dilution)
    if "shares_outstanding" in q and "shares_outstanding" in p:
        criteria_with_data += 1
        current_shares = q["shares_outstanding"]
        prior_shares = p["shares_outstanding"]
        score = 1 if current_shares <= prior_shares else 0
        criteria["no_dilution"] = {
            "score": score,
            "value": f"Current={current_shares}, Prior={prior_shares}",
            "threshold": "current <= prior",
        }
        total_score += score

    # =========================================================================
    # OPERATING EFFICIENCY (2 criteria)
    # =========================================================================

    # 8. Higher Gross Margin YoY
    gross_margin = None
    if "gross_profit" in q and "revenue" in q and q["revenue"] > 0:
        gross_margin = q["gross_profit"] / q["revenue"]

    if gross_margin is not None and "gross_margin" in p:
        criteria_with_data += 1
        prior_margin = p["gross_margin"]
        score = 1 if gross_margin > prior_margin else 0
        criteria["higher_gross_margin"] = {
            "score": score,
            "value": f"Current={round(gross_margin, 4)}, Prior={prior_margin}",
            "threshold": "current > prior",
        }
        total_score += score

    # 9. Higher Asset Turnover YoY
    asset_turnover = None
    if "revenue" in q and "total_assets" in q and q["total_assets"] > 0:
        asset_turnover = q["revenue"] / q["total_assets"]

    if asset_turnover is not None and "asset_turnover" in p:
        criteria_with_data += 1
        prior_turnover = p["asset_turnover"]
        score = 1 if asset_turnover > prior_turnover else 0
        criteria["higher_asset_turnover"] = {
            "score": score,
            "value": f"Current={round(asset_turnover, 4)}, Prior={prior_turnover}",
            "threshold": "current > prior",
        }
        total_score += score

    # =========================================================================
    # AGGREGATION
    # =========================================================================

    # Calculate data completeness
    data_completeness = (criteria_with_data / 9) * 100 if 9 > 0 else 0

    # Interpretation
    interpretation = _interpret_score(total_score)

    # Category breakdown
    profitability = sum(
        criteria.get(c, {}).get("score", 0)
        for c in [
            "positive_net_income",
            "positive_roa",
            "positive_ocf",
            "ocf_greater_than_ni",
        ]
    )
    leverage_liquidity = sum(
        criteria.get(c, {}).get("score", 0)
        for c in ["lower_debt", "higher_current_ratio", "no_dilution"]
    )
    operating_efficiency = sum(
        criteria.get(c, {}).get("score", 0)
        for c in ["higher_gross_margin", "higher_asset_turnover"]
    )

    return {
        "total_score": total_score,
        "criteria": criteria,
        "data_completeness_pct": round(data_completeness, 1),
        "interpretation": interpretation,
        "category_scores": {
            "profitability": profitability,
            "leverage_liquidity": leverage_liquidity,
            "operating_efficiency": operating_efficiency,
        },
    }


def _interpret_score(score: int) -> str:
    """Interpret Piotroski F-Score.

    Args:
        score: F-Score (0-9).

    Returns:
        Interpretation string: Excellent, Good, Fair, or Poor.
    """
    if score >= 8:
        return "Excellent"
    elif score >= 6:
        return "Good"
    elif score >= 4:
        return "Fair"
    else:
        return "Poor"


def batch_piotroski_scores(
    symbols_data: dict[str, PiotroskiInput],
) -> dict[str, dict]:
    """Calculate F-Scores for multiple symbols.

    Args:
        symbols_data: Dictionary of {symbol: PiotroskiInput}.

    Returns:
        Dictionary of {symbol: score_result}.
    """
    results = {}
    for symbol, data in symbols_data.items():
        results[symbol] = calculate_piotroski_score(data)
    return results


def get_fscore_summary(result: dict) -> str:
    """Generate a human-readable summary of the F-Score result.

    Args:
        result: Result from calculate_piotroski_score.

    Returns:
        Summary string.
    """
    score = result["total_score"]
    interp = result["interpretation"]
    completeness = result["data_completeness_pct"]
    cat = result["category_scores"]

    lines = [
        f"Piotroski F-Score: {score}/9 ({interp})",
        f"Data Completeness: {completeness}%",
        "",
        "Category Breakdown:",
        f"  Profitability: {cat['profitability']}/4",
        f"  Leverage/Liquidity: {cat['leverage_liquidity']}/3",
        f"  Operating Efficiency: {cat['operating_efficiency']}/2",
    ]

    return "\n".join(lines)


def rank_by_fscore(
    symbols_data: dict[str, PiotroskiInput],
) -> list[tuple[str, int, str]]:
    """Rank symbols by F-Score descending.

    Args:
        symbols_data: Dictionary of {symbol: PiotroskiInput}.

    Returns:
        List of (symbol, score, interpretation) tuples, sorted by score descending.
    """
    results = batch_piotroski_scores(symbols_data)
    ranked = [
        (symbol, r["total_score"], r["interpretation"])
        for symbol, r in results.items()
    ]
    return sorted(ranked, key=lambda x: x[1], reverse=True)
