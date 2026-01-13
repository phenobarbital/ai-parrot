# parrot/advisors/mixin.py
from typing import Optional, List, Dict, Any, Type, Union
from abc import ABC

from ..tools.abstract import AbstractTool
from ..stores.abstract import AbstractStore
from .manager import SelectionStateManager
from .catalog import ProductCatalog
from .questions import QuestionSet
from .tools import (
    StartSelectionTool,
    GetNextQuestionTool,
    ApplyCriteriaTool,
    CompareProductsTool,
    UndoSelectionTool,
    GetCurrentStateTool,
    RecommendProductTool,
    SearchProductsTool,
    GetProductDetailsTool,
)


class ProductAdvisorMixin:
    """
    Mixin that adds product selection wizard capabilities to any Bot/Agent.

    Features:
    - Guided product selection through discriminant questions
    - State management with Redis
    - Undo/redo support via Memento pattern
    - Works with VoiceBot and text chatbots

    Usage:
        class MyProductBot(ProductAdvisorMixin, BasicAgent):
            pass

        bot = MyProductBot(
            name="Product Advisor",
            llm="google:gemini-2.0-flash",
            catalog=my_catalog,  # ProductCatalog instance
        )
        await bot.configure()

    Or with VoiceBot:
        class VoiceAdvisor(ProductAdvisorMixin, VoiceBot):
            pass
    """

    # Mixin state
    _product_catalog: Optional[ProductCatalog] = None
    _selection_manager: Optional[SelectionStateManager] = None
    _question_set: Optional[QuestionSet] = None
    _advisor_tools: List[AbstractTool] = []

    def __init__(
        self,
        *args,
        catalog: Optional[ProductCatalog] = None,
        catalog_id: str = "default",
        vector_store: Optional[AbstractStore] = None,
        selection_manager: Optional[SelectionStateManager] = None,
        question_set: Optional[QuestionSet] = None,
        auto_register_tools: bool = True,
        **kwargs
    ):
        """
        Initialize ProductAdvisorMixin.

        Args:
            catalog: Pre-configured ProductCatalog
            catalog_id: Identifier for multi-tenant catalogs
            vector_store: Vector store for product embeddings
            selection_manager: Custom state manager (uses default Redis if None)
            question_set: Pre-generated questions (generates if None)
            auto_register_tools: Whether to auto-register advisor tools
        """
        # Store advisor config before calling super().__init__
        self._catalog_id = catalog_id
        if catalog:
            self._product_catalog = catalog
        if vector_store:
            self._vector_store = vector_store
        if selection_manager:
            self._selection_manager = selection_manager
        if question_set:
            self._question_set = question_set
        self._auto_register_tools = auto_register_tools

        # Call parent init
        super().__init__(*args, **kwargs)

    async def configure_advisor(
        self,
        catalog: Optional[ProductCatalog] = None,
        question_set: Optional[QuestionSet] = None,
    ) -> None:
        """
        Configure the product advisor components.

        Call this after bot.configure() or override configure() to call it.
        """
        # Initialize catalog
        self._product_catalog = catalog or self._product_catalog
        if not self._product_catalog and self._vector_store:
            # Special configuration for gorillashed catalog
            catalog_kwargs = {}
            if self._catalog_id == "gorillashed":
                catalog_kwargs["schema"] = "gorillashed"
                catalog_kwargs["table"] = "products"

            self._product_catalog = ProductCatalog(
                catalog_id=self._catalog_id,
                vector_store=self.store,
                **catalog_kwargs
            )

        if not self._product_catalog:
            raise ValueError(
                "ProductAdvisorMixin requires either a 'catalog' or 'vector_store'"
            )

        # Initialize state manager
        self._selection_manager = (
            self._selection_manager or SelectionStateManager()
        )

        # Initialize or generate question set
        self._question_set = (
            question_set or self._question_set or await self._generate_questions()
        )

        # Register tools
        if self._auto_register_tools:
            await self._register_advisor_tools()

    async def _generate_questions(self) -> QuestionSet:
        """
        Generate discriminant questions using LLM.

        This analyzes the product catalog and creates optimal questions.
        Should be called once per catalog and cached.
        """
        from .generator import generate_discriminant_questions
        from ..clients.factory import SUPPORTED_CLIENTS

        products = await self._product_catalog.get_all_products()

        # For VoiceBot, _llm is GeminiLiveClient which has different ask() signature.
        # If bot has ask_text() method, use text LLM for question generation.
        llm = getattr(self, '_llm', None) or getattr(self, 'llm', None)

        # Check if LLM is a voice-only client (GeminiLiveClient has stream_voice)
        if llm and hasattr(llm, 'stream_voice'):
            # Create a text-based LLM for question generation
            # Note: Don't use llm.model as it's an audio-only model
            GoogleGenAIClient = SUPPORTED_CLIENTS.get('google')
            if GoogleGenAIClient:
                llm = GoogleGenAIClient(
                    model='gemini-2.5-flash',
                    temperature=0.3,
                )
                self.logger.debug("Using text LLM for question generation (voice LLM not compatible)")

        if not llm:
            raise ValueError("No LLM available for question generation")

        return await generate_discriminant_questions(
            products=products,
            llm=llm,
            catalog_id=self._catalog_id
        )

    async def _register_advisor_tools(self) -> None:
        """Register all product advisor tools."""
        self._advisor_tools = [
            # Search/lookup tools (for answering direct questions)
            SearchProductsTool(
                catalog=self._product_catalog,
            ),
            GetProductDetailsTool(
                catalog=self._product_catalog,
            ),
            # Selection workflow tools
            StartSelectionTool(
                catalog=self._product_catalog,
                state_manager=self._selection_manager,
            ),
            GetNextQuestionTool(
                question_set=self._question_set,
                state_manager=self._selection_manager,
            ),
            ApplyCriteriaTool(
                catalog=self._product_catalog,
                state_manager=self._selection_manager,
                question_set=self._question_set,
            ),
            CompareProductsTool(
                catalog=self._product_catalog,
                state_manager=self._selection_manager,
            ),
            UndoSelectionTool(
                state_manager=self._selection_manager,
            ),
            GetCurrentStateTool(
                state_manager=self._selection_manager,
                catalog=self._product_catalog,
            ),
            RecommendProductTool(
                catalog=self._product_catalog,
                state_manager=self._selection_manager,
            ),
        ]

        # Register with the bot's tool manager
        tool_manager = getattr(self, 'tool_manager')
        for tool in self._advisor_tools:
            tool_manager.register_tool(tool)

        # Sync tools to the LLM client's tool manager
        llm = getattr(self, '_llm', None)
        if llm and hasattr(self, '_sync_tools_to_llm'):
            self._sync_tools_to_llm(llm)
            # Enable tools on the LLM client (may have been False at creation time)
            llm.enable_tools = True
            self.logger.info(
                f"Synced {len(self._advisor_tools)} advisor tools to LLM (enable_tools=True)"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Convenience Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def start_product_selection(
        self,
        user_id: str,
        session_id: str,
        category: Optional[str] = None,
    ) -> str:
        """
        Start a new product selection session.

        Returns welcome message with first question.
        """
        products = await self._product_catalog.get_all_products(category=category)
        product_ids = [p.product_id for p in products]

        state = await self._selection_manager.create_state(
            session_id=session_id,
            user_id=user_id,
            catalog_id=self._catalog_id,
            product_ids=product_ids
        )

        # Get first question
        first_question = self._question_set.get_next_question(
            asked=[],
            criteria={},
            remaining_products=len(product_ids)
        )

        return (
            f"Great! I'll help you find the perfect product. "
            f"I have {len(product_ids)} options to consider. "
            f"Let me ask you a few questions to narrow it down.\n\n"
            f"{first_question.format_for_text() if first_question else 'What are you looking for?'}"
        )

    async def undo_last_answer(
        self,
        user_id: str,
        session_id: str,
    ) -> str:
        """Undo the last answer and restore previous state."""
        state, action = await self._selection_manager.undo(session_id, user_id)

        if state:
            return (
                f"No problem! I've undone: {action}. "
                f"You now have {state.products_remaining} products to consider. "
                f"What would you like to do?"
            )
        return "Nothing to undo - you're at the beginning of the selection."

    @property
    def product_catalog(self) -> Optional[ProductCatalog]:
        """Access the product catalog."""
        return self._product_catalog

    @property
    def selection_manager(self) -> Optional[SelectionStateManager]:
        """Access the selection state manager."""
        return self._selection_manager
