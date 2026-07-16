---
type: Wiki Entity
title: ProductCatalog
id: class:parrot.advisors.catalog.catalog.ProductCatalog
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Product catalog with hybrid search capabilities.
---

# ProductCatalog

Defined in [`parrot.advisors.catalog.catalog`](../summaries/mod:parrot.advisors.catalog.catalog.md).

```python
class ProductCatalog
```

Product catalog with hybrid search capabilities.

Combines:
- Structured filtering (price, dimensions, category)
- Semantic search (embeddings)
- JSONB queries (specs, features)

Usage:
    catalog = ProductCatalog(
        catalog_id="sheds_2024",
        table="products_catalog",
        embedding_model="BAAI/bge-base-en-v1.5"
    )
    await catalog.initialize()

    # Add products
    await catalog.add_product(product_spec)


    )

## Methods

- `async def initialize(self, create_table: bool=True) -> None` — Initialize the catalog store and create table if needed.
- `async def add_product(self, product: ProductSpec, generate_embedding: bool=True) -> str` — Add a product to the catalog.
- `async def get_product(self, product_id: str) -> Optional[ProductSpec]` — Get a single product by ID.
- `async def get_products(self, product_ids: List[str]) -> List[ProductSpec]` — Get multiple products by IDs.
- `async def get_all_products(self, category: Optional[str]=None, active_only: bool=True) -> List[ProductSpec]` — Get all products in catalog.
- `async def get_all_product_ids(self, category: Optional[str]=None) -> List[str]` — Get all product IDs (lightweight query).
- `async def search(self, query: Optional[str]=None, filters: Optional[Dict[str, Any]]=None, limit: int=10, score_threshold: float=0.3, search_type: str='hybrid') -> List[ProductSearchResult]` — Search products with hybrid capabilities.
- `async def filter_products(self, product_ids: List[str], criteria: Dict[str, Any], soft_match: bool=True) -> Tuple[List[str], Dict[str, str]]` — Filter products by criteria, return matching IDs and elimination reasons.
- `async def compare_products(self, product_ids: List[str], comparison_aspects: Optional[List[str]]=None) -> Dict[str, Any]` — Generate a comparison matrix for products.
- `async def close(self) -> None` — Close database connections.
