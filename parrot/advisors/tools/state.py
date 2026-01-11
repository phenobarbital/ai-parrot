# parrot/advisors/tools/state.py
"""
GetCurrentStateTool - Returns current selection state for transparency/debugging.
"""
from typing import Optional
from pydantic import Field
from ...tools.abstract import ToolResult
from .base import BaseAdvisorTool, ProductAdvisorToolArgs


class GetCurrentStateArgs(ProductAdvisorToolArgs):
    """Arguments for getting current state."""
    include_history: bool = Field(
        default=False,
        description="Whether to include the full selection history"
    )
    include_products: bool = Field(
        default=False,
        description="Whether to include details of remaining products"
    )


class GetCurrentStateTool(BaseAdvisorTool):
    """
    Returns the current state of the product selection process.
    
    Useful for:
    - Debugging selection issues
    - Showing progress to the user
    - Resuming interrupted sessions
    - Understanding why certain products were eliminated
    """
    
    name: str = "get_selection_state"
    description: str = (
        "Get the current state of the product selection process. "
        "Shows criteria collected, products remaining, and progress."
    )
    args_schema = GetCurrentStateArgs
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        include_history: bool = False,
        include_products: bool = False,
        **kwargs
    ) -> ToolResult:
        """Execute the get state tool."""
        try:
            state, error = await self._get_state_or_error(user_id, session_id)
            if error:
                return error
            
            # Build response
            response_parts = [
                "**Selection Progress**",
                f"- Phase: {state.phase.value}",
                f"- Products remaining: {state.products_remaining} of {len(state.all_product_ids)}",
                f"- Questions answered: {len(state.questions_asked)}",
            ]
            
            if state.criteria:
                response_parts.append("\n**Criteria collected:**")
                for key, value in state.criteria.items():
                    response_parts.append(f"- {key}: {value}")
            
            if state.eliminated:
                response_parts.append(f"\n**Products eliminated:** {len(state.eliminated)}")
            
            # Build data payload
            data = {
                "phase": state.phase.value,
                "products_total": len(state.all_product_ids),
                "products_remaining": state.products_remaining,
                "products_eliminated": len(state.eliminated),
                "questions_asked": state.questions_asked,
                "criteria": state.criteria,
                "candidate_ids": state.candidate_ids,
                "can_undo": await self._state_manager.can_undo(session_id, user_id),
                "can_redo": await self._state_manager.can_redo(session_id, user_id),
                "started_at": state.started_at.isoformat() if state.started_at else None,
                "updated_at": state.updated_at.isoformat() if state.updated_at else None
            }
            
            # Include history if requested
            if include_history:
                history = await self._state_manager.get_history_summary(session_id, user_id)
                data["history"] = history
                
                if history:
                    response_parts.append("\n**Selection History:**")
                    for step in history:
                        marker = "→" if step.get("is_current") else " "
                        response_parts.append(
                            f"{marker} Step {step['step']}: {step['action']}"
                        )
            
            # Include product details if requested
            if include_products and state.candidate_ids:
                products = await self._catalog.get_products(state.candidate_ids[:10])
                data["products"] = [
                    {
                        "id": p.product_id,
                        "name": p.name,
                        "price": p.price,
                        "footprint": p.dimensions.footprint if p.dimensions else None
                    }
                    for p in products
                ]
                
                response_parts.append("\n**Remaining Products:**")
                for p in products[:5]:
                    price_str = f"${p.price:,.0f}" if p.price else "N/A"
                    response_parts.append(f"- {p.name} ({price_str})")
                
                if len(products) > 5:
                    response_parts.append(f"  ... and {len(products) - 5} more")
            
            return self._success_result(
                "\n".join(response_parts),
                data=data
            )
            
        except Exception as e:
            self.logger.error(f"Error getting state: {e}")
            return self._error_result(f"Failed to get selection state: {str(e)}")