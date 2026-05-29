# parrot/advisors/catalog/__init__.py
"""
Product Catalog module - Product storage and search.
"""
from .catalog import ProductCatalog
from .loaders import ProductLoader, CSVLoader, SeparateMarkdownLoader, LoadResult

__all__ = [
    "ProductCatalog",
    "ProductLoader",
    "CSVLoader", 
    "SeparateMarkdownLoader",
    "LoadResult",
]
