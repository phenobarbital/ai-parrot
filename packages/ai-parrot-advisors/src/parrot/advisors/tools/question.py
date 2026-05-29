# parrot/advisors/tools/question.py
"""
GetNextQuestionTool - Returns the next optimal question to ask.
"""
from typing import Optional
from pydantic import Field

from ...tools.abstract import ToolResult
from .base import (
    BaseAdvisorTool,
    ProductAdvisorToolArgs
)


class GetNextQuestionArgs(ProductAdvisorToolArgs):
    """Arguments for getting the next question."""
    force_category: Optional[str] = Field(
        None,
        description="Optionally force a specific question category (use_case, space, budget, feature)"
    )


class GetNextQuestionTool(BaseAdvisorTool):
    """
    Returns the next optimal question to ask the user.
    
    This tool considers:
    - Questions already asked
    - Criteria already collected
    - Number of remaining products
    - Question dependencies and conditions
    
    Use this when you need to continue the selection process
    after processing the user's previous answer.
    """
    
    name: str = "get_next_question"
    description: str = (
        "Get the next question to ask in the product selection process. "
        "Call this after applying criteria from the user's previous answer."
    )
    args_schema = GetNextQuestionArgs
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        force_category: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Execute the get next question tool."""
        try:
            # Get current state
            state, error = await self._get_state_or_error(user_id, session_id)
            if error:
                return error
            
            # Check if we should recommend instead
            if state.products_remaining <= 3:
                return self._success_result(
                    f"We've narrowed it down to {state.products_remaining} products. "
                    "Would you like me to show you a comparison or make a recommendation?",
                    data={
                        "should_recommend": True,
                        "products_remaining": state.products_remaining,
                        "candidate_ids": state.candidate_ids,
                        "phase": state.phase.value
                    }
                )
            
            # Get next question
            next_question = None
            if self._question_set:
                # Filter by category if requested
                if force_category:
                    from ..questions import QuestionCategory
                    try:
                        category = QuestionCategory(force_category.lower())
                        category_questions = self._question_set.get_questions_by_category(category)
                        for q in category_questions:
                            if q.question_id not in state.questions_asked:
                                next_question = q
                                break
                    except ValueError:
                        pass  # Invalid category, fall through to normal selection
                
                if not next_question:
                    next_question = self._question_set.get_next_question(
                        asked_ids=state.questions_asked,
                        current_criteria=state.criteria,
                        remaining_products=state.products_remaining
                    )
            
            if not next_question:
                # No more questions, suggest recommendation
                return self._success_result(
                    f"I've asked all my questions! We have {state.products_remaining} products that match. "
                    "Would you like me to compare them or make a recommendation?",
                    data={
                        "no_more_questions": True,
                        "products_remaining": state.products_remaining,
                        "candidate_ids": state.candidate_ids,
                        "criteria_collected": state.criteria
                    }
                )
            
            # Return the question
            return self._success_result(
                next_question.format_for_text(),
                data={
                    "question_id": next_question.question_id,
                    "question_text": next_question.question_text,
                    "question_text_voice": next_question.question_text_voice,
                    "answer_type": next_question.answer_type.value,
                    "options": [
                        {"label": opt.label, "value": opt.value, "description": opt.description}
                        for opt in (next_question.options or [])
                    ],
                    "category": next_question.category.value,
                    "maps_to_feature": next_question.maps_to_feature,
                    "products_remaining": state.products_remaining,
                    "questions_asked_count": len(state.questions_asked)
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error getting next question: {e}")
            return self._error_result(f"Failed to get next question: {str(e)}")