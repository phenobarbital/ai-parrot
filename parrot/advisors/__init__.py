# parrot/advisors/__init__.py
"""
Product Advisor - AI-powered product recommendation system.

This package provides:
- ProductAdvisorMixin: Mixin to add product advisor capabilities to bots
- ProductCatalog: Product storage with hybrid search
- QuestionSet/QuestionGenerator: Discriminant question generation
- SelectionStateManager: Redis-based state with undo/redo support

Usage with BaseBot:
    from parrot.advisors import ProductAdvisorMixin, ProductCatalog
    from parrot.bots import BaseBot

    class ProductBot(ProductAdvisorMixin, BaseBot):
        pass

    catalog = ProductCatalog(catalog_id="my_products")
    await catalog.initialize()

    bot = ProductBot(
        name="Product Advisor",
        llm="google:gemini-2.0-flash",
        catalog=catalog,
    )
    await bot.configure()
    await bot.configure_advisor()
"""
from .mixin import ProductAdvisorMixin
from .catalog.catalog import ProductCatalog
from .catalog.loaders import ProductLoader, CSVLoader, LoadResult
from .manager import SelectionStateManager
from .questions import (
    QuestionSet,
    DiscriminantQuestion,
    AnswerType,
    QuestionCategory,
)
from .generator import QuestionGenerator
from .models import (
    ProductSpec,
    ProductFeature,
    ProductDimensions,
    FeatureType,
)
from .tools import create_advisor_tools


__all__ = [
    # Core mixin
    "ProductAdvisorMixin",
    # Catalog
    "ProductCatalog",
    "ProductLoader",
    "CSVLoader",
    "LoadResult",
    # State management
    "SelectionStateManager",
    # Questions
    "QuestionSet",
    "DiscriminantQuestion",
    "QuestionGenerator",
    "AnswerType",
    "QuestionCategory",
    # Models
    "ProductSpec",
    "ProductFeature",
    "ProductDimensions",
    "FeatureType",
    # Factory
    "create_advisor_tools",
]
