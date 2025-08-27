"""
Abstract Bot interface.
"""
from abc import ABC
import contextlib
import importlib
from typing import Any, Dict, List, Union, Optional
from collections.abc import Callable
import uuid
from string import Template
import asyncio
import copy
from aiohttp import web
from navconfig.logging import logging
from navigator_auth.conf import AUTH_SESSION_OBJECT

from parrot.tools.math import MathTool  # pylint: disable=E0611
from ..interfaces import DBInterface
from ..exceptions import ConfigError  # pylint: disable=E0611
from ..conf import (
    EMBEDDING_DEFAULT_MODEL
)
from ..utils import SafeDict
from .prompts import (
    BASIC_SYSTEM_PROMPT,
    BASIC_HUMAN_PROMPT,
    DEFAULT_GOAL,
    DEFAULT_ROLE,
    DEFAULT_CAPABILITIES,
    DEFAULT_BACKHISTORY
)
from ..clients import LLM_PRESETS, SUPPORTED_CLIENTS, AbstractClient
from ..models import (
    AIMessage,
    SourceDocument
)
from ..stores import AbstractStore, supported_stores
from ..stores.models import Document
from ..tools import AbstractTool
from ..tools.manager import ToolManager, ToolFormat, ToolDefinition
from ..memory import (
    ConversationMemory,
    ConversationTurn,
    ConversationHistory,
    InMemoryConversation,
    FileConversationMemory,
    RedisConversation,
)


logging.getLogger(name='primp').setLevel(logging.INFO)
logging.getLogger(name='rquest').setLevel(logging.INFO)
logging.getLogger("grpc").setLevel(logging.CRITICAL)


class AbstractBot(DBInterface, ABC):
    """AbstractBot.

    This class is an abstract representation a base abstraction for all Chatbots.
    """
    # Define system prompt template
    system_prompt_template = BASIC_SYSTEM_PROMPT
    # Define human prompt template
    human_prompt_template = BASIC_HUMAN_PROMPT
    _default_llm: str = 'google'

    def __init__(
        self,
        name: str = 'Nav',
        system_prompt: str = None,
        human_prompt: str = None,
        use_tools: bool = True,
        tools: List[Union[str, AbstractTool]] = None,
        tool_threshold: float = 0.7,  # Confidence threshold for tool usage,
        debug: bool = False,
        **kwargs
    ):
        """Initialize the Chatbot with the given configuration."""
        self._request: Optional[web.Request] = None

        # System and Human Prompts:
        if system_prompt:
            self.system_prompt_template = system_prompt or self.system_prompt_template
        if human_prompt:
            self.human_prompt_template = human_prompt or self.human_prompt_template

        # Debug mode:
        self._debug = debug

        # Chatbot ID:
        self.chatbot_id: uuid.UUID = kwargs.get(
            'chatbot_id',
            str(uuid.uuid4().hex)
        )
        if self.chatbot_id is None:
            self.chatbot_id = str(uuid.uuid4().hex)

        # Basic Bot Information:
        self.name: str = name
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Bot'
        )
        # Agentic Tools:
        self.tools = tools or []
        self.tool_threshold = tool_threshold
        self.enable_tools: bool = use_tools or kwargs.get('enable_tools', True)
        if len(self.tools) > 0:
            self.enable_tools = True
        # Optional aiohttp Application:
        self.app: Optional[web.Application] = None
        # Start initialization:
        self.return_sources: bool = kwargs.pop('return_sources', True)
        # program slug:
        self._program_slug: str = kwargs.pop('program_slug', 'parrot')
        # Bot Attributes:
        self.description = self._get_default_attr(
            'description',
            'Navigator Chatbot',
            **kwargs
        )
        self.role = kwargs.get('role', DEFAULT_ROLE)
        self.goal = kwargs.get('goal', DEFAULT_GOAL)
        self.capabilities = kwargs.get('capabilities', DEFAULT_CAPABILITIES)
        self.backstory = kwargs.get('backstory', DEFAULT_BACKHISTORY)
        self.rationale = kwargs.get('rationale', self.default_rationale())
        self.context = kwargs.get('use_context', True)

        # Definition of LLM Client
        self._llm_model = kwargs.get('model', 'gemini-2.5-flash')
        self._llm_preset: str = kwargs.get('preset', None)
        self._llm: Union[str, Any] = kwargs.get('llm', 'google')
        if isinstance(self._llm, str):
            self._llm = SUPPORTED_CLIENTS.get(self._llm.lower(), None)
        if self._llm:
            with contextlib.suppress(Exception):
                if not issubclass(self._llm, AbstractClient):
                    raise ValueError(
                        f"Invalid LLM Client: {self._llm}. Must be one of {SUPPORTED_CLIENTS.keys()}"
                    )
        if self._llm_preset:
            try:
                presetting = LLM_PRESETS[self._llm_preset]
            except KeyError:
                self.logger.warning(
                    f"Invalid preset: {self._llm_preset}, default to 'default'"
                )
                presetting = LLM_PRESETS['default']
            self._llm_temp = presetting.get('temperature', 0.1)
            self._max_tokens = presetting.get('max_tokens', 1024)
        else:
            # Default LLM Presetting by LLMs
            self._llm_temp = kwargs.get('temperature', 0.1)
            self._max_tokens = kwargs.get('max_tokens', 1024)
        # LLM Configuration:
        self._top_k = kwargs.get('top_k', 41)
        self._top_p = kwargs.get('top_p', 0.9)
        self._llm_config = kwargs.get('model_config', {})
        if self._llm_config:
            self._llm_model = self._llm_config.pop('model', self._llm_model)
            llm = self._llm_config.pop('name', 'google')
            self._llm_temp = self._llm_config.pop('temperature', self._llm_temp)
            self._top_k = self._llm_config.pop('top_k', self._top_k)
            self._top_p = self._llm_config.pop('top_p', self._top_p)
            self._llm = SUPPORTED_CLIENTS.get(llm)
        else:
            self._llm_config = {
                "name":  self._llm,
                "model": self._llm_model,
                "temperature": self._llm_temp,
                "top_k": self._top_k,
                "top_p": self._top_p
            }
        self.context = kwargs.pop('context', '')
        # Pre-Instructions:
        self.pre_instructions: list = kwargs.get(
            'pre_instructions',
            []
        )
        # Operational Mode:
        self.operation_mode: str = kwargs.get('operation_mode', 'adaptive')
        # Knowledge base:
        self.kb = None
        self.knowledge_base: List[str] = []
        self._documents_: list = []
        # Models, Embed and collections
        # Vector information:
        self._use_vector: bool = kwargs.get('use_vectorstore', False)
        self._vector_info_: dict = kwargs.get('vector_info', {})
        self._vector_store: dict = kwargs.get('vector_store_config', None)
        self.chunk_size: int = int(kwargs.get('chunk_size', 2048))
        self.dimension: int = int(kwargs.get('dimension', 384))
        self._metric_type: str = kwargs.get('metric_type', 'COSINE')
        self.store: Callable = None
        # List of Vector Stores:
        self.stores: List[AbstractStore] = []

        # NEW: Unified Conversation Memory System
        self.conversation_memory: Optional[ConversationMemory] = None
        self.memory_type: str = kwargs.get('memory_type', 'memory')  # 'memory', 'file', 'redis'
        self.memory_config: dict = kwargs.get('memory_config', {})

        # Conversation settings
        self.max_context_turns: int = kwargs.get('max_context_turns', 5)
        self.context_search_limit: int = kwargs.get('context_search_limit', 10)
        self.context_score_threshold: float = kwargs.get('context_score_threshold', 0.7)

        # Memory settings
        self.memory: Callable = None
        # Embedding Model Name
        self.embedding_model = kwargs.get(
            'embedding_model',
            {
                'model_name': EMBEDDING_DEFAULT_MODEL,
                'model_type': 'huggingface'
            }
        )
        # embedding object:
        self.embeddings = kwargs.get('embeddings', None)
        # Bot Security and Permissions:
        _default = self.default_permissions()
        _permissions = kwargs.get('permissions', _default)
        if _permissions is None:
            _permissions = {}
        self._permissions = {**_default, **_permissions}

    def set_program(self, program_slug: str) -> None:
        """Set the program slug for the bot."""
        self._program_slug = program_slug

    def get_vector_store(self):
        return self._vector_store

    def default_permissions(self) -> dict:
        """
        Returns the default permissions for the bot.

        This function defines and returns a dictionary containing the default
        permission settings for the bot. These permissions are used to control
        access and functionality of the bot across different organizational
        structures and user groups.

        Returns:
            dict: A dictionary containing the following keys, each with an empty list as its value:
                - "organizations": List of organizations the bot has access to.
                - "programs": List of programs the bot is allowed to interact with.
                - "job_codes": List of job codes the bot is authorized for.
                - "users": List of specific users granted access to the bot.
                - "groups": List of user groups with bot access permissions.
        """
        return {
            "organizations": [],
            "programs": [],
            "job_codes": [],
            "users": [],
            "groups": [],
        }

    def permissions(self):
        return self._permissions

    def get_supported_models(self) -> List[str]:
        return self._llm.get_supported_models()

    def _get_default_attr(self, key, default: Any = None, **kwargs):
        if key in kwargs:
            return kwargs.get(key)
        if hasattr(self, key):
            return getattr(self, key)
        if not hasattr(self, key):
            return default
        return getattr(self, key)

    def __repr__(self):
        return f"<Bot.{self.__class__.__name__}:{self.name}>"

    def default_rationale(self) -> str:
        # TODO: read rationale from a file
        return (
            "** Your Style: **\n"
            "- When responding to user queries, ensure that you provide accurate and up-to-date information.\n"  # noqa: C0301
            "- ensuring that responses are based only on verified information.\n"
        )

    @property
    def llm(self):
        return self._llm

    @llm.setter
    def llm(self, model):
        self._llm = model

    def llm_chain(
        self,
        llm: str = "vertexai",
        model: str = None,
        **kwargs
    ) -> AbstractClient:
        """llm_chain.

        Args:
            llm (str): The language model to use.

        Returns:
            AbstractClient: The language model to use.

        """
        try:
            cls = SUPPORTED_CLIENTS.get(llm.lower(), None)
            if not cls:
                raise ValueError(f"Unsupported LLM: {llm}")
            return cls(model=model, **kwargs)
        except Exception:
            raise

    def configure_llm(
        self,
        llm: Union[str, Callable] = None,
        **kwargs
    ):
        """
        Configuration of LLM.
        """
        if llm is not None:
            # If llm is provided, use it to configure the LLM client
            if isinstance(llm, str):
                # Get the LLM By Name:
                cls = SUPPORTED_CLIENTS.get(llm.lower(), None)
                self._llm = cls(
                    conversation_memory=self.conversation_memory,
                    **kwargs
                )
            elif issubclass(llm, AbstractClient):
                self._llm = llm(
                    conversation_memory=self.conversation_memory,
                    **kwargs
                )
            elif isinstance(llm, AbstractClient):
                # Set conversation memory on existing client
                if hasattr(llm, 'conversation_memory'):
                    llm.conversation_memory = self.conversation_memory
                self._llm = llm
            elif callable(llm):
                self._llm = llm(
                    conversation_memory=self.conversation_memory,
                    **kwargs
                )
            else:
                # TODO: Calling a Default LLM based on name
                # TODO: passing the default configuration
                try:
                    self._llm = self.llm_chain(
                        llm=self._default_llm,
                        model=self._llm_model,
                        temperature=self._llm_temp,
                        top_k=self._top_k,
                        top_p=self._top_p,
                        max_tokens=self._max_tokens,
                    )
                except Exception as e:
                    raise ConfigError(
                        f"Error configuring Default LLM {self._llm_model}: {e}"
                    )
        else:
            if self._llm is None:
                # If no llm is provided, use the default LLM configuration
                try:
                    self._llm = self.llm_chain(
                        llm=self._default_llm,
                        model=self._llm_model,
                        temperature=self._llm_temp,
                        top_k=self._top_k,
                        top_p=self._top_p,
                        max_tokens=self._max_tokens,
                        conversation_memory=self.conversation_memory,
                    )
                except Exception as e:
                    raise ConfigError(
                        f"Error configuring Default LLM {self._llm_model}: {e}"
                    )
            elif isinstance(self._llm, AbstractClient):
                if hasattr(self._llm, 'conversation_memory'):
                    self._llm.conversation_memory = self.conversation_memory
            elif issubclass(self._llm, AbstractClient):
                try:
                    # If _llm is already an AbstractClient subclass, just use it
                    self._llm = self._llm(
                        model=self._llm_model,
                        temperature=self._llm_temp,
                        top_k=self._top_k,
                        top_p=self._top_p,
                        max_tokens=self._max_tokens,
                        conversation_memory=self.conversation_memory,
                        **kwargs
                    )
                except TypeError as e:
                    raise ConfigError(
                        f"Error initializing LLM Client {self._llm.__name__}: {e}"
                    )
        # Register tools directly on client (like your working examples)
        try:
            self._llm.register_tools(self.tools)
            self.logger.info(
                f"Registered {len(self.tools)} tools with LLM client"
            )
        except Exception as e:
            self.logger.error(f"Error registering tools: {e}")

    def define_store(
        self,
        vector_store: str = 'postgres',
        **kwargs
    ):
        """Define the Vector Store."""
        self._use_vector = True
        self._vector_store = {
            "name": vector_store,
            **kwargs
        }

    def configure_store(self, **kwargs):
        """Configure Vector Store."""
        if isinstance(self._vector_store, list):
            for st in self._vector_store:
                try:
                    store_cls = self._get_database_store(st)
                    store_cls.use_database = self._use_vector
                    self.stores.append(store_cls)
                except ImportError:
                    continue
        elif isinstance(self._vector_store, dict):
            store_cls = self._get_database_store(self._vector_store)
            store_cls.use_database = self._use_vector
            self.stores.append(store_cls)
        else:
            raise ValueError(f"Invalid Vector Store Config: {self._vector_store}")

        self.logger.info(f"Configured Vector Stores: {self.stores}")
        if self.stores:
            self.store = self.stores[0]

    def _get_database_store(self, store: dict) -> AbstractStore:
        """Get the VectorStore Class from the store configuration."""
        name = store.get('name', None)
        if not name:
            vector_driver = store.get('vector_database', 'PgVectorStore')
            name = next(
                (k for k, v in supported_stores.items() if v == vector_driver), None
            )
        store_cls = supported_stores.get(name)
        cls_path = f"parrot.stores.{name}"
        try:
            module = importlib.import_module(cls_path, package=name)
            store_cls = getattr(module, store_cls)
            self.logger.notice(
                f"Using VectorStore: {store_cls.__name__} for {name} with Embedding {self.embedding_model}"  # noqa
            )
            if not 'embedding_model' in store:
                store['embedding_model'] = self.embedding_model
            if not 'embedding' in store:
                store['embedding'] = self.embeddings
            try:
                return store_cls(
                    **store
                )
            except Exception as err:
                self.logger.error(
                    f"Error configuring VectorStore: {err}"
                )
                raise
        except (ModuleNotFoundError, ImportError) as e:
            self.logger.error(f"Error importing VectorStore: {e}")
            raise
        except Exception:
            raise

    def configure_conversation_memory(self) -> None:
        """Configure the unified conversation memory system."""
        try:
            self.conversation_memory = self.get_conversation_memory(
                storage_type=self.memory_type,
                **self.memory_config
            )
            self.logger.info(
                f"Configured conversation memory: {self.memory_type}"
            )
        except Exception as e:
            self.logger.error(f"Error configuring conversation memory: {e}")
            # Fallback to in-memory
            self.conversation_memory = self.get_conversation_memory("memory")
            self.logger.warning(
                "Fallback to in-memory conversation storage"
            )

    def _define_prompt(self, config: Optional[dict] = None, **kwargs):
        """
        Define the System Prompt and replace variables.
        """
        # setup the prompt variables:
        if config:
            for key, val in config.items():
                setattr(self, key, val)

        pre_context = ''
        if self.pre_instructions:
            pre_context = "IMPORTANT PRE-INSTRUCTIONS: \n"
            pre_context += "\n".join(f"- {a}." for a in self.pre_instructions)
        tmpl = Template(self.system_prompt_template)
        final_prompt = tmpl.safe_substitute(
            name=self.name,
            role=self.role,
            goal=self.goal,
            capabilities=self.capabilities,
            backstory=self.backstory,
            rationale=self.rationale,
            pre_context=pre_context,
            **kwargs
        )
        self.system_prompt_template = final_prompt

    def create_kb(self, documents: list):
        new_docs = []
        for doc in documents:
            content = doc.pop('content')
            source = doc.pop('source', 'knowledge-base')
            if doc:
                meta = {
                    'source': source,
                    **doc
                }
            else:
                meta = {'source': source}
            if content:
                new_docs.append(
                    Document(
                        page_content=content,
                        metadata=meta
                    )
                )
        return new_docs

    async def configure(self, app=None) -> None:
        """Basic Configuration of Bot.
        """
        self.app = None
        if app:
            if isinstance(app, web.Application):
                self.app = app  # register the app into the Extension
            else:
                self.app = app.get_app()  # Nav Application
        # adding this configured chatbot to app:
        if self.app:
            self.app[f"{self.name.lower()}_bot"] = self

        # Configure conversation memory FIRST
        self.configure_conversation_memory()
        # Configure LLM:
        try:
            self.configure_llm()
        except Exception as e:
            self.logger.error(
                f"Error configuring LLM: {e}"
            )
            raise
        # set Client tools:
        # Log tools configuration AFTER LLM is configured
        tools_summary = self.get_tools_summary()
        self.logger.info(
            f"Configuration complete: "
            f"tools_enabled={tools_summary['tools_enabled']}, "
            f"operation_mode={tools_summary['operation_mode']}, "
            f"tools_count={tools_summary['tools_count']}, "
            f"effective_mode={tools_summary['effective_mode']}"
        )
        # And define Prompt:
        try:
            self._define_prompt()
        except Exception as e:
            self.logger.error(
                f"Error defining prompt: {e}"
            )
            raise
        # Configure VectorStore if enabled:
        if self._use_vector:
            try:
                self.configure_store()
            except Exception as e:
                self.logger.error(
                    f"Error configuring VectorStore: {e}"
                )
                raise

    def get_conversation_memory(
        self,
        storage_type: str = "memory",
        **kwargs
    ) -> ConversationMemory:
        """Factory function to create conversation memory instances."""
        if storage_type == "memory":
            return InMemoryConversation(**kwargs)
        elif storage_type == "file":
            return FileConversationMemory(**kwargs)
        elif storage_type == "redis":
            return RedisConversation(**kwargs)
        else:
            raise ValueError(
                f"Unknown storage type: {storage_type}"
            )

    async def get_conversation_history(
        self,
        user_id: str,
        session_id: str
    ) -> Optional[ConversationHistory]:
        """Get conversation history using unified memory system."""
        if not self.conversation_memory:
            return None
        return await self.conversation_memory.get_history(user_id, session_id)

    async def create_conversation_history(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationHistory:
        """Create new conversation history using unified memory system."""
        if not self.conversation_memory:
            raise RuntimeError("Conversation memory not configured")
        return await self.conversation_memory.create_history(user_id, session_id, metadata)

    async def save_conversation_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn
    ) -> None:
        """Save a conversation turn using unified memory system."""
        if not self.conversation_memory:
            return
        await self.conversation_memory.add_turn(user_id, session_id, turn)

    async def clear_conversation_history(self, user_id: str, session_id: str) -> bool:
        """Clear conversation history using unified memory system."""
        if not self.conversation_memory:
            return False
        try:
            await self.conversation_memory.clear_history(user_id, session_id)
            self.logger.info(f"Cleared conversation history for {user_id}/{session_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing conversation history: {e}")
            return False

    async def delete_conversation_history(self, user_id: str, session_id: str) -> bool:
        """Delete conversation history entirely using unified memory system."""
        if not self.conversation_memory:
            return False
        try:
            result = await self.conversation_memory.delete_history(user_id, session_id)
            self.logger.info(f"Deleted conversation history for {user_id}/{session_id}")
            return result
        except Exception as e:
            self.logger.error(f"Error deleting conversation history: {e}")
            return False

    async def list_user_conversations(self, user_id: str) -> List[str]:
        """List all conversation sessions for a user."""
        if not self.conversation_memory:
            return []
        try:
            return await self.conversation_memory.list_sessions(user_id)
        except Exception as e:
            self.logger.error(f"Error listing conversations for user {user_id}: {e}")
            return []

    def _extract_sources_documents(self, search_results: List[Any]) -> List[SourceDocument]:
        """
        Extract enhanced source information from search results.

        Args:
            search_results: List of SearchResult objects from vector store

        Returns:
            List of SourceDocument objects with full metadata
        """
        enhanced_sources = []
        seen_sources = set()  # To avoid duplicates

        for result in search_results:
            if not hasattr(result, 'metadata') or not result.metadata:
                continue

            metadata = result.metadata

            # Extract primary source identifier
            source = metadata.get('source')
            source_name = metadata.get('source_name', source)
            filename = metadata.get('filename', source_name)

            # Create unique identifier for deduplication
            # Use filename + chunk_index for chunked documents, or just filename for others
            chunk_index = metadata.get('chunk_index')
            if chunk_index is not None:
                unique_id = f"{filename}#{chunk_index}"
            else:
                unique_id = filename

            if unique_id in seen_sources:
                continue

            seen_sources.add(unique_id)

            # Extract document_meta if available
            document_meta = metadata.get('document_meta', {})

            # Build enhanced source document
            source_doc = SourceDocument(
                source=source or filename,
                filename=filename,
                file_path=document_meta.get('file_path') or metadata.get('source_path'),
                source_path=metadata.get('source_path') or document_meta.get('file_path'),
                url=metadata.get('url'),
                content_type=document_meta.get('content_type') or metadata.get('content_type'),
                category=metadata.get('category'),
                source_type=metadata.get('source_type'),
                source_ext=metadata.get('source_ext'),
                page_number=metadata.get('page_number'),
                chunk_id=metadata.get('chunk_id'),
                parent_document_id=metadata.get('parent_document_id'),
                chunk_index=chunk_index,
                score=getattr(result, 'score', None),
                metadata=metadata
            )

            enhanced_sources.append(source_doc)

        return enhanced_sources

    async def get_vector_context(
        self,
        question: str,
        search_type: str = 'similarity',  # 'similarity', 'mmr', 'ensemble'
        search_kwargs: dict = None,
        metric_type: str = 'COSINE',
        limit: int = 10,
        score_threshold: float = None,
        ensemble_config: dict = None,
        return_sources: bool = False,
    ) -> str:
        """Get relevant context from vector store.
        Args:
            question (str): The user's question to search context for.
            search_type (str): Type of search to perform ('similarity', 'mmr', 'ensemble').
            search_kwargs (dict): Additional parameters for the search.
            metric_type (str): Metric type for vector search (e.g., 'COSINE', 'EUCLIDEAN').
            limit (int): Maximum number of context items to retrieve.
            score_threshold (float): Minimum score for context relevance.
            ensemble_config (dict): Configuration for ensemble search.
            return_sources (bool): Whether to extract enhanced source information
        Returns:
            tuple: (context_string, metadata_dict)
        """
        if not self.store:
            return "", {}

        try:
            limit = limit or self.context_search_limit
            score_threshold = score_threshold or self.context_score_threshold
            search_results = None
            metadata = {
                'search_type': search_type,
                'score_threshold': score_threshold,
                'metric_type': metric_type
            }
            self.logger.notice(
                f"Retrieving vector context for question: {question} "
                f"using {search_type} search with limit {limit} "
                f"and score threshold {score_threshold}"
            )
            async with self.store as store:
                # Use the similarity_search method from PgVectorStore
                if search_type == 'mmr':
                    if search_kwargs is None:
                        search_kwargs = {
                            "k": limit,
                            "fetch_k": limit * 2,
                            "lambda_mult": 0.4,
                        }
                    search_results = await store.mmr_search(
                        query=question,
                        score_threshold=score_threshold,
                        **(search_kwargs or {})
                    )
                elif search_type == 'ensemble':
                    # Default ensemble configuration
                    if ensemble_config is None:
                        ensemble_config = {
                            'similarity_limit': max(6, int(limit * 1.2)),  # Get more from similarity
                            'mmr_limit': max(4, int(limit * 0.8)),         # Get fewer but more diverse from MMR
                            'final_limit': limit,                          # Final number to return
                            'similarity_weight': 0.6,                      # Weight for similarity scores
                            'mmr_weight': 0.4,                            # Weight for MMR scores
                            'dedup_threshold': 0.9,                       # Similarity threshold for deduplication
                            'rerank_method': 'weighted_score'             # 'weighted_score', 'rrf', 'interleave'
                        }
                    search_results = await self._ensemble_search(
                        store,
                        question,
                        ensemble_config,
                        score_threshold,
                        metric_type,
                        search_kwargs
                    )
                    metadata.update({
                        'ensemble_config': ensemble_config,
                        'similarity_results_count': len(search_results.get('similarity_results', [])),
                        'mmr_results_count': len(search_results.get('mmr_results', [])),
                        'final_results_count': len(search_results.get('final_results', []))
                    })
                    search_results = search_results['final_results']
                else:
                    # doing a similarity search by default
                    search_results = await store.similarity_search(
                        query=question,
                        limit=limit,
                        score_threshold=score_threshold,
                        metric=metric_type,
                        **(search_kwargs or {})
                    )

            if not search_results:
                metadata['search_results_count'] = 0
                if return_sources:
                    metadata['enhanced_sources'] = []
                return "", metadata

            # Format the context from search results
            context_parts = []
            sources = []
            for i, result in enumerate(search_results):
                context_parts.append(f"[Context {i+1}]: {result.content}")

                # Extract source information
                if hasattr(result, 'metadata') and result.metadata:
                    source_id = result.metadata.get('source', f"result_{i}")
                    sources.append(source_id)

            context = "\n\n".join(context_parts)

            if return_sources:
                source_documents = self._extract_sources_documents(search_results)
                metadata['source_documents'] = [source.to_dict() for source in source_documents]
                metadata['context_sources'] = [source.filename for source in source_documents]
            else:
                # Keep original behavior for backward compatibility
                metadata['context_sources'] = sources
                metadata.update({
                    'search_results_count': len(search_results),
                    'sources': sources
                })

            metadata.update({
                'search_results_count': len(search_results),
                'sources': sources
            })

            self.logger.info(
                f"Retrieved {len(search_results)} context items using {search_type} search"
            )

            return context, metadata

        except Exception as e:
            self.logger.error(
                f"Error retrieving vector context: {e}"
            )
            return "", {
                'search_results_count': 0,
                'search_type': search_type,
                'error': str(e)
            }

    def build_conversation_context(
        self,
        history: ConversationHistory,
        max_chars_per_message: int = 200,
        max_total_chars: int = 1500,
        include_turn_timestamps: bool = False,
        smart_truncation: bool = True
    ) -> str:
        """Build conversation context from history."""
        if not history or not history.turns:
            return ""

        recent_turns = history.get_recent_turns(self.max_context_turns)

        if not recent_turns:
            return ""

        context_parts = []
        total_chars = 0

        for i, turn in enumerate(recent_turns):
            turn_number = len(recent_turns) - i

            # Smart truncation: try to keep complete sentences
            user_msg = self._smart_truncate(
                turn.user_message, max_chars_per_message
            ) if smart_truncation else self._simple_truncate(
                turn.user_message, max_chars_per_message
            )
            assistant_msg = self._smart_truncate(
                turn.assistant_response, max_chars_per_message
            ) if smart_truncation else self._simple_truncate(
                turn.assistant_response,
                max_chars_per_message
            )

            # Build turn with optional timestamp
            turn_parts = [f"=== Turn {turn_number} ==="]

            if include_turn_timestamps and hasattr(turn, 'timestamp'):
                turn_parts.append(f"Time: {turn.timestamp.strftime('%H:%M')}")

            turn_parts.extend([
                f"👤 User: {user_msg}",
                f"🤖 Assistant: {assistant_msg}"
            ])

            turn_text = "\n".join(turn_parts)

            # Check total length
            if total_chars + len(turn_text) > max_total_chars:
                if i == 0:  # Always try to include at least the most recent turn
                    remaining_chars = max_total_chars - 100  # Leave room for formatting
                    if remaining_chars > 200:
                        turn_text = turn_text[:remaining_chars].rstrip() + "\n[...truncated]"
                        context_parts.append(turn_text)
                break

            context_parts.append(turn_text)
            total_chars += len(turn_text)

        if not context_parts:
            return ""

        # Reverse to chronological order
        context_parts.reverse()

        # Add header
        header = f"📋 Recent Conversation ({len(context_parts)} turns):"
        return f"{header}\n\n" + "\n\n".join(context_parts)

    def _smart_truncate(self, text: str, max_length: int) -> str:
        """Truncate text at sentence boundaries when possible."""
        if len(text) <= max_length:
            return text

        # Try to truncate at sentence boundaries
        sentences = text.split('. ')
        truncated = ""

        for sentence in sentences:
            test_text = truncated + sentence + ". " if truncated else sentence + ". "
            if len(test_text) > max_length - 3:  # Leave room for "..."
                break
            truncated = test_text

        # If no complete sentences fit, do character truncation
        if not truncated or len(truncated) < max_length * 0.5:
            truncated = text[:max_length - 3]

        return truncated.rstrip() + "..."

    def _simple_truncate(self, text: str, max_length: int) -> str:
        """Simple character-based truncation."""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3].rstrip() + "..."

    def is_agent_mode(self) -> bool:
        """Check if the bot is configured to operate in agent mode."""
        return (
            self.enable_tools and
            self.has_tools() and
            self.operation_mode in ['agentic', 'adaptive']
        )

    def is_conversational_mode(self) -> bool:
        """Check if the bot is configured for pure conversational mode."""
        return (
            not self.enable_tools or
            not self.has_tools() or
            self.operation_mode == 'conversational'
        )

    def get_operation_mode(self) -> str:
        """Get the current operation mode of the bot."""
        if self.operation_mode == 'adaptive':
            # In adaptive mode, determine based on current configuration
            if self.has_tools():  # ✅ Uses LLM client's tool_manager
                return 'agentic'
            else:
                return 'conversational'
        return self.operation_mode

    def _use_tools(
        self,
        question: str,
    ) -> bool:
        """Determine if tools should be enabled for this conversation."""
        if not self.enable_tools:
            return False

        # Check if tools are enabled and available via LLM client
        if not self.enable_tools or not self.has_tools():
            return False

        # For agentic mode, always use tools if available
        if self.operation_mode == 'agentic':
            return True

        # For conversational mode, never use tools
        if self.operation_mode == 'conversational':
            return False

        # For adaptive mode, use heuristics
        if self.operation_mode == 'adaptive':
            # Simple heuristics based on question content
            tool_keywords = [
                'calculate', 'compute', 'analyze', 'search', 'find',
                'create', 'generate', 'plot', 'chart', 'graph',
                'execute', 'run', 'process', 'convert', 'transform'
            ]

            question_lower = question.lower()
            return any(keyword in question_lower for keyword in tool_keywords)

        return False

    def get_tools_summary(self) -> Dict[str, Any]:
        """Get a summary of available tools and configuration."""
        return {
            'tools_enabled': self.enable_tools,
            'operation_mode': self.operation_mode,
            'tools_count': self.get_tools_count(),
            'available_tools': self.get_available_tools(),
            'has_tools': self.has_tools(),
            'is_agent_mode': self.is_agent_mode(),
            'is_conversational_mode': self.is_conversational_mode(),
            'effective_mode': self.get_operation_mode()
        }

    async def create_system_prompt(
        self,
        vector_context: str = "",
        conversation_context: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """Create the complete system prompt for the LLM."""
        # Process conversation and vector contexts
        context_parts = []
        if vector_context:
            context_parts.append(vector_context)
        if metadata:
            metadata_text = "**Search Metadata:**\n"
            for key, value in metadata.items():
                if key == 'sources' and isinstance(value, list):
                    metadata_text += f"- {key}: {', '.join(value[:3])}{'...' if len(value) > 3 else ''}\n"
                else:
                    metadata_text += f"- {key}: {value}\n"
            context_parts.append(metadata_text)

            # Format conversation context
        chat_history_section = ""
        if conversation_context:
            chat_history_section = f"**Previous Conversation:**\n{conversation_context}"

        # Apply template substitution
        tmpl = Template(self.system_prompt_template)
        system_prompt = tmpl.safe_substitute(
            context="\n\n".join(context_parts) if context_parts else "No additional context available.",
            chat_history=chat_history_section,
            **kwargs
        )
        return system_prompt

    async def conversation(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',  # 'similarity', 'mmr', 'ensemble'
        search_kwargs: dict = None,
        metric_type: str = 'COSINE',
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        return_context: bool = False,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        mode: str = "adaptive",
        **kwargs
    ) -> AIMessage:
        """
        Conversation method with vector store and history integration.

        Args:
            question: The user's question
            session_id: Session identifier for conversation history
            user_id: User identifier
            search_type: Type of search to perform ('similarity', 'mmr', 'ensemble')
            search_kwargs: Additional search parameters
            metric_type: Metric type for vector search (e.g., 'COSINE', 'EUCLIDEAN')
            limit: Maximum number of context items to retrieve
            score_threshold: Minimum score for context relevance
            use_vector_context: Whether to retrieve context from vector store
            use_conversation_history: Whether to use conversation history
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: The response from the LLM
        """
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        limit = kwargs.get(
            'limit',
            self.context_search_limit
        )
        score_threshold = kwargs.get(
            'score_threshold', self.context_score_threshold
        )

        try:
            # Get conversation history using unified memory
            conversation_history = None
            conversation_context = ""

            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await self.get_conversation_history(user_id, session_id)
                if not conversation_history:
                    conversation_history = await self.create_conversation_history(
                        user_id, session_id
                    )

                conversation_context = self.build_conversation_context(conversation_history)

            # Get vector context if store exists and enabled
            vector_context = ""
            vector_metadata = {}
            if use_vector_context and self.store:
                # Custom ensemble configuration
                if search_type == 'ensemble' and not ensemble_config:
                    ensemble_config = {
                        'similarity_limit': 6,      # Get 6 results from similarity
                        'mmr_limit': 4,             # Get 4 results from MMR
                        'final_limit': 5,           # Return top 5 combined
                        'similarity_weight': 0.6,   # Similarity results weight
                        'mmr_weight': 0.4,          # MMR results weight
                        'rerank_method': 'weighted_score'  # or 'rrf' or 'interleave'
                    }
                vector_context, vector_metadata = await self.get_vector_context(
                    question,
                    search_type=search_type,
                    search_kwargs=search_kwargs,
                    metric_type=metric_type,
                    limit=limit,
                    score_threshold=score_threshold,
                    ensemble_config=ensemble_config,
                    return_sources=return_sources
                )

            # Determine if tools should be used
            use_tools = self._use_tools(question)
            if mode == "adaptive":
                effective_mode = "agentic" if use_tools else "conversational"
            elif mode == "agentic":
                use_tools = True
                effective_mode = "agentic"
            else:  # conversational
                use_tools = False
                effective_mode = "conversational"

            # Log tool usage decision
            self.logger.info(
                f"Tool usage decision: use_tools={use_tools}, mode={mode}, "
                f"effective_mode={effective_mode}, available_tools={len(self.tools)}"
            )
            # Create system prompt
            system_prompt = await self.create_system_prompt(
                vector_context=vector_context,
                conversation_context=conversation_context,
                vector_metadata=vector_metadata,
                **kwargs
            )
            # Configure LLM if needed
            new_llm = kwargs.pop('llm', None)
            if new_llm:
                self.configure_llm(
                    llm=new_llm,
                    **kwargs.pop('llm_config', {})
                )

            # Make the LLM call using the Claude client
            async with self._llm as client:
                response = await client.ask(
                    prompt=question,
                    system_prompt=system_prompt,
                    model=kwargs.get('model', self._llm_model),
                    max_tokens=kwargs.get('max_tokens', self._max_tokens),
                    temperature=kwargs.get('temperature', self._llm_temp),
                    user_id=user_id,
                    session_id=session_id,
                )

                # Enhance the response with context metadata
                response.set_vector_context_info(
                    used=bool(vector_context),
                    context_length=len(vector_context) if vector_context else 0,
                    search_results_count=vector_metadata.get('search_results_count', 0),
                    search_type=search_type if vector_context else None,
                    score_threshold=score_threshold,
                    sources=vector_metadata.get('sources', []),
                    source_documents=vector_metadata.get('source_documents', [])
                )

                response.set_conversation_context_info(
                    used=bool(conversation_context),
                    context_length=len(conversation_context) if conversation_context else 0
                )
                if return_sources and vector_metadata.get('source_documents'):
                    response.source_documents = vector_metadata['source_documents']
                    response.context_sources = vector_metadata.get('context_sources', [])

                # Set additional metadata
                response.session_id = session_id
                response.turn_id = turn_id

                # return the response Object:
                return self.get_response(response, return_sources, return_context)

        except asyncio.CancelledError:
            self.logger.info("Conversation task was cancelled.")
            raise
        except Exception as e:
            self.logger.error(f"Error in conversation: {e}")
            raise

    def as_markdown(
        self,
        response: AIMessage,
        return_sources: bool = False,
        return_context: bool = False,
    ) -> str:
        """Enhanced markdown formatting with context information."""
        markdown_output = f"**Question**: {response.input}  \n"
        markdown_output += f"**Answer**: \n {response.output}  \n"

        # Add context information if available
        if return_context and response.has_context:
            context_info = []
            if response.used_vector_context:
                context_info.append(
                    f"Vector search ({response.search_type}, {response.search_results_count} results)"
                )
            if response.used_conversation_history:
                context_info.append(
                    "Conversation history"
                )

            if context_info:
                markdown_output += f"\n**Context Used**: {', '.join(context_info)}  \n"

        # Add tool information if tools were used
        if response.has_tools:
            tool_names = [tc.name for tc in response.tool_calls]
            markdown_output += f"\n**Tools Used**: {', '.join(tool_names)}  \n"

        # Handle sources as before
        if return_sources and response.source_documents:
            source_documents = response.source_documents
            current_sources = []
            block_sources = []
            count = 0
            d = {}

            for source in source_documents:
                if count >= 20:
                    break  # Exit loop after processing 20 documents

                metadata = getattr(source, 'metadata', {})
                if 'url' in metadata:
                    src = metadata.get('url')
                elif 'filename' in metadata:
                    src = metadata.get('filename')
                else:
                    src = metadata.get('source', 'unknown')

                if src == 'knowledge-base':
                    continue  # avoid attaching kb documents

                source_title = metadata.get('title', src)
                if source_title in current_sources:
                    continue

                current_sources.append(source_title)
                if src:
                    d[src] = metadata.get('document_meta', {})

                source_filename = metadata.get('filename', src)
                if src:
                    block_sources.append(f"- [{source_title}]({src})")
                else:
                    if 'page_number' in metadata:
                        block_sources.append(
                            f"- {source_filename} (Page {metadata.get('page_number')})"
                        )
                    else:
                        block_sources.append(f"- {source_filename}")
                count += 1

            if block_sources:
                markdown_output += f"\n**Sources**:  \n"
                markdown_output += "\n".join(block_sources)

            if d:
                response.documents = d

        return markdown_output

    def get_response(
        self,
        response: AIMessage,
        return_sources: bool = True,
        return_context: bool = False
    ) -> AIMessage:
        """Response processing with error handling."""
        if hasattr(response, 'error') and response.error:
            return response  # return this error directly

        try:
            response.response = self.as_markdown(
                response,
                return_sources=return_sources,
                return_context=return_context
            )
            return response
        except (ValueError, TypeError) as exc:
            self.logger.error(f"Error validating response: {exc}")
            return response
        except Exception as exc:
            self.logger.error(f"Error on response: {exc}")
            return response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass

    def retrieval(self, request: web.Request = None) -> "AbstractBot":
        """
        Configure the retrieval chain for the Chatbot, returning `self` if allowed,
        or raise HTTPUnauthorized if not. A permissions dictionary can specify
        * users
        * groups
        * job_codes
        * programs
        * organizations
        If a permission list is the literal string "*", it means "unrestricted" for that category.

        Args:
            request (web.Request, optional): The request object. Defaults to None.
        Returns:
            AbstractBot: The Chatbot object or raise HTTPUnauthorized.
        """
        self._request = request
        session = request.session
        try:
            userinfo = session[AUTH_SESSION_OBJECT]
        except KeyError:
            userinfo = {}

        # decode your user from session
        try:
            user = session.decode("user")
        except (KeyError, TypeError):
            raise web.HTTPUnauthorized(
                reason="Invalid user"
            )

        # 1: superuser is always allowed
        if userinfo.get('superuser', False) is True:
            return self

        # convenience references
        users_allowed = self._permissions.get('users', [])
        groups_allowed = self._permissions.get('groups', [])
        job_codes_allowed = self._permissions.get('job_codes', [])
        programs_allowed = self._permissions.get('programs', [])
        orgs_allowed = self._permissions.get('organizations', [])

        # 2: check if 'users' == "*" or user.username in 'users'
        if users_allowed == "*":
            return self
        if user.get('username') in users_allowed:
            return self

        # 3: check job_code
        if job_codes_allowed == "*":
            return self
        try:
            if user.job_code in job_codes_allowed:
                return self
        except AttributeError:
            pass

        # 4: check groups
        # If groups_allowed == "*", no restriction on groups
        if groups_allowed == "*":
            return self
        # otherwise, see if there's an intersection
        user_groups = set(userinfo.get("groups", []))
        if not user_groups.isdisjoint(groups_allowed):
            return self

        # 5: check programs
        if programs_allowed == "*":
            return self
        try:
            user_programs = set(userinfo.get("programs", []))
            if not user_programs.isdisjoint(programs_allowed):
                return self
        except AttributeError:
            pass


        # 6: check organizations
        if orgs_allowed == "*":
            return self
        try:
            user_orgs = set(userinfo.get("organizations", []))
            if not user_orgs.isdisjoint(orgs_allowed):
                return self
        except AttributeError:
            pass

        # If none of the conditions pass, raise unauthorized:
        raise web.HTTPUnauthorized(
            reason=f"User {user.username} is not Unauthorized"
        )

    async def shutdown(self, **kwargs) -> None:
        """
        Shutdown.

        Optional shutdown method to clean up resources.
        This method can be overridden in subclasses to perform any necessary cleanup tasks,
        such as closing database connections, releasing resources, etc.
        Args:
            **kwargs: Additional keyword arguments.
        """

    async def invoke(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        use_conversation_history: bool = True,
        memory: Optional[Callable] = None,
        **kwargs
    ) -> AIMessage:
        """
        Simplified conversation method with adaptive mode and conversation history.

        Args:
            question: The user's question
            session_id: Session identifier for conversation history
            user_id: User identifier
            use_conversation_history: Whether to use conversation history
            memory: Optional memory callable override
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: The response from the LLM
        """
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        try:
            # Get conversation history using unified memory
            conversation_history = None
            conversation_context = ""

            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await self.get_conversation_history(user_id, session_id)
                if not conversation_history:
                    conversation_history = await self.create_conversation_history(
                        user_id, session_id
                    )

                conversation_context = self.build_conversation_context(conversation_history)

            # Determine if tools should be used (adaptive mode)
            use_tools = self._use_tools(question)
            effective_mode = "agentic" if use_tools else "conversational"

            # FIXED: Use the new method that checks LLM client's tool_manager
            available_tools_count = self.get_tools_count()

            # Log tool usage decision
            self.logger.info(
                f"Tool usage decision: use_tools={use_tools}, "
                f"effective_mode={effective_mode}, available_tools={available_tools_count}"
            )

            # Create system prompt (no vector context)
            system_prompt = await self.create_system_prompt(
                conversation_context=conversation_context,
                **kwargs
            )

            # Configure LLM if needed
            new_llm = kwargs.pop('llm', None)
            if new_llm:
                self.configure_llm(
                    llm=new_llm,
                    **kwargs.pop('llm_config', {})
                )

            # Make the LLM call using the Claude client
            async with self._llm as client:
                response = await client.ask(
                    prompt=question,
                    system_prompt=system_prompt,
                    model=kwargs.get('model', self._llm_model),
                    max_tokens=kwargs.get('max_tokens', self._max_tokens),
                    temperature=kwargs.get('temperature', self._llm_temp),
                    user_id=user_id,
                    session_id=session_id,
                )

                # Set conversation context info
                response.set_conversation_context_info(
                    used=bool(conversation_context),
                    context_length=len(conversation_context) if conversation_context else 0
                )

                # Set additional metadata
                response.session_id = session_id
                response.turn_id = turn_id

                # Return the response
                return self.get_response(response, return_sources=False, return_context=False)

        except asyncio.CancelledError:
            self.logger.info("Conversation task was cancelled.")
            raise
        except Exception as e:
            self.logger.error(f"Error in conversation: {e}")
            raise

    # Additional utility methods for conversation management
    async def get_conversation_summary(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of the conversation history."""
        history = await self.get_conversation_history(user_id, session_id)
        if not history.turns:
            return None

        return {
            'session_id': session_id,
            'user_id': history.user_id,
            'total_turns': len(history.turns),
            'created_at': history.created_at.isoformat(),
            'updated_at': history.updated_at.isoformat(),
            'last_user_message': history.turns[-1].user_message if history.turns else None,
            'last_assistant_response': history.turns[-1].assistant_response[:100] + "..." if history.turns else None,
        }

## Ensemble Search Method
    async def _ensemble_search(
        self,
        store,
        question: str,
        config: dict,
        score_threshold: float,
        metric_type: str,
        search_kwargs: dict = None
    ) -> dict:
        """Perform ensemble search combining similarity and MMR approaches."""

        # Perform similarity search
        similarity_results = await store.similarity_search(
            query=question,
            limit=config['similarity_limit'],
            score_threshold=score_threshold,
            metric=metric_type,
            **(search_kwargs or {})
        )
        # Perform MMR search
        mmr_search_kwargs = {
            "k": config['mmr_limit'],
            "fetch_k": config['mmr_limit'] * 2,
            "lambda_mult": 0.4,
        }
        if search_kwargs:
            mmr_search_kwargs.update(search_kwargs)
        mmr_results = await store.mmr_search(
            query=question,
            score_threshold=score_threshold,
            **mmr_search_kwargs
        )
        # Combine and rerank results
        final_results = self._combine_search_results(
            similarity_results,
            mmr_results,
            config
        )

        return {
            'similarity_results': similarity_results,
            'mmr_results': mmr_results,
            'final_results': final_results
        }

    def _combine_search_results(self, similarity_results: list, mmr_results: list, config: dict) -> list:
        """Combine and rerank results from different search methods."""

        # Create a mapping of content to results for deduplication
        content_map = {}
        all_results = []

        # Add similarity results with their weights and ranks
        for rank, result in enumerate(similarity_results):
            content_key = self._get_content_key(result.content)
            if content_key not in content_map:
                # Create a copy of the result and add ensemble information
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.ensemble_score = result.score * config['similarity_weight']
                result_copy.search_source = 'similarity'
                result_copy.similarity_rank = rank
                result_copy.mmr_rank = None

                content_map[content_key] = result_copy
                all_results.append(result_copy)

        # Add MMR results, handling duplicates
        for rank, result in enumerate(mmr_results):
            content_key = self._get_content_key(result.content)
            if content_key in content_map:
                # If duplicate, boost the score and update metadata
                existing = content_map[content_key]
                mmr_score = result.score * config['mmr_weight']
                existing.ensemble_score += mmr_score
                existing.search_source = 'both'
                existing.mmr_rank = rank
            else:
                # New result from MMR
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.ensemble_score = result.score * config['mmr_weight']
                result_copy.search_source = 'mmr'
                result_copy.similarity_rank = None
                result_copy.mmr_rank = rank

                content_map[content_key] = result_copy
                all_results.append(result_copy)

        # Rerank based on method
        rerank_method = config.get('rerank_method', 'weighted_score')

        if rerank_method == 'weighted_score':
            # Sort by ensemble score
            all_results.sort(key=lambda x: x.ensemble_score, reverse=True)

        elif rerank_method == 'rrf':
            # Reciprocal Rank Fusion
            all_results = self._reciprocal_rank_fusion(similarity_results, mmr_results)

        elif rerank_method == 'interleave':
            # Interleave results from both searches
            all_results = self._interleave_results(similarity_results, mmr_results)

        # Return top results
        final_limit = config.get('final_limit', 5)
        return all_results[:final_limit]

    def _get_content_key(self, content: str) -> str:
        """Generate a key for content deduplication."""
        # Simple approach: use first 100 characters, normalized
        return content[:100].lower().strip()

    def _copy_result(self, result):
        """Create a copy of a search result."""
        # This depends on your result object structure
        # Adjust based on your actual result class
        return copy.deepcopy(result)

    def _reciprocal_rank_fusion(self, similarity_results: list, mmr_results: list, k: int = 60) -> list:
        """Implement Reciprocal Rank Fusion for combining ranked lists."""

        # Create score mappings and result mappings
        content_scores = {}
        result_map = {}

        # Add similarity scores and track results
        for rank, result in enumerate(similarity_results):
            content_key = self._get_content_key(result.content)
            rrf_score = 1 / (k + rank + 1)
            content_scores[content_key] = content_scores.get(content_key, 0) + rrf_score

            if content_key not in result_map:
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.similarity_rank = rank
                result_copy.mmr_rank = None
                result_copy.search_source = 'similarity'
                result_map[content_key] = result_copy

        # Add MMR scores and update results
        for rank, result in enumerate(mmr_results):
            content_key = self._get_content_key(result.content)
            rrf_score = 1 / (k + rank + 1)
            content_scores[content_key] = content_scores.get(content_key, 0) + rrf_score

            if content_key in result_map:
                # Update existing result
                result_map[content_key].mmr_rank = rank
                result_map[content_key].search_source = 'both'
            else:
                # New result from MMR
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.similarity_rank = None
                result_copy.mmr_rank = rank
                result_copy.search_source = 'mmr'
                result_map[content_key] = result_copy

        # Set ensemble scores based on RRF and sort
        for content_key, rrf_score in content_scores.items():
            if content_key in result_map:
                result_map[content_key].ensemble_score = rrf_score

        # Sort by RRF score
        sorted_items = sorted(content_scores.items(), key=lambda x: x[1], reverse=True)

        # Return sorted results
        return [result_map[content_key] for content_key, _ in sorted_items if content_key in result_map]

    def _interleave_results(self, similarity_results: list, mmr_results: list) -> list:
        """Interleave results from both search methods."""

        interleaved = []
        seen_content = set()

        max_len = max(len(similarity_results), len(mmr_results))

        for i in range(max_len):
            # Add from similarity first
            if i < len(similarity_results):
                result = similarity_results[i]
                content_key = self._get_content_key(result.content)
                if content_key not in seen_content:
                    result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                    result_copy.ensemble_score = 1.0 - (i * 0.1)  # Decreasing score based on position
                    result_copy.search_source = 'similarity'
                    result_copy.similarity_rank = i
                    result_copy.mmr_rank = None

                    interleaved.append(result_copy)
                    seen_content.add(content_key)

            # Add from MMR
            if i < len(mmr_results):
                result = mmr_results[i]
                content_key = self._get_content_key(result.content)
                if content_key not in seen_content:
                    result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                    result_copy.ensemble_score = 0.9 - (i * 0.1)  # Slightly lower base score for MMR
                    result_copy.search_source = 'mmr'
                    result_copy.similarity_rank = None
                    result_copy.mmr_rank = i

                    interleaved.append(result_copy)
                    seen_content.add(content_key)

        return interleaved

    # Tool Management:
    def get_tools_count(self) -> int:
        """Get the total number of available tools from LLM client."""
        # During initialization, before LLM is configured, fall back to self.tools
        if self._llm is None:
            return len(self.tools)
        else:
            return self._llm.tool_manager.tool_count()

    def has_tools(self) -> bool:
        """Check if any tools are available via LLM client."""
        return self.get_tools_count() > 0

    def get_available_tools(self) -> List[str]:
        """Get list of available tool names from LLM client."""
        if hasattr(self, '_llm') and self._llm and hasattr(self._llm, 'tool_manager'):
            return list(self._llm.tool_manager.list_tools())
        return []

    def register_tool(
        self,
        tool: Union[ToolDefinition, AbstractTool] = None,
        name: str = None,
        description: str = None,
        input_schema: Dict[str, Any] = None,
        function: Callable = None,
    ) -> None:
        """Register a tool via LLM client's tool_manager."""
        if hasattr(self, '_llm') and self._llm and hasattr(self._llm, 'tool_manager'):
            self._llm.tool_manager.register_tool(
                tool=tool,
                name=name,
                description=description,
                input_schema=input_schema,
                function=function
            )
        else:
            # Store for later registration when LLM client is created
            if not hasattr(self, 'tools'):
                self.tools = []
            self.tools.append({
                'tool': tool,
                'name': name,
                'description': description,
                'input_schema': input_schema,
                'function': function
            })

    def register_tools(self, tools: List[Union[ToolDefinition, AbstractTool]]) -> None:
        """Register multiple tools via LLM client's tool_manager."""
        if hasattr(self, '_llm') and self._llm and hasattr(self._llm, 'tool_manager'):
            self._llm.tool_manager.register_tools(tools)
        else:
            self.tools.extend(tools)
