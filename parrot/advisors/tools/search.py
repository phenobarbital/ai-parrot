# parrot/advisors/tools/search.py
"""
Product Search Tool - Direct product lookup and search.
"""
from typing import Optional, List, Dict, Any
from pydantic import Field
from ..models import ProductSpec
from .base import BaseAdvisorTool, ProductAdvisorToolArgs, ToolResult


class SearchProductsArgs(ProductAdvisorToolArgs):
    """Arguments for searching products."""
    query: str = Field(
        ...,
        description="Search query - can be product name, category, or description keywords"
    )
    max_results: int = Field(
        default=5,
        description="Maximum number of results to return",
        ge=1,
        le=10
    )
    include_price: bool = Field(
        default=True,
        description="Whether to include price information in results"
    )


class SearchProductsTool(BaseAdvisorTool):
    """
    Search for products by name, category, or keywords.
    
    Use this tool to:
    - Look up specific products by name
    - Find products in a category
    - Search by features or description
    - Answer questions about product prices and details
    """
    
    name: str = "search_products"
    description: str = (
        "Search the product catalog to find products by name, category, or keywords. "
        "Use this to answer questions about specific products, prices, and features."
    )
    args_schema = SearchProductsArgs
    
    async def _execute(
        self,
        query: str,
        user_id: str = "default",
        session_id: str = "default",
        max_results: int = 5,
        include_price: bool = True,
        **kwargs
    ) -> ToolResult:
        """Execute product search."""
        try:
            if not self._catalog:
                return self._error_result("Product catalog not available.")
            
            # Try semantic search first if available
            results: List[ProductSpec] = []
            
            # Check if catalog has semantic search
            if hasattr(self._catalog, 'search_products'):
                results = await self._catalog.search_products(
                    query=query,
                    limit=max_results
                )
            elif hasattr(self._catalog, 'find_similar'):
                results = await self._catalog.find_similar(
                    query=query,
                    limit=max_results
                )
            else:
                # Fallback: get all and filter
                all_products = await self._catalog.get_all_products()
                query_lower = query.lower()
                
                # Score products by relevance
                scored = []
                for p in all_products:
                    score = 0
                    name_lower = p.name.lower() if p.name else ""
                    category_lower = p.category.lower() if p.category else ""
                    
                    # Exact name match
                    if query_lower in name_lower:
                        score += 10
                    if query_lower == name_lower:
                        score += 20
                    
                    # Category match
                    if query_lower in category_lower:
                        score += 5
                    
                    # Keywords in features
                    for feat in (p.features or []):
                        if query_lower in str(feat.value).lower():
                            score += 2
                    
                    # Keywords in description
                    if p.description and query_lower in p.description.lower():
                        score += 3
                    
                    if score > 0:
                        scored.append((score, p))
                
                # Sort by score and take top results
                scored.sort(key=lambda x: x[0], reverse=True)
                results = [p for _, p in scored[:max_results]]
            
            if not results:
                return self._success_result(
                    f"No products found matching '{query}'. Try a different search term.",
                    data={"results": [], "query": query}
                )
            
            # Format results
            response_parts = [f"Found {len(results)} product(s) for '{query}':\n"]
            
            product_data = []
            for p in results:
                # Build product info line
                info = f"**{p.name}**"
                if include_price and p.price:
                    info += f" - ${p.price:,.0f}"
                if p.category:
                    info += f" ({p.category})"
                
                response_parts.append(f"• {info}")
                
                # Add dimensions if available
                if p.dimensions:
                    response_parts.append(
                        f"  Size: {p.dimensions.width} x {p.dimensions.depth} ft"
                    )
                
                # Add key features (first 2)
                if p.unique_selling_points:
                    for usp in p.unique_selling_points[:2]:
                        response_parts.append(f"  ✓ {usp}")
                
                # Add image and product links
                if p.image_url:
                    response_parts.append(f"  🖼️ Image: {p.image_url}")
                if p.url:
                    response_parts.append(f"  🔗 Link: {p.url}")
                
                response_parts.append("")  # blank line between products
                
                # Collect data
                product_data.append({
                    "id": p.product_id,
                    "name": p.name,
                    "price": p.price,
                    "category": p.category,
                    "dimensions": {
                        "width": p.dimensions.width if p.dimensions else None,
                        "depth": p.dimensions.depth if p.dimensions else None,
                        "footprint": p.dimensions.footprint if p.dimensions else None,
                    } if p.dimensions else None,
                    "url": p.url,
                    "image_url": p.image_url,
                })
            
            return self._success_result(
                "\n".join(response_parts),
                data={"results": product_data, "query": query, "count": len(results)}
            )
            
        except Exception as e:
            self.logger.error(f"Error searching products: {e}")
            return self._error_result(f"Search failed: {str(e)}")


class GetProductDetailsTool(BaseAdvisorTool):
    """
    Get detailed information about a specific product.
    """
    
    name: str = "get_product_details"
    description: str = (
        "Get full details about a specific product by its ID or name. "
        "Returns price, dimensions, features, and specifications."
    )
    
    class Args(ProductAdvisorToolArgs):
        product_id: Optional[str] = Field(
            default=None,
            description="Product ID to look up"
        )
        product_name: Optional[str] = Field(
            default=None,
            description="Product name to search for"
        )
    
    args_schema = Args
    
    async def _execute(
        self,
        user_id: str = "default",
        session_id: str = "default",
        product_id: Optional[str] = None,
        product_name: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Get product details."""
        try:
            if not self._catalog:
                return self._error_result("Product catalog not available.")
            
            product: Optional[ProductSpec] = None
            
            # Look up by ID
            if product_id:
                product = await self._catalog.get_product(product_id)
            
            # Search by name
            if not product and product_name:
                all_products = await self._catalog.get_all_products()
                name_lower = product_name.lower()
                for p in all_products:
                    if p.name and name_lower in p.name.lower():
                        product = p
                        break
            
            if not product:
                search_term = product_id or product_name
                return self._error_result(
                    f"Product '{search_term}' not found. Try searching with different terms."
                )
            
            # Format detailed response
            parts = [f"## {product.name}\n"]
            
            if product.price:
                parts.append(f"**Price:** ${product.price:,.0f}")
            
            if product.category:
                parts.append(f"**Category:** {product.category}")
            
            if product.dimensions:
                d = product.dimensions
                parts.append(f"**Dimensions:** {d.width} x {d.depth} ft ({d.footprint:.0f} sq ft)")
                if d.height:
                    parts.append(f"**Height:** {d.height} ft")
            
            if product.description:
                parts.append(f"\n**Description:**\n{product.description}")
            
            if product.unique_selling_points:
                parts.append("\n**Key Features:**")
                for usp in product.unique_selling_points:
                    parts.append(f"• {usp}")
            
            if product.features:
                parts.append("\n**Specifications:**")
                for feat in product.features[:10]:  # Limit to avoid overwhelming
                    parts.append(f"• {feat.name}")
            
            # Include image URL for visual reference
            if product.image_url:
                parts.append(f"\n🖼️ **Product Image:** {product.image_url}")
            
            if product.url:
                parts.append(f"\n🔗 [View Product Details]({product.url})")
            
            return self._success_result(
                "\n".join(parts),
                data={
                    "product_id": product.product_id,
                    "name": product.name,
                    "price": product.price,
                    "category": product.category,
                    "description": product.description,
                    "dimensions": {
                        "width": product.dimensions.width,
                        "depth": product.dimensions.depth,
                        "height": product.dimensions.height,
                        "footprint": product.dimensions.footprint,
                    } if product.dimensions else None,
                    "features": [
                        {"name": f.name, "value": f.value}
                        for f in (product.features or [])
                    ],
                    "unique_selling_points": product.unique_selling_points,
                    "url": product.url,
                    "image_url": product.image_url,
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error getting product details: {e}")
            return self._error_result(f"Failed to get product: {str(e)}")
