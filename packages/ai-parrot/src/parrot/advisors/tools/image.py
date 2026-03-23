"""
ShowProductImageTool - Show product image on explicit request.

Triggered when user says:
- "Can you show me the image?"
- "What does it look like?"
- "Can you show me a photo?"
"""
from typing import Optional
from pydantic import Field
from ...tools.abstract import ToolResult
from .base import BaseAdvisorTool, ProductAdvisorToolArgs


class ShowProductImageArgs(ProductAdvisorToolArgs):
    """Arguments for showing product image."""
    product_id: Optional[str] = Field(
        None,
        description="Product ID to show (uses recommended product if not specified)"
    )


class ShowProductImageTool(BaseAdvisorTool):
    """Show product image without speaking the URL."""

    name: str = "show_product_image"
    description: str = (
        "Show the product image to the user. Use when they ask to see "
        "what a product looks like, request a photo, or want to see the image."
    )
    args_schema = ShowProductImageArgs

    async def _execute(
        self,
        user_id: str,
        session_id: str,
        product_id: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Show product image."""
        try:
            # Try to get state, but don't error if missing (unlike _get_state_or_error)
            # This avoids the "State retrieval failed" warning when doing direct lookups
            state = await self._state_manager.get_state(session_id, user_id)
            
            target_id = product_id
            
            # 1. If no ID provided, try to infer from state
            if not target_id and state:
                # Priority: Recommended > Last Viewed > Single Candidate
                if state.metadata.get("recommended_id"):
                    target_id = state.metadata["recommended_id"]
                    self.logger.debug(f"Using recommended_id: {target_id}")
                elif state.metadata.get("last_viewed_id"):
                    target_id = state.metadata["last_viewed_id"]
                    self.logger.debug(f"Using last_viewed_id: {target_id}")
                elif state.candidate_ids and len(state.candidate_ids) == 1:
                    target_id = state.candidate_ids[0]
                    self.logger.debug(f"Using single candidate: {target_id}")

            if not target_id:
                return self._error_result(
                    "No product selected. Would you like me to help you find one?"
                )

            # 2. Try direct lookup by ID
            product = await self._catalog.get_product(target_id)
            
            # 3. If not found, and target_id looks like a name, try search
            if not product and target_id:
                # Basic heuristic: if it has spaces or is not a clean slug, it might be a name
                # Or just try search anyway as fallback
                # Use 'search' method instead of non-existent 'search_products'
                results = await self._catalog.search(
                    query=target_id,
                    limit=1,
                    search_type="hybrid"
                )
                if results:
                    # results is a list of ProductSearchResult, so we need .product
                    product = results[0].product

            if not product:
                return self._error_result(f"I couldn't find a product named '{target_id}'.")

            if not product.image_url:
                return self._success_result(
                    voice_text=f"Sorry, I don't have an image available for the {product.name}.",
                    message=f"No image available for {product.name}",
                )

            return self._success_result(
                message=f"Showing image of {product.name}: {product.image_url}",
                voice_text=f"Here is the {product.name}. Check the screen.",
                display_data={
                    "type": "image",
                    "content": {
                        "url": product.image_url,
                        "alt": product.name,
                        "caption": f"{product.name}" + (
                            f" - ${product.price:,.0f}" if product.price else ""
                        ),
                        "product_url": product.url,
                    },
                    "auto_display": True,
                }
            )

        except Exception as e:
            self.logger.error(f"Error showing image: {e}")
            return self._error_result("I could not show the image.")
