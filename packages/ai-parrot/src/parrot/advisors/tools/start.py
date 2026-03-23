# parrot/advisors/tools/start.py
"""
StartSelectionTool - Initiates a product selection wizard session.
"""
from typing import Optional, List
from pydantic import Field
from ...tools.abstract import ToolResult
from .base import (
    BaseAdvisorTool,
    BaseAdvisorTool,
    ProductAdvisorToolArgs
)
from .utils import infer_criteria_from_response


class StartSelectionArgs(ProductAdvisorToolArgs):
    """Arguments for starting a product selection session."""
    category: Optional[str] = Field(
        None,
        description="Optional category to filter products (e.g., 'sheds', 'storage')"
    )
    context: Optional[str] = Field(
        None,
        description="Optional context about what the user is looking for"
    )
    force_restart: bool = Field(
        False,
        description="If True, clears any existing session and starts fresh."
    )


class StartSelectionTool(BaseAdvisorTool):
    """
    Initiates a new product selection wizard session.
    
    This tool:
    1. Loads all products from the catalog (optionally filtered by category)
    2. Creates a new selection state in Redis
    3. Returns the first question to ask the user
    
    Use this when the user says things like:
    - "Help me choose a product"
    - "I need help finding the right shed"
    - "What product would you recommend?"
    - "I'm looking for..."
    - "Start over"
    - "Restart"
    - "Clear session"
    """
    
    name: str = "start_product_selection"
    description: str = (
        "Start a guided product selection session. Call this when the user wants help "
        "choosing a product or asks for recommendations. Returns the first question to ask."
    )
    args_schema = StartSelectionArgs
    
    async def _execute(
        self,
        user_id: str,
        session_id: str,
        category: Optional[str] = None,
        context: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Execute the start selection tool."""
        try:
            # Check if there's already an active session
            existing_state = None
            if not kwargs.get("force_restart", False):
                existing_state = await self._state_manager.get_state(session_id, user_id)
            
            # Auto-restart if session exists but has 0 products (dead end)
            if existing_state and existing_state.products_remaining == 0:
                self.logger.info("Existing session has 0 products. Auto-restarting.")
                existing_state = None

            if existing_state and existing_state.phase not in ("completed", "idle"):
                # If we have new context or category, try to update the existing session
                if context or category:
                    criteria = {}
                    if context:
                        criteria.update(infer_criteria_from_response(context))
                    if category:
                        criteria["category"] = category
                    
                    if criteria:
                        # Apply inferred criteria to existing session
                        first_key = list(criteria.keys())[0]
                        first_val = criteria[first_key]
                        
                        updated_state, eliminated = await self._state_manager.apply_criteria(
                            session_id=session_id,
                            user_id=user_id,
                            criteria_key=first_key,
                            criteria_value=first_val,
                            question=None, # Inferred from context
                            answer=context or f"Selected category {category}"
                        )
                        
                        return self._success_result(
                            f"I've updated your existing session. {eliminated} products were removed based on '{context or category}'. "
                            f"You have {updated_state.products_remaining} products remaining. "
                            f"Let's continue!",
                            data={
                                "session_updated": True,
                                "criteria_applied": criteria,
                                "products_remaining": updated_state.products_remaining
                            }
                        )

                # Otherwise, offer to continue or restart
                return self._success_result(
                    f"You already have an active selection session with {existing_state.products_remaining} "
                    f"products remaining. Would you like to continue where you left off, or start fresh?",
                    data={
                        "has_existing_session": True,
                        "products_remaining": existing_state.products_remaining,
                        "criteria_collected": existing_state.criteria,
                        "phase": existing_state.phase.value
                    }
                )
            
            # Load products from catalog
            product_ids = await self._catalog.get_all_product_ids(category=category)
            
            if not product_ids:
                return self._error_result(
                    f"No products found{' in category ' + category if category else ''}. "
                    "Please check the catalog."
                )
            
            # Create new selection state
            metadata = {}
            if context:
                metadata["initial_context"] = context
            if category:
                metadata["category_filter"] = category

            # -------------------------------------------------------------
            # NEW: Apply initial context filters immediately
            # -------------------------------------------------------------
            applied_initial_criteria = {}
            if context:
                inferred = infer_criteria_from_response(context)
                if inferred:
                    matching_ids, eliminated = await self._catalog.filter_products(
                        product_ids=product_ids,
                        criteria=inferred
                    )
                    # Only apply filter if it doesn't eliminate EVERYTHING or NOTHING
                    if 0 < len(matching_ids) < len(product_ids):
                         product_ids = matching_ids
                         applied_initial_criteria = inferred
                         metadata["initial_criteria"] = inferred
                         self.logger.info(f"Applied initial criteria from context: {inferred}")
                    elif len(matching_ids) == 0:
                         # Filter eliminated everything. We should notify the user but proceed with full list.
                         self.logger.info(f"Initial criteria {inferred} eliminated all products. Ignoring.")
                         metadata["failed_initial_criteria"] = inferred
                         
            state = await self._state_manager.create_state(
                session_id=session_id,
                user_id=user_id,
                catalog_id=self._catalog.catalog_id,
                product_ids=product_ids,
                metadata=metadata
            )
            
            # If we applied criteria, recording it in the state history as "initial filter"
            if applied_initial_criteria:
                # We artificially "apply" them to the state's criteria map so the bot knows
                first_key = list(applied_initial_criteria.keys())[0]
                first_val = applied_initial_criteria[first_key]
                
                # We re-apply via manager to ensure history/state consistency
                # (although we already filtered the IDs passed to create_state, 
                #  we need the state object to reflect that these criteria are active)
                
                # Actually, simplest way: Just update the state's criteria dict directly 
                # since we filtered the seed list.
                # However, cleaner for Memento is to call apply_criteria on the fresh state.
                
                # Let's do a loop for all criteria
                for k, v in applied_initial_criteria.items():
                     await self._state_manager.apply_criteria(
                        session_id=session_id,
                        user_id=user_id,
                        criteria_key=k, 
                        criteria_value=v,
                        question=None,
                        answer=context,
                        products_to_keep=None # Already filtered
                    )
            
            # Get the first question
            first_question = None
            if self._question_set:
                first_question = self._question_set.get_next_question(
                    asked_ids=[],
                    current_criteria={},
                    remaining_products=len(product_ids)
                )
            
            # Build response
            response_parts = []
            
            if metadata.get("failed_initial_criteria"):
                crit = metadata["failed_initial_criteria"]
                # Create readable string of failed criteria
                failed_str = ", ".join(f"{k}='{v}'" for k, v in crit.items())
                response_parts.append(
                    f"I couldn't find any products matching those specific requirements ({failed_str}). "
                    f"However, I can help you find the best match from our {len(product_ids)} available options."
                )
            else:
                response_parts.append(
                    f"I'll help you find the perfect product from our {len(product_ids)} options."
                )
                
            response_parts.append("Let me ask you a few questions to narrow things down.")
            
            question_data = None
            if first_question:
                response_parts.append("")
                response_parts.append(first_question.format_for_text())
                question_data = {
                    "question_id": first_question.question_id,
                    "question_text": first_question.question_text,
                    "question_text_voice": first_question.question_text_voice,
                    "answer_type": first_question.answer_type.value,
                    "options": [
                        {"label": opt.label, "value": opt.value, "description": opt.description}
                        for opt in (first_question.options or [])
                    ],
                    "category": first_question.category.value
                }
            
            return self._success_result(
                "\n".join(response_parts),
                data={
                    "session_started": True,
                    "total_products": len(product_ids),
                    "catalog_id": self._catalog.catalog_id,
                    "first_question": question_data,
                    "phase": state.phase.value
                }
            )
            
        except Exception as e:
            self.logger.error(f"Error starting selection: {e}")
            return self._error_result(f"Failed to start selection: {str(e)}")