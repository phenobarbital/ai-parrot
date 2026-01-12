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
            self.logger.debug(
                f"🔍 SearchProductsTool._execute called with query='{query}', "
                f"catalog={self._catalog}, catalog_id={getattr(self._catalog, 'catalog_id', 'N/A')}"
            )
            
            if not self._catalog:
                self.logger.error("❌ Product catalog is None!")
                return self._error_result("Product catalog not available.")
            
            # Check catalog initialization status
            self.logger.debug(
                f"📦 Catalog status: initialized={getattr(self._catalog, '_initialized', 'N/A')}, "
                f"schema={getattr(self._catalog, 'schema', 'N/A')}, "
                f"table={getattr(self._catalog, 'table', 'N/A')}"
            )
            
            # Try semantic search first if available
            results: List[ProductSpec] = []
            
            # Check if catalog has semantic search
            has_search = hasattr(self._catalog, 'search_products')
            has_similar = hasattr(self._catalog, 'find_similar')
            self.logger.debug(
                f"🔎 Method availability: search_products={has_search}, find_similar={has_similar}"
            )
            
            if has_search:
                self.logger.debug("Using catalog.search_products()")
                results = await self._catalog.search_products(
                    query=query,
                    limit=max_results
                )
            elif has_similar:
                self.logger.debug("Using catalog.find_similar()")
                results = await self._catalog.find_similar(
                    query=query,
                    limit=max_results
                )
            else:
                # Fallback: get all and filter
                self.logger.debug("Using fallback: get_all_products() + scoring")
                all_products = await self._catalog.get_all_products()
                self.logger.debug(f"📊 Got {len(all_products)} products from catalog")
                query_lower = query.lower().strip()
                # Tokenize query into words for better matching
                query_words = [w.strip() for w in query_lower.split() if len(w.strip()) > 2]
                self.logger.debug(f"🔍 Search query: '{query_lower}', words: {query_words}")
                
                # Score products by relevance
                scored = []
                for p in all_products:
                    score = 0
                    name_lower = p.name.lower() if p.name else ""
                    category_lower = p.category.lower() if p.category else ""
                    
                    self.logger.debug(
                        f"  Checking product: name='{p.name}' (lower='{name_lower}'), "
                        f"category='{p.category}'"
                    )
                    
                    # ═══════════════════════════════════════════════════════════
                    # Name matching (highest priority)
                    # ═══════════════════════════════════════════════════════════
                    
                    # Exact name match (highest score)
                    if query_lower == name_lower:
                        score += 30
                        self.logger.debug(f"    +30 (exact name match)")
                    # Product name is contained in query (e.g., "imperial" in "imperial shed")
                    elif name_lower and name_lower in query_lower:
                        score += 20
                        self.logger.debug(f"    +20 (name in query)")
                    # Query is contained in product name
                    elif query_lower in name_lower:
                        score += 15
                        self.logger.debug(f"    +15 (query in name)")
                    else:
                        # Check if any query word matches the product name
                        for word in query_words:
                            if word == name_lower:
                                score += 20
                                self.logger.debug(f"    +20 (word '{word}' exact match)")
                                break
                            elif word in name_lower or name_lower in word:
                                score += 10
                                self.logger.debug(f"    +10 (word '{word}' partial match)")
                                break
                    
                    # ═══════════════════════════════════════════════════════════
                    # Category matching
                    # ═══════════════════════════════════════════════════════════
                    
                    # Check if category matches any query word
                    if category_lower:
                        for word in query_words:
                            if word in category_lower or category_lower in word:
                                score += 5
                                self.logger.debug(f"    +5 (category match: '{word}')")
                                break
                    
                    # ═══════════════════════════════════════════════════════════
                    # Features and description matching
                    # ═══════════════════════════════════════════════════════════
                    
                    # Keywords in features
                    for feat in (p.features or []):
                        feat_value = str(feat.value).lower()
                        for word in query_words:
                            if word in feat_value:
                                score += 2
                                break
                    
                    # Keywords in description
                    if p.description:
                        desc_lower = p.description.lower()
                        for word in query_words:
                            if word in desc_lower:
                                score += 3
                                self.logger.debug(f"    +3 (description match)")
                                break
                    
                    self.logger.debug(f"    Final score: {score}")
                    if score > 0:
                        scored.append((score, p))
                
                # Sort by score and take top results
                scored.sort(key=lambda x: x[0], reverse=True)
                results = [p for _, p in scored[:max_results]]
                self.logger.debug(f"📊 Scoring complete: {len(scored)} products matched, returning top {len(results)}")
            
            if not results:
                self.logger.warning(f"⚠️ No products found for query '{query}'")
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
