# parrot/advisors/tools/compare.py
"""
CompareProductsTool - Generates side-by-side product comparisons.
"""
from typing import Optional, List
from pydantic import Field

from ...tools.abstract import ToolResult
from .base import (
    BaseAdvisorTool, 
    ProductAdvisorToolArgs
)


class CompareProductsArgs(ProductAdvisorToolArgs):
    """Arguments for comparing products."""
    product_ids: Optional[List[str]] = Field(
        None,
        description="Specific product IDs to compare (uses remaining candidates if not provided)"
    )
    aspects: Optional[List[str]] = Field(
        None,
        description="Specific aspects to compare (e.g., ['price', 'dimensions', 'material'])"
    )
    max_products: int = Field(
        default=5,
        description="Maximum number of products to compare",
        ge=2,
        le=10
    )


class CompareProductsTool(BaseAdvisorTool):
    """
    Generates a detailed side-by-side comparison of products.
    
    Use this when:
    - User asks to compare specific products
    - Selection is narrowed to 2-5 products
    - User wants to see differences between options
    """
    
    name: str = "compare_products"
    description: str = (
        "Compare products side-by-side showing key differences. "
        "Use when narrowed to a few options or when user asks to compare."
    )
    args_schema = CompareProductsArgs
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        product_ids: Optional[List[str]] = None,
        aspects: Optional[List[str]] = None,
        max_products: int = 5,
        **kwargs
    ) -> ToolResult:
        """Execute the compare products tool."""
        try:
            # Get product IDs to compare
            ids_to_compare = product_ids
            
            # Get current state for reference (optional - may not exist for direct comparisons)
            state = None
            if self._state_manager:
                state = await self._state_manager.get_state(session_id, user_id)

            if not ids_to_compare:
                # Use current candidates from state
                if state and state.candidate_ids:
                    ids_to_compare = state.candidate_ids[:max_products]
            
            # Name Resolution Logic
            # The LLM often passes product names (e.g., "Elite") instead of IDs.
            # We resolve these against either the session state or all catalog products.
            if ids_to_compare:
                # Get products to resolve names against
                if state and state.candidate_ids:
                    # Use session candidates
                    candidates = await self._catalog.get_products(state.candidate_ids)
                else:
                    # No session - load all products from catalog for name resolution
                    all_ids = await self._catalog.get_all_product_ids()
                    candidates = await self._catalog.get_products(all_ids)
                
                name_map = {p.name.lower(): p.product_id for p in candidates}
                id_set = {p.product_id for p in candidates}
               
                resolved_ids = []
                for item in ids_to_compare:
                    item_clean = item.strip()
                    item_lower = item_clean.lower()
                    
                    # Case 1: already a valid ID
                    if item_clean in id_set:
                        resolved_ids.append(item_clean)
                        continue
                        
                    # Case 2: exact name match (case-insensitive)
                    if item_lower in name_map:
                        resolved_ids.append(name_map[item_lower])
                        continue
                    
                    # Case 3: fuzzy name match (name contains input or input contains name)
                    found_fuzzy = False
                    for name, pid in name_map.items():
                        if item_lower in name or name in item_lower:
                            resolved_ids.append(pid)
                            found_fuzzy = True
                            break
                    if found_fuzzy:
                        continue
                    
                    # If we can't resolve it, keep original to let catalog fail and report it
                    resolved_ids.append(item)
                
                ids_to_compare = resolved_ids
            
            if not ids_to_compare or len(ids_to_compare) < 2:
                return self._error_result(
                    "Need at least 2 products to compare. "
                    "Please specify product names like 'compare Elite and Versa'."
                )
            
            # Limit to max_products
            ids_to_compare = ids_to_compare[:max_products]
            
            # Get comparison data
            comparison = await self._catalog.compare_products(
                product_ids=ids_to_compare,
                comparison_aspects=aspects
            )
            
            if not comparison.get("products"):
                return self._error_result(f"Could not load products for comparison. IDs not found: {ids_to_compare}")
            
            products = comparison["products"]
            
            # Check if we lost some products
            if len(products) < 2 and len(ids_to_compare) >= 2:
                found_ids = {p['id'] for p in products}
                missing = [pid for pid in ids_to_compare if pid not in found_ids]
                return self._error_result(
                    f"Could not load enough products for comparison. "
                    f"Found {len(products)} ({', '.join(found_ids)}), "
                    f"but missing: {', '.join(missing) or 'unknown'}. "
                    "Please verify the product IDs."
                )
            matrix = comparison["comparison"]
            
            response_parts = [
                f"**Comparing {len(products)} Products**\n"
            ]
            
            # Product names header
            response_parts.append("| Feature | " + " | ".join(p["name"][:20] for p in products) + " |")
            response_parts.append("|" + "---|" * (len(products) + 1))
            
            # Comparison rows
            priority_features = ["Price", "Dimensions", "Footprint"]  # Show these first
            
            for feature in priority_features:
                if feature in matrix:
                    values = [str(matrix[feature].get(p["id"], "N/A")) for p in products]
                    response_parts.append(f"| **{feature}** | " + " | ".join(values) + " |")
            
            # Other features
            for feature, values_dict in matrix.items():
                if feature not in priority_features:
                    values = [str(values_dict.get(p["id"], "N/A")) for p in products]
                    response_parts.append(f"| {feature} | " + " | ".join(values) + " |")
            
            # Unique selling points
            response_parts.append("\n**Highlights:**")
            for p in products:
                if p.get("unique_selling_points"):
                    usp = p["unique_selling_points"][:2]
                    response_parts.append(f"- **{p['name']}**: {'; '.join(usp)}")
            
                    usp = p["unique_selling_points"][:2]
                    response_parts.append(f"- **{p['name']}**: {'; '.join(usp)}")
            
            # Images
            response_parts.append("\n**Images:**")
            for p in products:
                if p.get("image_url"):
                    response_parts.append(f"- **{p['name']}**: {p['image_url']}")

            return self._success_result(
                "\n".join(response_parts),
                data={
                    "products": [
                        {**p, "image_url": p.get("image_url")} 
                        for p in products
                    ],
                    "comparison_matrix": matrix,
                    "product_count": len(products)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error comparing products: {e}")
            return self._error_result(f"Failed to compare products: {str(e)}")