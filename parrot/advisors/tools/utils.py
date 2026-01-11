# parrot/advisors/tools/utils.py
"""
Shared utilities for Product Advisor tools.
"""
from typing import Dict, Any, Optional
import re


def normalize_price_value(price_str: str) -> float:
    """
    Normalize price string to a float value.
    
    Handles:
    - K/k notation: "5K" → 5000, "2.5k" → 2500
    - M/m notation: "1M" → 1000000
    - Commas: "5,000" → 5000
    - Dollar signs: "$5000" → 5000
    """
    if not price_str:
        return 0.0
    
    # Clean up the string
    price_str = price_str.strip().replace(',', '').replace('$', '')
    
    # Handle K/k notation (thousands)
    k_match = re.match(r'^([\d.]+)\s*[kK]$', price_str)
    if k_match:
        return float(k_match.group(1)) * 1000
    
    # Handle M/m notation (millions)
    m_match = re.match(r'^([\d.]+)\s*[mM]$', price_str)
    if m_match:
        return float(m_match.group(1)) * 1000000
    
    # Regular number
    try:
        return float(price_str)
    except ValueError:
        return 0.0


def infer_criteria_from_response(response: str) -> Dict[str, Any]:
    """
    Try to infer criteria from a free-form response.
    
    Handles common patterns like:
    - "about 10x12 feet" → max_footprint: 120
    - "under $2000" → max_price: 2000
    - "no more than 5K" → max_price: 5000
    - "for storage" → use_case: storage
    """
    if not response:
        return {}
        
    response_lower = response.lower()
    criteria = {}
    
    # Dimension patterns: "10x12", "10 by 12", "10 feet by 12 feet"
    dim_match = re.search(
        r'(\d+\.?\d*)\s*(?:ft|feet|foot)?\s*[xX×by]\s*(\d+\.?\d*)\s*(?:ft|feet|foot)?',
        response_lower
    )
    if dim_match:
        width, depth = float(dim_match.group(1)), float(dim_match.group(2))
        criteria["available_space"] = {"width": width, "depth": depth}
        # Approximate footprint if not exact
        criteria["max_footprint"] = width * depth
        return criteria
    
    # Price patterns - improved to handle K notation
    # Max price patterns (under/budget/no more than)
    # Note: "no more than" must be checked before "more than"
    max_price_match = re.search(
        r'(?:under|below|max|maximum|budget[^\d]*|less than|no more than|up to)\s*\$?\s*([\d.,]+\s*[kKmM]?)',
        response_lower
    )
    if max_price_match:
        price = normalize_price_value(max_price_match.group(1))
        if price > 0:
            criteria["max_price"] = price

    # Min price patterns (over/above/at least)
    # Only check if we didn't already match "no more than" (which would be confused with "more than")
    if "max_price" not in criteria or "no more than" not in response_lower:
        min_price_match = re.search(
            r'(?:over|above|min|minimum|more than|at least|start(?:ing)? at)\s*\$?\s*([\d.,]+\s*[kKmM]?)',
            response_lower
        )
        if min_price_match:
            price = normalize_price_value(min_price_match.group(1))
            if price > 0:
                criteria["min_price"] = price
    
    # Use case patterns
    use_cases = ["storage", "workshop", "workspace", "office", "gym", "studio", 
                 "garden", "tools", "equipment", "hobby"]
    for uc in use_cases:
        if uc in response_lower:
            criteria["use_case"] = uc
            break  # found a use case
            
    # Simple size keywords
    if "small" in response_lower:
        criteria["size_category"] = "small"
    elif "large" in response_lower or "big" in response_lower:
        criteria["size_category"] = "large"
    elif "medium" in response_lower:
        criteria["size_category"] = "medium"
        
    # Price range keywords
    if "budget" in response_lower or "economy" in response_lower:
        criteria["price_range"] = "budget"
    elif "mid" in response_lower and ("range" in response_lower or "tier" in response_lower):
        criteria["price_range"] = "mid-range"
    elif "premium" in response_lower:
        criteria["price_range"] = "premium"
    elif "luxury" in response_lower:
        criteria["price_range"] = "luxury"
    
    # Subcategory keywords (product type/context)
    subcategories = {
        "commercial": ["commercial", "business", "professional"],
        "home": ["home", "residential", "house"],
        "pool": ["pool", "poolside", "swimming"],
        "farm": ["farm", "farming", "agricultural", "agriculture"],
        "backyard": ["backyard", "back yard", "patio", "garden area"],
        "industrial": ["industrial", "warehouse", "factory"],
        "country": ["country", "rural", "cottage"],
    }
    for subcat, keywords in subcategories.items():
        for kw in keywords:
            if kw in response_lower:
                criteria["subcategory"] = subcat
                break
        if "subcategory" in criteria:
            break
    
    return criteria

