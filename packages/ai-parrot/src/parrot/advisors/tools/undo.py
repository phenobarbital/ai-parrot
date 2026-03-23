# parrot/advisors/tools/undo.py
"""
UndoSelectionTool - Reverts to the previous selection state (Memento pattern).
"""
from pydantic import Field

from ...tools.abstract import ToolResult
from .base import BaseAdvisorTool, ProductAdvisorToolArgs


class UndoSelectionArgs(ProductAdvisorToolArgs):
    """Arguments for undo operation."""
    steps: int = Field(
        default=1,
        description="Number of steps to undo (default: 1)",
        ge=1,
        le=10
    )


class UndoSelectionTool(BaseAdvisorTool):
    """
    Reverts the product selection to a previous state.
    
    Uses the Memento pattern to restore:
    - Previous criteria
    - Previous candidate products
    - Previous questions asked
    
    Use this when the user wants to:
    - Go back and change an answer
    - Undo their last choice
    - Start over from a previous point
    """
    
    name: str = "undo_selection"
    description: str = (
        "Undo the last answer/criteria in the product selection. "
        "Use when the user wants to go back, change their answer, or reconsider."
    )
    args_schema = UndoSelectionArgs
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        steps: int = 1,
        **kwargs
    ) -> ToolResult:
        """Execute the undo tool."""
        try:
            # Check if undo is possible
            can_undo = await self._state_manager.can_undo(session_id, user_id)
            
            if not can_undo:
                return self._success_result(
                    "Nothing to undo - you're at the beginning of the selection process.",
                    data={"can_undo": False, "steps_undone": 0}
                )
            
            # Perform undo(s)
            undone_actions = []
            final_state = None
            
            for i in range(steps):
                state, action = await self._state_manager.undo(session_id, user_id)
                if state:
                    final_state = state
                    undone_actions.append(action)
                else:
                    break
            
            if not final_state:
                return self._error_result("Failed to undo - state could not be restored.")
            
            # Build response
            if len(undone_actions) == 1:
                response = f"Done! I've undone: {undone_actions[0]}."
            else:
                response = f"Done! I've undone {len(undone_actions)} steps."
            
            response += f" You now have {final_state.products_remaining} products to consider."
            
            # Get the next question to re-ask
            next_question = None
            if self._question_set:
                next_question = self._question_set.get_next_question(
                    asked_ids=final_state.questions_asked,
                    current_criteria=final_state.criteria,
                    remaining_products=final_state.products_remaining
                )
            
            if next_question:
                response += f"\n\nLet me ask again: {next_question.format_for_text()}"
            
            return self._success_result(
                response,
                data={
                    "steps_undone": len(undone_actions),
                    "undone_actions": undone_actions,
                    "products_remaining": final_state.products_remaining,
                    "criteria": final_state.criteria,
                    "can_undo_more": await self._state_manager.can_undo(session_id, user_id),
                    "can_redo": await self._state_manager.can_redo(session_id, user_id),
                    "next_question": {
                        "question_id": next_question.question_id,
                        "question_text": next_question.question_text
                    } if next_question else None
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error during undo: {e}")
            return self._error_result(f"Failed to undo: {str(e)}")


class RedoSelectionTool(BaseAdvisorTool):
    """
    Re-applies a previously undone action.
    
    Use this when the user changes their mind after undoing.
    """
    
    name: str = "redo_selection"
    description: str = (
        "Redo a previously undone action in the product selection. "
        "Use after undo if the user changes their mind."
    )
    args_schema = UndoSelectionArgs  # Same args as undo
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        steps: int = 1,
        **kwargs
    ) -> ToolResult:
        """Execute the redo tool."""
        try:
            can_redo = await self._state_manager.can_redo(session_id, user_id)
            
            if not can_redo:
                return self._success_result(
                    "Nothing to redo - you're at the latest state.",
                    data={"can_redo": False, "steps_redone": 0}
                )
            
            redone_actions = []
            final_state = None
            
            for i in range(steps):
                state, action = await self._state_manager.redo(session_id, user_id)
                if state:
                    final_state = state
                    redone_actions.append(action)
                else:
                    break
            
            if not final_state:
                return self._error_result("Failed to redo - state could not be restored.")
            
            response = f"Restored! {', '.join(redone_actions)}. "
            response += f"You now have {final_state.products_remaining} products."
            
            return self._success_result(
                response,
                data={
                    "steps_redone": len(redone_actions),
                    "redone_actions": redone_actions,
                    "products_remaining": final_state.products_remaining,
                    "criteria": final_state.criteria,
                    "can_undo": await self._state_manager.can_undo(session_id, user_id),
                    "can_redo": await self._state_manager.can_redo(session_id, user_id)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error during redo: {e}")
            return self._error_result(f"Failed to redo: {str(e)}")