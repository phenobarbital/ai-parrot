"""
Abstract Bot interface.
"""
from abc import ABC
import importlib
from typing import Any, List, Union, Optional
from collections.abc import Callable
import os
import uuid
from string import Template
import asyncio
from aiohttp import web
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.vectorstores import VectorStoreRetriever
from langchain.memory import (
    ConversationBufferMemory,
    ConversationBufferWindowMemory
)
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate
)
from langchain.retrievers import (
    EnsembleRetriever,
)
from langchain.docstore.document import Document
from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.chains.conversational_retrieval.base import (
    ConversationalRetrievalChain
)
from langchain_community.chat_message_histories import (
    RedisChatMessageHistory
)
from langchain_community.retrievers import BM25Retriever
# for exponential backoff
from pydantic_core._pydantic_core import ValidationError

import backoff # for exponential backoff
from datamodel.exceptions import ValidationError as DataError  # pylint: disable=E0611
from navconfig.logging import logging
from navigator_auth.conf import AUTH_SESSION_OBJECT
from ..interfaces import DBInterface
from ..exceptions import ConfigError
from ..conf import (
    REDIS_HISTORY_URL,
    EMBEDDING_DEFAULT_MODEL
)

## LLM configuration
from ..llms import LLM_PRESETS, AbstractLLM

# Vertex
try:
    from ..llms.vertex import VertexLLM
    VERTEX_ENABLED = True
except (ModuleNotFoundError, ImportError):
    VERTEX_ENABLED = False

# Google
try:
    from ..llms.google import GoogleGenAI
    GOOGLE_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GOOGLE_ENABLED = False

# Anthropic:
try:
    from ..llms.anthropic import AnthropicLLM
    ANTHROPIC_ENABLED = True
except (ModuleNotFoundError, ImportError):
    ANTHROPIC_ENABLED = False

# OpenAI
try:
    from ..llms.openai import OpenAILLM
    OPENAI_ENABLED = True
except (ModuleNotFoundError, ImportError):
    OPENAI_ENABLED = False

# Groq
try:
    from ..llms.groq import GroqLLM
    GROQ_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GROQ_ENABLED = False

from ..utils import SafeDict
# Chat Response:
from ..models import ChatResponse
from .prompts import (
    BASIC_SYSTEM_PROMPT,
    BASIC_HUMAN_PROMPT,
    DEFAULT_GOAL,
    DEFAULT_ROLE,
    DEFAULT_CAPABILITIES,
    DEFAULT_BACKHISTORY
)
from .interfaces import EmptyRetriever
## Vector Stores:
from ..stores import AbstractStore, supported_stores, EmptyStore
from .retrievals import MultiVectorStoreRetriever


os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # Hide TensorFlow logs if present

logging.getLogger(name='primp').setLevel(logging.INFO)
logging.getLogger(name='rquest').setLevel(logging.INFO)
logging.getLogger("grpc").setLevel(logging.CRITICAL)
logging.getLogger("tensorflow").setLevel(logging.CRITICAL)
logging.getLogger("transformers").setLevel(logging.CRITICAL)
logging.getLogger("pymilvus").setLevel(logging.INFO)


def predicate(exception):
    """Return True if we should retry, False otherwise."""
    return not isinstance(exception, (ValidationError, RuntimeError, DataError))


class AbstractBot(DBInterface, ABC):
    """AbstractBot.

    This class is an abstract representation a base abstraction for all Chatbots.
    """
    # TODO: make tensor and embeddings optional.
    # Define system prompt template
    system_prompt_template = BASIC_SYSTEM_PROMPT

    # Define human prompt template
    human_prompt_template = BASIC_HUMAN_PROMPT

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
            self.system_prompt_template = system_prompt or BASIC_SYSTEM_PROMPT
        if human_prompt:
            self.human_prompt_template = human_prompt or BASIC_HUMAN_PROMPT
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
        # Optional Redis Memory Saver:
        self.memory_saver: Optional[MemorySaver] = None
        # Start initialization:
        self.kb = None
        self.knowledge_base: list = []
        self.return_sources: bool = kwargs.pop('return_sources', False)
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
        # Definition of LLM
        self._llm_class: str = None
        self._default_llm: str = kwargs.get('use_llm', 'vertexai')
        self._use_chat: bool = kwargs.get('use_chat', False)
        self._llm_model = kwargs.get('model_name', 'gemini-1.5-pro')
        self._llm_preset: str = kwargs.get('preset', None)
        if self._llm_preset:
            try:
                presetting = LLM_PRESETS[self._llm_preset]
            except KeyError:
                self.logger.warning(
                    f"Invalid preset: {self._llm_preset}, default to 'analytical'"
                )
                presetting = LLM_PRESETS['analytical']
            self._llm_temp = presetting.get('temperature', 0.2)
            self._max_tokens = presetting.get('max_tokens', 4096)
        else:
            # Default LLM Presetting by LLMs
            self._llm_temp = kwargs.get('temperature', 0.2)
            self._max_tokens = kwargs.get('max_tokens', 4096)
        self._llm_top_k = kwargs.get('top_k', 41)
        self._llm_top_p = kwargs.get('top_p', 0.9)
        self._llm_config = kwargs.get('model_config', {})
        if self._llm_config:
            self._llm_model = self._llm_config.pop('model', self._llm_model)
            self._llm_class = self._llm_config.pop('name', None)
        # Overrriding LLM object
        self._llm_obj: Callable = kwargs.get('llm', None)
        # LLM base Object:
        self._llm: Callable = None
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
        self.dimension: int = int(kwargs.get('dimension', 768))
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
        return self._llm_obj.get_supported_models()

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
            "- If you are unsure, let the user know and avoid making assumptions. Maintain a professional tone in all responses.\n"
            "- Use simple language for complex topics to ensure user understanding.\n"
            "- You are a fluent speaker, you can talk and respond fluently in English or Spanish, and you must answer in the same language as the user's question. If the user's language is not English, you should translate your response into their language.\n"
        )


    @property
    def llm(self):
        return self._llm

    @llm.setter
    def llm(self, model):
        self._llm_obj = model
        self._llm = model.get_llm()

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=3,
        max_time=60,
        giveup=lambda e: not predicate(e)  # Don't retry if predicate returns False
    )
    def llm_chain(
        self,
        llm: str = "vertexai",
        model: str = None,
        **kwargs
    ) -> AbstractLLM:
        """llm_chain.

        Args:
            llm (str): The language model to use.

        Returns:
            AbstractLLM: The language model to use.

        """
        try:
            if llm == 'openai' and OPENAI_ENABLED:
                mdl = OpenAILLM(model=model or "gpt-4.1", **kwargs)
            elif llm in ('vertexai', 'VertexLLM') and VERTEX_ENABLED:
                mdl = VertexLLM(model=model or "gemini-1.5-pro", **kwargs)
            elif llm == 'anthropic' and ANTHROPIC_ENABLED:
                mdl = AnthropicLLM(model=model or 'claude-3-5-sonnet-20240620', **kwargs)
            elif llm in ('groq', 'Groq') and GROQ_ENABLED:
                mdl = GroqLLM(model=model or "meta-llama/llama-4-maverick-17b-128e-instruct", **kwargs)
            elif llm == 'llama3' and GROQ_ENABLED:
                mdl = GroqLLM(model=model or "llama-3.3-70b-versatile", **kwargs)
            elif llm == 'gemma' and GROQ_ENABLED:
                mdl = GroqLLM(model=model or "gemma2-9b-it", **kwargs)
            elif llm == 'mistral' and GROQ_ENABLED:
                mdl = GroqLLM(model=model or "mistral-saba-24b", **kwargs)
            elif llm == 'google' and GOOGLE_ENABLED:
                mdl = GoogleGenAI(model=model or "models/gemini-2.5-pro-preview-03-25", **kwargs)
            else:
                raise ValueError(f"Invalid llm: {llm}")
            # get the LLM:
            return mdl
        except Exception:
            raise

    def configure_llm(
        self,
        llm: Union[str, Callable] = None,
        config: Optional[dict] = None,
        use_chat: bool = False,
        **kwargs
    ):
        """
        Configuration of LLM.
        """
        if isinstance(llm, str):
            # Get the LLM By Name:
            self._llm_obj = self.llm_chain(
                llm,
                **config
            )
            # getting langchain LLM from Obj:
            self._llm = self._llm_obj.get_llm()
        elif isinstance(llm, AbstractLLM):
            self._llm_obj = llm
            self._llm = llm.get_llm()
        elif callable(llm):
            # self._llm_obj = llm
            self._llm = llm()
        elif isinstance(self._llm_obj, str):
            # is the name of the LLM object to be used:
            self._llm_obj = self.llm_chain(
                llm=self._llm_obj,
                **kwargs
            )
            self._llm = self._llm_obj.get_llm()
        elif isinstance(self._llm_obj, AbstractLLM):
            self._llm = self._llm_obj.get_llm()
        else:
            # TODO: Calling a Default LLM
            # TODO: passing the default configuration
            try:
                self._llm_obj = self.llm_chain(
                    llm=self._default_llm,
                    model=self._llm_model,
                    temperature=self._llm_temp,
                    top_k=self._llm_top_k,
                    top_p=self._llm_top_p,
                    max_tokens=self._max_tokens,
                    use_chat=use_chat
                )
            except Exception as e:
                self.logger.error(
                    f"Error configuring Default LLM {self._llm_model}: {e}"
                )
                raise ConfigError(
                    f"Error configuring Default LLM {self._llm_model}: {e}"
                )
            self._llm = self._llm_obj.get_llm()

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

    def _define_prompt(self, config: Optional[dict] = None):
        """
        Define the System Prompt and replace variables.
        """
        # setup the prompt variables:
        if config:
            for key, val in config.items():
                setattr(self, key, val)

        pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
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
            context=context
        )
        print('Template Prompt: \n', final_prompt)
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
        name = store.get('name', 'milvus')
        store_cls = supported_stores.get(name)
        cls_path = f"parrot.stores.{name}"
        try:
            module = importlib.import_module(cls_path, package=name)
            store_cls = getattr(module, store_cls)
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


    def get_memory(
        self,
        session_id: str = None,
        key: str = 'chat_history',
        input_key: str = 'question',
        output_key: str = 'answer',
        size: int = 5,
        ttl: int = 86400
    ):
        args = {
            'memory_key': key,
            'input_key': input_key,
            'output_key': output_key,
            'return_messages': True,
            'max_len': size,
            'k': 10
        }
        if session_id:
            message_history = RedisChatMessageHistory(
                url=REDIS_HISTORY_URL,
                session_id=session_id,
                ttl=ttl
            )
            args['chat_memory'] = message_history
        return ConversationBufferWindowMemory(
            **args
        )

    def clean_history(
        self,
        session_id: str = None
    ):
        try:
            redis_client = RedisChatMessageHistory(
                url=REDIS_HISTORY_URL,
                session_id=session_id,
                ttl=60
            )
            redis_client.clear()
        except Exception as e:
            self.logger.error(
                f"Error clearing chat history: {e}"
            )

    def get_response(self, response: dict, query: str = None):
        if 'error' in response:
            return response  # return this error directly
        try:
            response = ChatResponse(**response)
            response.query = query
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
        except ValidationError as exc:
            self.logger.error(
                f"Error on response: {exc.payload}"
            )
            return response

    async def conversation(
            self,
            question: str,
            chain_type: str = 'stuff',
            search_type: str = 'similarity',
            search_kwargs: dict = {"k": 4, "fetch_k": 10, "lambda_mult": 0.89},
            return_docs: bool = True,
            metric_type: str = None,
            memory: Any = None,
            **kwargs
    ):
        # re-configure LLM:
        new_llm = kwargs.pop('llm', None)
        llm_config = kwargs.pop(
            'llm_config',
            {
                "temperature": 0.2,
                "top_k": 41,
                "Top_p": 0.9
            }
        )
        if new_llm:
            self.configure_llm(llm=new_llm, config=llm_config)
        # define the Pre-Context
        pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
        # custom_template = self.system_prompt_template.format_map(
        #     SafeDict(
        #         summaries=pre_context
        #     )
        # )
        custom_template = self.safe_format_template(
            self.system_prompt_template,
            summaries=pre_context
        )

        # Create prompt templates
        self.system_prompt = SystemMessagePromptTemplate.from_template(
            custom_template
        )
        self.human_prompt = HumanMessagePromptTemplate.from_template(
            self.human_prompt_template,
            input_variables=['question', 'chat_history']
        )
        # Combine into a ChatPromptTemplate
        chat_prompt = ChatPromptTemplate.from_messages([
            self.system_prompt,
            self.human_prompt
        ])
        if not memory:
            memory = self.memory
        if not self.memory:
            # Initialize memory
            self.memory = ConversationBufferMemory(
                memory_key="chat_history",
                input_key="question",
                output_key='answer',
                return_messages=True
            )
        try:
            if self._use_vector:
                async with self.store as store:  #pylint: disable=E1101
                    vector = store.get_vector(metric_type=metric_type)
                    retriever = VectorStoreRetriever(
                        vectorstore=vector,
                        search_type=search_type,
                        chain_type=chain_type,
                        search_kwargs=search_kwargs
                    )
                    # Create the ConversationalRetrievalChain with custom prompt
                    chain = ConversationalRetrievalChain.from_llm(
                        llm=self._llm,
                        retriever=retriever,
                        memory=self.memory,
                        chain_type=chain_type,  # e.g., 'stuff', 'map_reduce', etc.
                        verbose=True,
                        return_source_documents=return_docs,
                        return_generated_question=True,
                        combine_docs_chain_kwargs={
                            'prompt': chat_prompt
                        },
                        **kwargs
                    )
                    response = await chain.ainvoke(
                        {"question": question}
                    )
            else:
                retriever = EmptyRetriever()
                # Create the ConversationalRetrievalChain with custom prompt
                chain = ConversationalRetrievalChain.from_llm(
                    llm=self._llm,
                    retriever=retriever,
                    memory=self.memory,
                    chain_type=chain_type,  # e.g., 'stuff', 'map_reduce', etc.
                    verbose=True,
                    return_source_documents=return_docs,
                    return_generated_question=True,
                    combine_docs_chain_kwargs={
                        'prompt': chat_prompt
                    },
                    **kwargs
                )
                response = await chain.ainvoke(
                    {"question": question}
                )
        except asyncio.CancelledError:
            # Handle task cancellation
            print("Conversation task was cancelled.")
        except Exception as e:
            self.logger.error(
                f"Error in conversation: {e}"
            )
            raise
        return self.get_response(response, question)

    async def question(
            self,
            question: str,
            chain_type: str = 'stuff',
            search_type: str = 'similarity',
            search_kwargs: dict = {"k": 4, "fetch_k": 10, "lambda_mult": 0.89},
            return_docs: bool = True,
            metric_type: str = None,
            **kwargs
    ):
        # pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
        # system_prompt = self.system_prompt_template.format_map(
        #     SafeDict(
        #         summaries=pre_context
        #     )
        # )
        system_prompt = self.system_prompt_template
        human_prompt = self.human_prompt_template.replace(
            '**Chat History:**', ''
        )
        human_prompt = human_prompt.format_map(
            SafeDict(
                chat_history=''
            )
        )
        # re-configure LLM:
        new_llm = kwargs.pop('llm', None)
        if new_llm:
            llm_config = kwargs.pop(
                'llm_config',
                {
                    "temperature": 0.2,
                    "top_k": 41,
                    "Top_p": 0.9
                }
            )
            self.configure_llm(llm=new_llm, config=llm_config)
        # Combine into a ChatPromptTemplate
        prompt = PromptTemplate(
            template=system_prompt + '\n' + human_prompt,
            input_variables=['context', 'question']
        )
        try:
            if self._use_vector:
                async with self.store as store:  #pylint: disable=E1101
                    vector = store.get_vector(metric_type=metric_type)
                    retriever = VectorStoreRetriever(
                        vectorstore=vector,
                        search_type=search_type,
                        chain_type=chain_type,
                        search_kwargs=search_kwargs
                    )
                    chain = RetrievalQA.from_chain_type(
                        llm=self._llm,
                        chain_type=chain_type,  # e.g., 'stuff', 'map_reduce', etc.
                        retriever=retriever,
                        chain_type_kwargs={
                            'prompt': prompt,
                        },
                        return_source_documents=return_docs,
                        **kwargs
                    )
                    response = await chain.ainvoke(
                        question
                    )
            else:
                retriever = EmptyRetriever()
                # Create the RetrievalQA chain with custom prompt
                chain = RetrievalQA.from_chain_type(
                    llm=self._llm,
                    chain_type=chain_type,  # e.g., 'stuff', 'map_reduce', etc.
                    retriever=retriever,
                    chain_type_kwargs={
                        'prompt': prompt,
                    },
                    return_source_documents=return_docs,
                    **kwargs
                )
                response = await chain.ainvoke(
                    question
                )
        except (RuntimeError, asyncio.CancelledError):
            # check for "Event loop is closed"
            response = chain.invoke(
                question
            )
        except Exception as e:
            # Handle exceptions
            self.logger.error(
                f"An error occurred: {e}"
            )
            response = {
                "query": question,
                "error": str(e)
            }
        return self.get_response(response, question)

    def as_markdown(self, response: ChatResponse, return_sources: bool = False) -> str:
        markdown_output = f"**Question**: {response.question}  \n"
        markdown_output += f"**Answer**: \n {response.answer}  \n"
        if return_sources is True and response.source_documents:
            source_documents = response.source_documents
            current_sources = []
            block_sources = []
            count = 0
            d = {}
            for source in source_documents:
                if count >= 20:
                    break  # Exit loop after processing 10 documents
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

    async def __aenter__(self):
        if not self.store:
            self.store = EmptyStore()
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
        search_kwargs: dict = {"k": 4, "fetch_k": 10, "lambda_mult": 0.89},
        return_docs: bool = True,
        metric_type: str = None,
        memory: Any = None,
        **kwargs
    ) -> ChatResponse:
        """Build a Chain to answer Questions using AI Models.
        """
        new_llm = kwargs.pop('llm', None)
        if new_llm is not None:
            # re-configure LLM:
            llm_config = kwargs.pop(
                'llm_config',
                {
                    "temperature": 0.2,
                    "top_k": 41,
                    "Top_p": 0.9
                }
            )
            self.configure_llm(llm=new_llm, config=llm_config)
        # define the Pre-Context
        pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
        custom_template = self.system_prompt_template.format_map(
            SafeDict(
                summaries=pre_context
            )
        )
        # Create prompt templates
        self.system_prompt = SystemMessagePromptTemplate.from_template(
            custom_template
        )
        self.human_prompt = HumanMessagePromptTemplate.from_template(
            self.human_prompt_template,
            input_variables=['question', 'chat_history']
        )
        # Combine into a ChatPromptTemplate
        chat_prompt = ChatPromptTemplate.from_messages([
            self.system_prompt,
            self.human_prompt
        ])
        if not memory:
            memory = self.memory
        if not self.memory:
            # Initialize memory
            self.memory = ConversationBufferMemory(
                memory_key="chat_history",
                input_key="question",
                output_key='answer',
                return_messages=True
            )
        async with self.store as store:  #pylint: disable=E1101
            # Check if we have multiple stores:
            if self._use_vector:
                if len(self.stores) > 1:
                    store = self.stores[0]
                #     retriever = MultiVectorStoreRetriever(
                #         stores=self.stores,
                #         metric_type=metric_type,
                #         search_type=search_type,
                #         chain_type=chain_type,
                #         search_kwargs=search_kwargs
                #     )
                # else:
                vector = store.get_vector(metric_type=metric_type)
                retriever = VectorStoreRetriever(
                    vectorstore=vector,
                    search_type=search_type,
                    chain_type=chain_type,
                    search_kwargs=search_kwargs
                )
            else:
                retriever = EmptyRetriever()
            print('Retriever ', retriever)
            # if self.kb:
            #     b25_retriever = BM25Retriever.from_documents(self.kb)
            #     retriever = EnsembleRetriever(
            #         retrievers=[retriever, b25_retriever],
            #         weights=[0.8, 0.2]
            #     )
            try:
                # Create the ConversationalRetrievalChain with custom prompt
                chain = ConversationalRetrievalChain.from_llm(
                    llm=self._llm,
                    retriever=retriever,
                    memory=self.memory,
                    chain_type=chain_type,  # e.g., 'stuff', 'map_reduce', etc.
                    verbose=True,
                    return_source_documents=return_docs,
                    return_generated_question=True,
                    combine_docs_chain_kwargs={
                        'prompt': chat_prompt
                    },
                    **kwargs
                )
                response = await chain.ainvoke(
                    {"question": question}
                )
                return self.get_response(response, question)
            except asyncio.CancelledError:
                # Handle task cancellation
                print("Conversation task was cancelled.")
            except Exception as e:
                self.logger.error(
                    f"Error in conversation: {e}"
                )
                raise
