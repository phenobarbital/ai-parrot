# parrot/advisors/tools/__init__.py
"""
Product Advisor Tools - Tools for guided product selection.
"""
from .base import BaseAdvisorTool, ProductAdvisorToolArgs
from .start import StartSelectionTool, StartSelectionArgs
from .question import GetNextQuestionTool, GetNextQuestionArgs
from .criteria import ApplyCriteriaTool, ApplyCriteriaArgs
from .compare import CompareProductsTool, CompareProductsArgs
from .undo import UndoSelectionTool, RedoSelectionTool, UndoSelectionArgs
from .state import GetCurrentStateTool, GetCurrentStateArgs
from .recommend import RecommendProductTool, RecommendProductArgs
from .search import SearchProductsTool, SearchProductsArgs, GetProductDetailsTool


__all__ = [
    # Base
    "BaseAdvisorTool",
    "ProductAdvisorToolArgs",
    
    # Tools
    "StartSelectionTool",
    "GetNextQuestionTool", 
    "ApplyCriteriaTool",
    "CompareProductsTool",
    "UndoSelectionTool",
    "RedoSelectionTool",
    "GetCurrentStateTool",
    "RecommendProductTool",
    "SearchProductsTool",
    "GetProductDetailsTool",
    
    # Args schemas
    "StartSelectionArgs",
    "GetNextQuestionArgs",
    "ApplyCriteriaArgs",
    "CompareProductsArgs",
    "UndoSelectionArgs",
    "GetCurrentStateArgs",
    "RecommendProductArgs",
    "SearchProductsArgs",
]


def create_advisor_tools(
    state_manager,
    catalog,
    question_set=None
) -> list:
    """
    Factory function to create all advisor tools with shared dependencies.
    
    Usage:
        tools = create_advisor_tools(
            state_manager=my_state_manager,
            catalog=my_catalog,
            question_set=my_questions
        )
        
        agent.register_tools(tools)
    """
    common_kwargs = {
        "state_manager": state_manager,
        "catalog": catalog,
        "question_set": question_set
    }
    
    return [
        # Search/lookup tools (for answering direct questions)
        SearchProductsTool(catalog=catalog),
        GetProductDetailsTool(catalog=catalog),
        # Selection workflow tools
        StartSelectionTool(**common_kwargs),
        GetNextQuestionTool(**common_kwargs),
        ApplyCriteriaTool(**common_kwargs),
        CompareProductsTool(**common_kwargs),
        UndoSelectionTool(**common_kwargs),
        RedoSelectionTool(**common_kwargs),
        GetCurrentStateTool(**common_kwargs),
        RecommendProductTool(**common_kwargs),
    ]