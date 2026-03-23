# parrot/advisors/tools/criteria.py
"""
ApplyCriteriaTool - Applies user's answer to filter products.
"""
from typing import Optional, Any, Dict
from pydantic import Field

from ...tools.abstract import ToolResult
from .base import BaseAdvisorTool, ProductAdvisorToolArgs
from .utils import infer_criteria_from_response


class ApplyCriteriaArgs(ProductAdvisorToolArgs):
    """Arguments for applying criteria from user's answer."""
    question_id: Optional[str] = Field(
        None,
        description="ID of the question being answered (helps with response parsing)"
    )
    user_response: str = Field(
        ...,
        description="The user's actual text response/message (e.g., 'I want a large shed', 'under $500'). Do NOT use 'user_id' or 'session_id' here."
    )
    criteria_key: Optional[str] = Field(
        None,
        description="Explicit criteria key to set (optional, auto-detected from question)"
    )
    criteria_value: Optional[Any] = Field(
        None,
        description="Explicit criteria value to set (optional, auto-parsed from response)"
    )


class ApplyCriteriaTool(BaseAdvisorTool):
    """
    Applies the user's answer to filter products and update selection state.
    
    This tool:
    1. Parses the user's response to extract criteria
    2. Filters products based on the criteria
    3. Updates the selection state with new criteria
    4. Creates a Memento snapshot for undo capability
    
    Use this after the user answers a question to narrow down products.
    """
    
    name: str = "apply_selection_criteria"
    description: str = (
        "Apply the user's answer to filter products. Call this after the user responds "
        "to a selection question. Automatically parses the response and filters products."
    )
    args_schema = ApplyCriteriaArgs
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        user_response: str,
        question_id: Optional[str] = None,
        criteria_key: Optional[str] = None,
        criteria_value: Optional[Any] = None,
        **kwargs
    ) -> ToolResult:
        """Execute the apply criteria tool."""
        try:
            # Get current state
            state, error = await self._get_state_or_error(user_id, session_id)
            if error:
                 # Auto-start logic: If no session, try to start one using the response as context
                 if "No active product selection session" in error.error:
                     self.logger.info(f"Auto-starting session for user {user_id} based on apply_criteria")
                     
                     # Infer criteria to see if we have enough to start (or just start generic)
                     inferred = infer_criteria_from_response(user_response)
                     
                     # Always start a new session if auto-start triggered
                     # Use inferred criteria as context if available, or just the raw response
                     product_ids = await self._catalog.get_all_product_ids()
                     state = await self._state_manager.create_state(
                         session_id=session_id,
                         user_id=user_id,
                         catalog_id=self._catalog.catalog_id,
                         product_ids=product_ids,
                         metadata={"initial_context": user_response}
                     )
                     # Valid state created, continue to execution
                 else:
                     return error
            
            # Parse the response to get criteria
            parsed_criteria = {}
            question = None
            
            if question_id and self._question_set:
                question = self._question_set.get_question(question_id)
                if question:
                    parsed_criteria = question.parse_response(user_response) or {}
            
            # Use explicit criteria if provided
            if criteria_key and criteria_value is not None:
                parsed_criteria[criteria_key] = criteria_value
            
            # If still no criteria, try to infer from response
            if not parsed_criteria:
                parsed_criteria = infer_criteria_from_response(user_response)
            
            if not parsed_criteria:
                return self._success_result(
                    "I couldn't understand that response. Could you please clarify? "
                    f"You can say things like: {self._get_example_responses(question)}",
                    data={
                        "parse_failed": True,
                        "original_response": user_response,
                        "question_id": question_id
                    }
                )
            
            # Filter products based on criteria
            matching_ids, eliminated = await self._catalog.filter_products(
                product_ids=state.candidate_ids,
                criteria=parsed_criteria
            )
            
            # Handle case where filter results in 0 products
            if len(matching_ids) == 0:
                # Don't save the 0-result state - just inform user
                criteria_key_used = list(parsed_criteria.keys())[0]
                criteria_value_used = parsed_criteria[criteria_key_used]
                
                return self._success_result(
                    f"That filter ('{criteria_key_used}': '{criteria_value_used}') would eliminate all "
                    f"{state.products_remaining} remaining products. I won't apply it. "
                    f"Try a different option, or say 'undo' to go back to where you had more products.",
                    data={
                        "filter_rejected": True,
                        "reason": "would eliminate all products",
                        "criteria_attempted": parsed_criteria,
                        "products_before": state.products_remaining,
                        "products_after": state.products_remaining,  # Unchanged
                        "eliminated_count": 0,
                        "candidate_ids": state.candidate_ids,  # Preserved
                        "can_undo": await self._state_manager.can_undo(session_id, user_id),
                        "phase": state.phase.value
                    }
                )
            
            # Apply criteria to state (creates Memento snapshot)
            criteria_key_used = list(parsed_criteria.keys())[0]
            criteria_value_used = parsed_criteria[criteria_key_used]
            
            updated_state, eliminated_count = await self._state_manager.apply_criteria(
                session_id=session_id,
                user_id=user_id,
                criteria_key=criteria_key_used,
                criteria_value=criteria_value_used,
                question=question.question_text if question else None,
                answer=user_response,
                products_to_keep=matching_ids
            )
            
            # Build response
            response_parts = []
            
            # Acknowledge with follow-up text if available
            if question and question.follow_up_text:
                response_parts.append(question.follow_up_text)
            else:
                response_parts.append("Got it!")
            
            # Report filtering results
            if eliminated_count > 0:
                response_parts.append(
                    f"That narrows it down from {state.products_remaining} to "
                    f"{updated_state.products_remaining} products."
                )
            else:
                response_parts.append(
                    f"All {updated_state.products_remaining} remaining products still match."
                )
            
            # Check if we should recommend
            should_recommend = updated_state.products_remaining <= 3
            if should_recommend:
                response_parts.append(
                    f"\nWe're down to {updated_state.products_remaining} options! "
                    "Would you like me to compare them or make a recommendation?"
                )
            
            return self._success_result(
                " ".join(response_parts),
                data={
                    "criteria_applied": parsed_criteria,
                    "products_before": state.products_remaining,
                    "products_after": updated_state.products_remaining,
                    "eliminated_count": eliminated_count,
                    "eliminated_products": eliminated,
                    "candidate_ids": updated_state.candidate_ids,
                    "should_recommend": should_recommend,
                    "can_undo": await self._state_manager.can_undo(session_id, user_id),
                    "phase": updated_state.phase.value
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error applying criteria: {e}")
            return self._error_result(f"Failed to apply criteria: {str(e)}")
    
    def _get_example_responses(self, question) -> str:
        """Get example valid responses for a question."""
        if question and question.example_answers:
            return ", ".join(f'"{ex}"' for ex in question.example_answers[:3])
        
        if question and question.options:
            return ", ".join(f'"{opt.label}"' for opt in question.options[:3])
        
        return '"storage", "10x12 feet", "under $2000"'