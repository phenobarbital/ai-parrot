# parrot/advisors/tools/recommend.py
"""
RecommendProductTool - Generates a final product recommendation.
"""
from typing import Optional, List
from pydantic import Field

from ...tools.abstract import ToolResult
from .base import BaseAdvisorTool, ProductAdvisorToolArgs


class RecommendProductArgs(ProductAdvisorToolArgs):
    """Arguments for generating a recommendation."""
    explain_reasoning: bool = Field(
        default=True,
        description="Whether to explain why this product is recommended"
    )
    include_alternatives: bool = Field(
        default=True,
        description="Whether to include alternative options"
    )
    max_alternatives: int = Field(
        default=2,
        description="Maximum number of alternatives to include",
        ge=0,
        le=5
    )


class RecommendProductTool(BaseAdvisorTool):
    """
    Generates a final product recommendation based on collected criteria.
    
    This tool:
    1. Analyzes remaining products against user criteria
    2. Selects the best match
    3. Explains why it's recommended
    4. Optionally suggests alternatives
    
    Use when the selection is narrowed to 1-3 products.
    """
    
    name: str = "recommend_product"
    description: str = (
        "Generate a final product recommendation based on the user's criteria. "
        "Use when selection is narrowed to a few products."
    )
    args_schema = RecommendProductArgs
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        explain_reasoning: bool = True,
        include_alternatives: bool = True,
        max_alternatives: int = 2,
        **kwargs
    ) -> ToolResult:
        """Execute the recommend product tool."""
        try:
            # Get current state
            state, error = await self._get_state_or_error(user_id, session_id)
            if error:
                return error
            
            if not state.candidate_ids:
                return self._error_result(
                    "No products match your criteria. Would you like to undo some choices "
                    "and try different options?"
                )
            
            # Get remaining products
            products = await self._catalog.get_products(state.candidate_ids)
            
            if not products:
                return self._error_result("Could not load product details.")
            
            # Score and rank products based on criteria match
            scored_products = self._score_products(products, state.criteria)
            
            # Best match
            recommended = scored_products[0]
            alternatives = scored_products[1:max_alternatives + 1] if include_alternatives else []
            
            # Build response
            response_parts = [
                f"🎯 **My Recommendation: {recommended['product'].name}**\n"
            ]
            
            # Product details
            p = recommended['product']
            if p.price:
                response_parts.append(f"**Price:** ${p.price:,.0f}")
            if p.dimensions:
                response_parts.append(
                    f"**Size:** {p.dimensions.width} x {p.dimensions.depth} ft "
                    f"({p.dimensions.footprint:.0f} sq ft)"
                )
            
            # Reasoning
            if explain_reasoning and recommended.get('reasons'):
                response_parts.append("\n**Why this product:**")
                for reason in recommended['reasons'][:4]:
                    response_parts.append(f"✓ {reason}")
            
            # Unique selling points
            if p.unique_selling_points:
                response_parts.append("\n**Key Features:**")
                for usp in p.unique_selling_points[:3]:
                    response_parts.append(f"• {usp}")
            
            # Link
            if p.url:
                response_parts.append(f"\n🔗 [View Product Details]({p.url})")
            
            # Image
            if p.image_url:
                response_parts.append(f"\n🖼️ Image: {p.image_url}")
            
            # Alternatives
            if alternatives:
                response_parts.append("\n---\n**Also Consider:**")
                for alt in alternatives:
                    alt_p = alt['product']
                    price_str = f"${alt_p.price:,.0f}" if alt_p.price else ""
                    response_parts.append(f"• **{alt_p.name}** {price_str}")
                    if alt.get('reasons'):
                        response_parts.append(f"  _{alt['reasons'][0]}_")
            
            # Update state to completed, but preserve candidate_ids for follow-up comparisons
            from ..state import SelectionPhase
            state.phase = SelectionPhase.COMPLETED
            # Store recommendation info in metadata for potential follow-up queries
            state.metadata["recommended_id"] = p.product_id
            state.metadata["alternative_ids"] = [alt['product'].product_id for alt in alternatives]
            await self._state_manager._save_state(state)
            
            return self._success_result(
                "\n".join(response_parts),
                data={
                    "recommended": {
                        "id": p.product_id,
                        "name": p.name,
                        "price": p.price,
                        "url": p.url,
                        "image_url": p.image_url,
                        "score": recommended['score'],
                        "reasons": recommended.get('reasons', [])
                    },
                    "alternatives": [
                        {
                            "id": alt['product'].product_id,
                            "name": alt['product'].name,
                            "price": alt['product'].price,
                            "score": alt['score']
                        }
                        for alt in alternatives
                    ],
                    "criteria_used": state.criteria,
                    "selection_complete": True
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error generating recommendation: {e}")
            return self._error_result(f"Failed to generate recommendation: {str(e)}")
    
    def _score_products(
        self, 
        products: List, 
        criteria: dict
    ) -> List[dict]:
        """
        Score products based on how well they match criteria.
        
        Returns list of {product, score, reasons} sorted by score descending.
        """
        scored = []
        
        for product in products:
            score = 100  # Start with perfect score
            reasons = []
            
            # Score based on criteria match
            if "use_case" in criteria:
                if criteria["use_case"] in product.use_cases:
                    reasons.append(f"Great for {criteria['use_case']}")
                else:
                    score -= 20
            
            if "max_price" in criteria and product.price:
                price_ratio = product.price / criteria["max_price"]
                if price_ratio <= 0.7:
                    reasons.append("Well within your budget")
                    score += 10
                elif price_ratio <= 0.9:
                    reasons.append("Good value for the price")
                elif price_ratio > 1:
                    score -= 30
            
            if "max_footprint" in criteria and product.dimensions:
                space_ratio = product.dimensions.footprint / criteria["max_footprint"]
                if space_ratio <= 0.8:
                    reasons.append("Fits comfortably in your space")
                    score += 5
                elif space_ratio <= 1.0:
                    reasons.append("Fits your available space")
            
            # Bonus for unique selling points
            if product.unique_selling_points:
                score += len(product.unique_selling_points) * 2
                reasons.extend(product.unique_selling_points[:2])
            
            scored.append({
                "product": product,
                "score": score,
                "reasons": reasons
            })
        
        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored