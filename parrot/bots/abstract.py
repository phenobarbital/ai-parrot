"""
Abstract Bot interface.
"""
from abc import ABC
import importlib
from typing import Any, List, Union, Optional
from collections.abc import Callable
import uuid
from string import Template
import asyncio
from aiohttp import web
# for exponential backoff
import backoff # for exponential backoff
from datamodel.exceptions import ValidationError as DataError  # pylint: disable=E0611
from navconfig.logging import logging
from navigator_auth.conf import AUTH_SESSION_OBJECT  # pylint: disable=E0611
from ..interfaces import DBInterface
from ..exceptions import ConfigError  # pylint: disable=E0611
from ..conf import (
    REDIS_HISTORY_URL,
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
    AIMessageFactory
)
from ..stores import AbstractStore, supported_stores


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
        **kwargs
    ):
        """Initialize the Chatbot with the given configuration."""
        self._request: Optional[web.Request] = None
        if system_prompt:
            self.system_prompt_template = system_prompt or self.system_prompt_template
        if human_prompt:
            self.human_prompt_template = human_prompt or self.human_prompt_template
        # Chatbot ID:
        self.chatbot_id: uuid.UUID = kwargs.get(
            'chatbot_id',
            str(uuid.uuid4().hex)
        )
        if self.chatbot_id is None:
            self.chatbot_id = str(uuid.uuid4().hex)
        # Basic Information:
        self.name: str = name
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Bot'
        )
        # Optional aiohttp Application:
        self.app: Optional[web.Application] = None
        # Start initialization:
        self.kb = None
        self.knowledge_base: List[str] = []
        self.return_sources: bool = kwargs.pop('return_sources', True)
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
        self._llm_model = kwargs.get('model', 'gemini-2.0-flash-001')
        self._llm_preset: str = kwargs.get('preset', None)
        self._llm: Union[str, Any] = kwargs.get('llm', 'google')
        if isinstance(self._llm, str):
            self._llm = SUPPORTED_CLIENTS.get(self._llm.lower(), None)
        if self._llm and not issubclass(self._llm, AbstractClient):
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

        # Knowledge base:
        self.knowledge_base: list = []
        self._documents_: list = []
        # Models, Embed and collections
        # Vector information:
        self._use_vector: bool = kwargs.get('use_vectorstore', False)
        self._vector_info_: dict = kwargs.get('vector_info', {})
        self._vector_store: dict = kwargs.get('vector_store', None)
        self.chunk_size: int = int(kwargs.get('chunk_size', 2048))
        self.dimension: int = int(kwargs.get('dimension', 384))
        # Metric Type:
        self._metric_type: str = kwargs.get('metric_type', 'COSINE')
        self.store: Callable = None
        self.stores: List[AbstractStore] = []
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
        self.rag_model = kwargs.get(
            'rag_model',
            "rlm/rag-prompt-llama"
        )
        # Summarization and Classification Models
        # Bot Security and Permissions:
        _default = self.default_permissions()
        _permissions = kwargs.get('permissions', _default)
        if _permissions is None:
            _permissions = {}
        self._permissions = {**_default, **_permissions}

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
            "- When responding to user queries, ensure that you provide accurate and up-to-date information.\n"
            "- Be polite, clear and concise in your explanations.\n"
            "- ensuring that responses are based only on verified information from owned sources.\n"
            "- Detect user language: respond in English if the user writes in English; respond in Spanish if the user writes in Spanish."
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
            return cls(
                model=model,
                **kwargs
            )
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
                    **kwargs
                )
            elif issubclass(llm, AbstractClient):
                self._llm = llm(**kwargs)
            elif isinstance(llm, AbstractClient):
                self._llm = llm
            elif callable(llm):
                self._llm = llm(
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
                    self.logger.error(
                        f"Error configuring Default LLM {self._llm_model}: {e}"
                    )
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
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error configuring Default LLM {self._llm_model}: {e}"
                    )
                    raise ConfigError(
                        f"Error configuring Default LLM {self._llm_model}: {e}"
                    )
            elif isinstance(self._llm, AbstractClient):
                return self._llm
            elif issubclass(self._llm, AbstractClient):
                try:
                    # If _llm is already an AbstractClient subclass, just use it
                    self._llm = self._llm(
                        model=self._llm_model,
                        temperature=self._llm_temp,
                        top_k=self._top_k,
                        top_p=self._top_p,
                        max_tokens=self._max_tokens,
                        **kwargs
                    )
                except TypeError as e:
                    self.logger.error(
                        f"Error initializing LLM Client {self._llm.__name__}: {e}"
                    )
                    raise ConfigError(
                        f"Error initializing LLM Client {self._llm.__name__}: {e}"
                    )

    def create_kb(self, documents: list):
        new_docs = []
        # for doc in documents:
        #     content = doc.pop('content')
        #     source = doc.pop('source', 'knowledge-base')
        #     if doc:
        #         meta = {
        #             'source': source,
        #             **doc
        #         }
        #     else:
        #         meta = {'source': source}
        #     if content:
        #         new_docs.append(
        #             Document(
        #                 page_content=content,
        #                 metadata=meta
        #             )
        #         )
        return new_docs

    def safe_format_template(self, template, **kwargs):
        """
        Format a template string while preserving content inside triple backticks.
        """
        # Split the template by triple backticks
        parts = template.split("```")

        # Format only the odd-indexed parts (outside triple backticks)
        for i in range(0, len(parts), 2):
            parts[i] = parts[i].format_map(SafeDict(**kwargs))

        # Rejoin with triple backticks
        return "```".join(parts)

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
            pre_context = "Pre-Instructions: \n"
            pre_context += "\n".join(f"- {a}." for a in self.pre_instructions)
        context = "{context}"
        if self.context:
            context = """
            Here is a brief summary of relevant information:
            Context: {context}
            End of Context.

            Given this information, please provide answers to the following question adding detailed and useful insights.
            """
        tmpl = Template(self.system_prompt_template)
        final_prompt = tmpl.safe_substitute(
            name=self.name,
            role=self.role,
            goal=self.goal,
            capabilities=self.capabilities,
            backstory=self.backstory,
            rationale=self.rationale,
            pre_context=pre_context,
            context=context,
            **kwargs
        )
        # print('Template Prompt: \n', final_prompt)
        self.system_prompt_template = final_prompt

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
        # Configure LLM:
        try:
            self.configure_llm()
        except Exception as e:
            self.logger.error(
                f"Error configuring LLM: {e}"
            )
            raise
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


    def _get_database_store(self, store: dict) -> AbstractStore:
        """Get the VectorStore Class from the store configuration."""
        name = store.get('name', None)
        if not name:
            vector_driver = store.get('vector_database', 'PgvectorStore')
            name = next((k for k, v in supported_stores.items() if v == vector_driver), None)
        store_cls = supported_stores.get(name)
        cls_path = f"parrot.stores.{name}"
        try:
            module = importlib.import_module(cls_path, package=name)
            store_cls = getattr(module, store_cls)
            self.logger.notice(
                f"Using VectorStore: {store_cls.__name__} for {name} with Embedding {self.embedding_model}"
            )
            return store_cls(
                embedding_model=self.embedding_model,
                embedding=self.embeddings,
                **store
            )
        except (ModuleNotFoundError, ImportError) as e:
            self.logger.error(
                f"Error importing VectorStore: {e}"
            )
            raise

    def configure_store(self, **kwargs):
        # TODO: Implement VectorStore Configuration
        if isinstance(self._vector_store, list):
            # Is a list of vector stores instances:
            for st in self._vector_store:
                try:
                    store_cls = self._get_database_store(st)
                    store_cls.use_database = self._use_vector
                    self.stores.append(store_cls)
                except ImportError:
                    continue
        elif isinstance(self._vector_store, dict):
            # Is a single vector store instance:
            store_cls = self._get_database_store(self._vector_store)
            store_cls.use_database = self._use_vector
            self.stores.append(store_cls)
        else:
            raise ValueError(
                f"Invalid Vector Store Config: {self._vector_store}"
            )
        self.logger.info(
            f"Configured Vector Stores: {self.stores}"
        )
        if self.stores:
            self.store = self.stores[0]
        print('=================================')
        print('END STORES >> ', self.stores, self.store)
        print('=================================')

    async def conversation(
            self,
            question: str,
            chain_type: str = 'stuff',
            search_type: str = 'similarity',  # 'similarity', 'mmr', 'ensemble'
            search_kwargs: dict = None,
            return_docs: bool = True,
            metric_type: str = 'EUCLIDEAN_DISTANCE',
            memory: Any = None,
            limit: Optional[int] = 5,
            score_threshold: float = None,
            **kwargs
    ) -> AIMessage:
        # re-configure LLM:
        new_llm = kwargs.pop('llm', None)
        llm_config = kwargs.pop(
            'llm_config',
            {
                "temperature": 0.1,
                "top_k": 41,
                "Top_p": 0.9
            }
        )
        if search_kwargs is None:
            search_kwargs = {
                "k": limit,
                "fetch_k": limit * 2,  # Fetch 2x for MMR, but still limited
                "lambda_mult": 0.4,  # Balance relevance vs diversity
            }
        if new_llm:
            self.configure_llm(llm=new_llm, config=llm_config)

    def as_markdown(self, response: AIMessage, return_sources: bool = False) -> str:
        markdown_output = f"**Question**: {response.input}  \n"
        markdown_output += f"**Answer**: \n {response.output}  \n"
        if return_sources is True and response.documents:
            source_documents = response.documents
            current_sources = []
            block_sources = []
            count = 0
            d = {}
            for source in source_documents:
                if count >= 20:
                    break  # Exit loop after processing 20 documents
                metadata = source.metadata
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
            if block_sources:
                markdown_output += f"**Sources**:  \n"
                markdown_output += "\n".join(block_sources)
            if d:
                response.documents = d
        return markdown_output

    def get_response(self, response: AIMessage):
        if 'error' in response:
            return response  # return this error directly
        try:
            response.response = self.as_markdown(
                response,
                return_sources=self.return_sources
            )
            return response
        except (ValueError, TypeError) as exc:
            self.logger.error(
                f"Error validating response: {exc}"
            )
            return response
        except Exception as exc:
            self.logger.error(
                f"Error on response: {exc}"
            )
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
        chain_type: str = 'stuff',
        search_type: str = 'similarity',
        search_kwargs: dict = {"k": 4, "fetch_k": 12, "lambda_mult": 0.4},
        score_threshold: float = None,
        return_docs: bool = True,
        metric_type: str = None,
        memory: Any = None,
        **kwargs
    ) -> AIMessage:
        """Build a Chain to answer Questions using AI Models.
        """
        new_llm = kwargs.pop('llm', None)
        if new_llm is not None:
            # re-configure LLM:
            llm_config = kwargs.pop(
                'llm_config',
                {
                    "model": self._llm_model,
                    "temperature": 0.1,
                    "top_k": 41,
                    "top_p": 0.9
                }
            )
            self.configure_llm(llm=new_llm, config=llm_config)
        # define the Pre-Context
        pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
        tmpl = Template(self.system_prompt_template)
        final_prompt = tmpl.safe_substitute(
            summaries=SafeDict(
                summaries=pre_context
            ),
            **kwargs
        )
        try:
            async with self._llm as client:
                print('LLM > ', client)
                response = await client.ask(
                    question
                )
                return self.get_response(response)
        except asyncio.CancelledError:
            # Handle task cancellation
            print("Conversation task was cancelled.")
        except Exception as e:
            self.logger.error(
                f"Error in conversation: {e}"
            )
            raise
