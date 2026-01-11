# parrot/advisors/tools/base.py
"""
Base classes and utilities for Product Advisor Tools.
"""
from __future__ import annotations
from typing import Dict, Any, TYPE_CHECKING
from pydantic import Field
from ...tools.abstract import (
    AbstractTool,
    AbstractToolArgsSchema, 
    ToolResult
)

if TYPE_CHECKING:
    from ..manager import SelectionStateManager
    from ..catalog import ProductCatalog
    from ..questions import QuestionSet


class ProductAdvisorToolArgs(AbstractToolArgsSchema):
    """Base args schema with common fields for advisor tools."""
    user_id: str = Field(
        ...,
        description="User identifier for the session"
    )
    session_id: str = Field(
        ...,
        description="Session identifier for tracking selection state"
    )


class BaseAdvisorTool(AbstractTool):
    """
    Base class for Product Advisor tools.
    
    Provides common functionality:
    - State manager access
    - Catalog access
    - Question set access
    - Standardized error handling
    """
    
    def __init__(
        self,
        state_manager: "SelectionStateManager" = None,
        catalog: "ProductCatalog" = None,
        question_set: "QuestionSet" = None,
        **kwargs
    ):
        """
        Initialize base advisor tool.
        
        Args:
            state_manager: Selection state manager instance
            catalog: Product catalog instance
            question_set: Question set for the catalog
        """
        self._state_manager = state_manager
        self._catalog = catalog
        self._question_set = question_set
        super().__init__(**kwargs)
    
    def _success_result(
        self, 
        message: str, 
        data: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ) -> ToolResult:
        """Create a successful ToolResult."""
        return ToolResult(
            status="success",
            result=message,
            metadata={
                **(metadata or {}),
                "data": data or {}
            }
        )
    
    def _error_result(self, error: str, metadata: Dict[str, Any] = None) -> ToolResult:
        """Create an error ToolResult."""
        return ToolResult(
            status="error",
            result="",
            error=error,
            metadata=metadata or {}
        )
    
    async def _get_state_or_error(
        self, 
        user_id: str, 
        session_id: str
    ) -> tuple:
        """
        Get current state or return error result.
        
        Returns:
            Tuple of (state, None) or (None, ToolResult with error)
        """
        state = await self._state_manager.get_state(session_id, user_id)
        if not state:
            self.logger.warning(
                f"State retrieval failed for session={session_id}, user={user_id}. "
                f"Key used: {self._state_manager._state_key(session_id, user_id)}"
            )
            return None, self._error_result(
                "No active product selection session. Use 'start_product_selection' first."
            )
        return state, None