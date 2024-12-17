from abc import ABC
from typing import Any, Union, Optional
from collections.abc import Callable
import uuid
import asyncio
from aiohttp import web
import grpc
# import torch
from langchain.memory import (
    ConversationBufferMemory
)
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate
)
from langchain.docstore.document import Document
from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.chains.conversational_retrieval.base import (
    ConversationalRetrievalChain
)
from langchain_community.chat_message_histories import (
    RedisChatMessageHistory
)
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStoreRetriever
# for exponential backoff
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)  # for exponential backoff
from datamodel.exceptions import ValidationError  # pylint: disable=E0611
from navconfig.logging import logging
from ..interfaces import DBInterface
from ..conf import (
    REDIS_HISTORY_URL,
    EMBEDDING_DEFAULT_MODEL
)
## LLM configuration
from ..llms import AbstractLLM
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
    from ..llms.anthropic import Anthropic
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

# Stores
from ..stores import get_vectordb
from ..utils import SafeDict
from ..models import ChatResponse
from .retrievals import RetrievalManager


class EmptyRetriever(BaseRetriever):
    """Return a Retriever with No results.
    """
    async def aget_relevant_documents(self, query: str):
        return []

    def _get_relevant_documents(self, query: str):
        return []


class AbstractBot(DBInterface, ABC):
    """AbstractBot.

    This class is an abstract representation a base abstraction for all Chatbots.
    """
    # TODO: make tensor and embeddings optional.
    # Define system prompt template
    system_prompt_template = """
    You are {name}, a helpful and professional AI assistant.

    Your primary function is to {goal}
    Use the information from the provided knowledge base and provided context of documents to answer users' questions accurately and concisely.
    Focus on answering the question directly but in detail. Do not include an introduction or greeting in your response.

    I am here to help with {role}.

    **Backstory:**
    {backstory}.

    Here is a brief summary of relevant information:
    Context: {context}
    End of Context.

    **{rationale}**

    Given this information, please provide answers to the following question adding detailed and useful insights.
    """

    # Define human prompt template
    human_prompt_template = """
    **Chat History:**
    {chat_history}

    **Human Question:**
    {question}
    """

    def __init__(
        self,
        name: str = 'Nav',
        system_prompt: str = None,
        human_prompt: str = None,
        **kwargs
    ):
        """Initialize the Chatbot with the given configuration."""
        if system_prompt:
            self.system_prompt_template = system_prompt
        if human_prompt:
            self.human_prompt_template = human_prompt
        # Chatbot ID:
        self.chatbot_id: uuid.UUID = kwargs.get(
            'chatbot_id',
            str(uuid.uuid4().hex)
        )
        # Basic Information:
        self.name: str = name
        ##  Logging:
        self.logger = logging.getLogger(f'{self.name}.Bot')
        # Start initialization:
        self.kb = None
        self.knowledge_base: list = []
        self.return_sources: bool = kwargs.pop('return_sources', False)
        self.description = self._get_default_attr(
            'description', 'Navigator Chatbot', **kwargs
        )
        self.role = self._get_default_attr(
            'role', self.default_role(), **kwargs
        )
        self.goal = self._get_default_attr(
            'goal',
            'provide helpful information to users',
            **kwargs
        )
        self.backstory = self._get_default_attr(
            'backstory',
            default=self.default_backstory(),
            **kwargs
        )
        self.rationale = self._get_default_attr(
            'rationale',
            default=self.default_rationale(),
            **kwargs
        )
        # Definition of LLM
        self._default_llm: str = kwargs.get('use_llm', 'vertexai')
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
        self.chunk_size: int = int(kwargs.get('chunk_size', 768))
        self.dimension: int = int(kwargs.get('dimension', 768))
        self._use_database: bool = kwargs.get('use_database', False)
        self._database: dict = kwargs.get('database', {})
        self.store: Callable = None
        self.memory: Callable = None

        # Embedding Model Name
        self.embedding_model = kwargs.get(
            'embedding_model', {}
        )
        if not self.embedding_model:
            self.embedding_model = {
                'model': EMBEDDING_DEFAULT_MODEL,
                'tokenizer': None
            }
        # embedding object:
        self.embeddings = kwargs.get('embeddings', None)
        self.rag_model = kwargs.get(
            'rag_model',
            "rlm/rag-prompt-llama"
        )

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
            "When responding to user queries, ensure that you provide accurate and up-to-date information.\n"
            "Be polite and clear in your explanations, "
            "ensuring that responses are based only on verified information from owned sources. "
            "If you are unsure, let the user know and avoid making assumptions. Maintain a professional tone in all responses.\n"
            "You are a fluent speaker, you can talk and respond fluently in English or Spanish, and you must answer in the same language as the user's question. If the user's language is not English, you should translate your response into their language.\n"
        )

    def default_backstory(self) -> str:
        return (
            "I am an AI assistant designed to help you find information.\n"
        )

    def default_role(self) -> str:
        return "Assisting with queries"

    @property
    def llm(self):
        return self._llm

    @llm.setter
    def llm(self, model):
        self._llm_obj = model
        self._llm = model.get_llm()

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    def llm_chain(
        self, llm: str = "vertexai", **kwargs
    ) -> AbstractLLM:
        """llm_chain.

        Args:
            llm (str): The language model to use.

        Returns:
            AbstractLLM: The language model to use.

        """
        if llm == 'openai' and OPENAI_ENABLED:
            mdl = OpenAILLM(model="gpt-3.5-turbo", **kwargs)
        elif llm in ('vertexai', 'VertexLLM') and VERTEX_ENABLED:
            mdl = VertexLLM(model="gemini-1.5-pro", **kwargs)
        elif llm == 'anthropic' and ANTHROPIC_ENABLED:
            mdl = Anthropic(model="claude-3-opus-20240229", **kwargs)
        elif llm in ('groq', 'Groq') and GROQ_ENABLED:
            mdl = GroqLLM(model="llama3-70b-8192", **kwargs)
        elif llm == 'llama3' and GROQ_ENABLED:
            mdl = GroqLLM(model="llama3-groq-70b-8192-tool-use-preview", **kwargs)
        elif llm == 'mixtral' and GROQ_ENABLED:
            mdl = GroqLLM(model="mixtral-8x7b-32768", **kwargs)
        elif llm == 'google' and GOOGLE_ENABLED:
            mdl = GoogleGenAI(model="models/gemini-1.5-pro-latest", **kwargs)
        else:
            raise ValueError(f"Invalid llm: {llm}")

        # get the LLM:
        return mdl

    def _configure_llm(self, llm: Union[str, Callable] = None, config: Optional[dict] = None):
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
        elif isinstance(self._llm_obj, AbstractLLM):
            self._llm = self._llm_obj.get_llm()
        elif self._llm_obj is not None:
            self._llm = self._llm_obj
        else:
            # TODO: Calling a Default LLM
            # TODO: passing the default configuration
            self._llm_obj = self.llm_chain(
                llm=self._default_llm,
                temperature=0.2,
                top_k=30,
                Top_p=0.6,
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

    async def store_configuration(self, vector_db: str, config: dict):
        """Create the Vector Store Configuration."""
        self.collection_name = config.get('collection_name', None)
        if not self.embeddings:
            embed = self.embedding_model
        else:
            embed = self.embeddings
        # TODO: add dynamic configuration of VectorStore
        self.store = get_vectordb(
            vector_db,
            embeddings=embed,
            **config
        )

    def _define_prompt(self, config: Optional[dict] = None):
        """
        Define the System Prompt and replace variables.
        """
        # setup the prompt variables:
        if config:
            for key, val in config.items():
                setattr(self, key, val)
        # Creating the variables:
        self.system_prompt_template = self.system_prompt_template.format_map(
            SafeDict(
                name=self.name,
                role=self.role,
                goal=self.goal,
                backstory=self.backstory,
                rationale=self.rationale
            )
        )
        # print('Template Prompt: \n', self.system_prompt_template)

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
            self.app[f"{self.name.lower()}_chatbot"] = self
        # Setup the Store Config:
        await self.store_configuration(
            vector_db='MilvusStore',
            config=self._database
        )
        # And define Prompt:
        self._define_prompt()

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
            'max_len': size
        }
        if session_id:
            message_history = RedisChatMessageHistory(
                url=REDIS_HISTORY_URL,
                session_id=session_id,
                ttl=ttl
            )
            args['chat_memory'] = message_history
        return ConversationBufferMemory(
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

    def get_response(self, response: dict):
        if 'error' in response:
            return response  # return this error directly
        try:
            response = ChatResponse(**response)
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
                "top_k": 30,
                "Top_p": 0.6
            }
        )
        self._configure_llm(llm=new_llm, config=llm_config)
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
        try:
            # allowing DB connections:
            self.store._use_database = self._use_database
            async with self.store as store:  #pylint: disable=E1101
                if self._use_database is True:
                    vector = store.get_vector(metric_type=metric_type)
                    retriever = VectorStoreRetriever(
                        vectorstore=vector,
                        search_type=search_type,
                        chain_type=chain_type,
                        search_kwargs=search_kwargs
                    )
                else:
                    retriever = EmptyRetriever()
                # Create the ConversationalRetrievalChain with custom prompt
                chain = ConversationalRetrievalChain.from_llm(
                    llm=self.llm,
                    retriever=retriever,
                    memory=self.memory,
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
        return self.get_response(response)

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
        pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
        system_prompt = self.system_prompt_template.format_map(
            SafeDict(
                summaries=pre_context
            )
        )
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
        llm_config = kwargs.pop(
            'llm_config',
            {
                "temperature": 0.2,
                "top_k": 30,
                "Top_p": 0.6
            }
        )
        self._configure_llm(llm=new_llm, config=llm_config)
        # Combine into a ChatPromptTemplate
        prompt = PromptTemplate(
            template=system_prompt + '\n' + human_prompt,
            input_variables=['context', 'question']
        )
        # allowing DB connections:
        self.store._use_database = self._use_database
        async with self.store as store:  #pylint: disable=E1101
            if self._use_database is True:
                vector = store.get_vector(metric_type=metric_type)
                retriever = VectorStoreRetriever(
                    vectorstore=vector,
                    search_type=search_type,
                    chain_type=chain_type,
                    search_kwargs=search_kwargs
                )
            else:
                retriever = EmptyRetriever()
            # Create the RetrievalQA chain with custom prompt
            chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type=chain_type,  # e.g., 'stuff', 'map_reduce', etc.
                retriever=retriever,
                chain_type_kwargs={
                    'prompt': prompt,
                },
                return_source_documents=return_docs,
                **kwargs
            )
            try:
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
        return self.get_response(response)

    def as_markdown(self, response: ChatResponse, return_sources: bool = False) -> str:
        markdown_output = f"**Question**: {response.question}  \n"
        markdown_output += f"**Answer**: {response.answer}  \n"
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
                        block_sources.append(f"- {source_filename} (Page {metadata.get('page_number')})")
                    else:
                        block_sources.append(f"- {source_filename}")
            if block_sources:
                markdown_output += f"**Sources**:  \n"
                markdown_output += "\n".join(block_sources)
            if d:
                response.documents = d
        return markdown_output

    async def shutdown(self):
        if self.store:
            try:
                await self.store.disconnect()
                await grpc.aio.shutdown_grpc_aio()
            except Exception:
                pass

    def get_retrieval(self, source_path: str = 'web', request: web.Request = None):
            pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
            system_prompt = self.system_prompt_template.format_map(
                SafeDict(
                    summaries=pre_context
                )
            )
            human_prompt = self.human_prompt_template
            # Generate the Retrieval
            rm = RetrievalManager(
                chatbot_id=self.chatbot_id,
                chatbot_name=self.name,
                source_path=source_path,
                model=self._llm,
                store=self.store,
                memory=None,
                system_prompt=system_prompt,
                human_prompt=human_prompt,
                kb=self.knowledge_base,
                request=request
            )
            return rm
