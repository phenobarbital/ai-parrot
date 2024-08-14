from abc import ABC
from collections.abc import Callable
from typing import Any, Union
from pathlib import Path, PurePath
import uuid
from aiohttp import web
import torch
from transformers import (
    AutoModel,
    AutoConfig,
    AutoTokenizer,
    # AutoModelForSeq2SeqLM
)
# Langchain
from langchain import hub
from langchain.docstore.document import Document
from langchain.memory import (
    # ConversationSummaryMemory,
    ConversationBufferMemory
)
# from langchain.retrievers import (
#     EnsembleRetriever,
#     ContextualCompressionRetriever
# )
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter
)
# from langchain.chains.retrieval_qa.base import RetrievalQA
# from langchain.chains.conversational_retrieval.base import (
#     ConversationalRetrievalChain
# )
# from langchain_core.runnables import (
#     RunnablePassthrough,
#     RunnablePick,
#     RunnableParallel
# )
# from langchain_core.output_parsers import StrOutputParser
# from langchain_core.prompts import (
#     PromptTemplate,
#     ChatPromptTemplate
# )
# from langchain_core.vectorstores import VectorStoreRetriever
# from langchain_community.retrievers import BM25Retriever
from langchain_community.chat_message_histories import RedisChatMessageHistory

# Navconfig
from navconfig import BASE_DIR
from navconfig.exceptions import ConfigError  # pylint: disable=E0611
from navconfig.logging import logging
from asyncdb.exceptions import NoDataFound

try:
    from ..stores.qdrant import QdrantStore
    QDRANT_ENABLED = True
except (ModuleNotFoundError, ImportError):
    QDRANT_ENABLED = False

try:
    from ..stores.milvus import MilvusStore
    MILVUS_ENABLED = True
except (ModuleNotFoundError, ImportError):
    MILVUS_ENABLED = False

from ..utils import SafeDict, parse_toml_config


## LLM configuration
# Vertex
try:
    from ..llms.vertex import VertexLLM
    VERTEX_ENABLED = True
except (ModuleNotFoundError, ImportError):
    VERTEX_ENABLED = False

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

# LLM Transformers
try:
    from  ..llms.pipes import PipelineLLM
    TRANSFORMERS_ENABLED = True
except (ModuleNotFoundError, ImportError):
    TRANSFORMERS_ENABLED = False

# HuggingFaces Hub:
try:
    from  ..llms.hf import HuggingFace
    HF_ENABLED = True
except (ModuleNotFoundError, ImportError):
    HF_ENABLED = False

# GroQ:
try:
    from ..llms.groq import GroqLLM
    GROQ_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GROQ_ENABLED = False

from ..loaders import (
    PDFLoader,
    PDFTablesLoader,
    GithubLoader,
    RepositoryLoader,
    WebLoader,
    VimeoLoader,
    YoutubeLoader,
    PPTXLoader,
    MSWordLoader
)
from .retrievals import RetrievalManager
from ..conf import (
    DEFAULT_LLM_MODEL_NAME,
    EMBEDDING_DEVICE,
    MAX_VRAM_AVAILABLE,
    RAM_AVAILABLE,
    default_dsn,
    REDIS_HISTORY_URL,
    EMBEDDING_DEFAULT_MODEL
)
from ..interfaces import DBInterface
from ..models import ChatbotModel


logging.getLogger(name='selenium.webdriver').setLevel(logging.WARNING)
logging.getLogger(name='selenium').setLevel(logging.INFO)


class AbstractChatbot(ABC, DBInterface):
    """Represents an Chatbot in Navigator.

        Each Chatbot has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """

    template_prompt: str = (
        "You are {name}, an expert AI assistant and {role} Working at {company}.\n\n"
        "Your primary function is to {goal}\n"
        "Use the provided context of the documents you have processed or extracted from other provided tools or sources to provide informative, detailed and accurate responses.\n"
        "I am here to help with {role}.\n"
        "**Backstory:**\n"
        "{backstory}.\n\n"
        "Focus on answering the question directly but detailed. Do not include an introduction or greeting in your response.\n\n"
        "{company_information}\n\n"
        "Here is a brief summary of relevant information:\n"
        "Context: {context}\n\n"
        "Given this information, please provide answers to the following question adding detailed and useful insights:\n\n"
        "**Chat History:** {chat_history}\n\n"
        "**Human Question:** {question}\n"
        "Assistant Answer:\n\n"
        "{rationale}\n"
        "You are a fluent speaker, you can talk and respond fluently in English and Spanish, and you must answer in the same language as the user's question. If the user's language is not English, you should translate your response into their language.\n"
    )

    def _get_default_attr(self, key, default: Any = None, **kwargs):
        if key in kwargs:
            return kwargs.get(key)
        if hasattr(self, key):
            return getattr(self, key)
        if not hasattr(self, key):
            return default
        return getattr(self, key)

    def __init__(self, **kwargs):
        """Initialize the Chatbot with the given configuration."""
        # Chatbot ID:
        self.chatbot_id: uuid.UUID = kwargs.get(
            'chatbot_id',
            None
        )
        # Basic Information:
        self.name = self._get_default_attr(
            'name', 'NAV', **kwargs
        )
        ##  Logging:
        self.logger = logging.getLogger(f'{self.name}.Chatbot')
        self.description = self._get_default_attr(
            'description', 'Navigator Chatbot', **kwargs
        )
        self.role = self._get_default_attr(
            'role', 'Chatbot', **kwargs
        )
        self.goal = self._get_default_attr(
            'goal', 'provide helpful information to users', **kwargs
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
        # Configuration File:
        self.config_file: PurePath = kwargs.get('config_file', None)
        # Other Configuration
        self.confidence_threshold: float = kwargs.get('threshold', 0.5)
        self.context = kwargs.pop('context', '')

        # Company Information:
        self.company_information: dict = kwargs.pop('company_information', {})

        # Pre-Instructions:
        self.pre_instructions: list = kwargs.get(
            'pre_instructions',
            []
        )

        # Knowledge base:
        self.knowledge_base: list = []
        self._documents_: list = []

        # Text Documents
        self.documents_dir = kwargs.get(
            'documents_dir',
            None
        )
        if isinstance(self.documents_dir, str):
            self.documents_dir = Path(self.documents_dir)
        if not self.documents_dir:
            self.documents_dir = BASE_DIR.joinpath('documents')
        if not self.documents_dir.exists():
            self.documents_dir.mkdir(
                parents=True,
                exist_ok=True
            )
        # Models, Embed and collections
        # Vector information:
        self.chunk_size: int = int(kwargs.get('chunk_size', 768))
        self.dimension: int = int(kwargs.get('dimension', 768))
        self._database: dict = kwargs.get('database', {})
        self._store: Callable = None
        # Embedding Model Name
        self.use_bge: bool = bool(
            kwargs.get('use_bge', 'False')
        )
        self.use_fastembed: bool = bool(
            kwargs.get('use_fastembed', 'False')
        )
        self.embedding_model_name = kwargs.get(
            'embedding_model_name', None
        )
        # embedding object:
        self.embeddings = kwargs.get('embeddings', None)
        self.tokenizer_model_name = kwargs.get(
            'tokenizer', None
        )
        self.summarization_model = kwargs.get(
            'summarization_model',
            "facebook/bart-large-cnn"
        )
        self.rag_model = kwargs.get(
            'rag_model',
            "rlm/rag-prompt-llama"
        )
        self._text_splitter_model = kwargs.get(
            'text_splitter',
            'mixedbread-ai/mxbai-embed-large-v1'
        )
        # Definition of LLM
        self._llm: Callable = None
        self._llm_obj: Callable = kwargs.get('llm', None)

        # Max VRAM usage:
        self._max_vram = int(kwargs.get('max_vram', MAX_VRAM_AVAILABLE))

    def get_llm(self):
        return self._llm_obj

    def __repr__(self):
        return f"<Chatbot.{self.__class__.__name__}:{self.name}>"

    # Database:
    @property
    def store(self):
        if not self._store.connected:
            self._store.connect()
        return self._store

    def default_rationale(self) -> str:
        # TODO: read rationale from a file
        return """
        I am a language model trained by Google.
        I am designed to provide helpful information to users.
        Remember to maintain a professional tone.
        If I cannot find relevant information in the documents,
        I will indicate this and suggest alternative avenues for the user to find an answer.
        """

    def default_backstory(self) -> str:
        return (
        "help with Human Resources related queries or knowledge-based questions about T-ROC Global.\n"
        "You can ask me about the company's products and services, the company's culture, the company's clients.\n"
        "You have the capability to read and understand various Human Resources documents, "
        "such as employee handbooks, policy documents, onboarding materials, company's website, and more.\n"
        "I can also provide information about the company's policies and procedures, benefits, and other HR-related topics."
    )

    def load_llm(self, llm_name: str, model_name: str = None, **kwargs):
        """Load the Language Model for the Chatbot.
        """
        print('LLM > ', llm_name)
        if llm_name == 'VertexLLM':
            if VERTEX_ENABLED is False:
                raise ConfigError(
                    "VertexAI enabled but not installed."
                )
            return VertexLLM(model=model_name, **kwargs)
        elif llm_name == 'Anthropic':
            if ANTHROPIC_ENABLED is False:
                raise ConfigError(
                    "ANTHROPIC is enabled but not installed."
                )
            return Anthropic(model=model_name, **kwargs)
        elif llm_name == 'OpenAI':
            if OPENAI_ENABLED is False:
                raise ConfigError(
                    "OpenAI is enabled but not installed."
                )
            return OpenAILLM(model=model_name, **kwargs)
        elif llm_name == 'hf':
            if HF_ENABLED is False:
                raise ConfigError(
                    "Hugginfaces Hub is enabled but not installed."
                )
            return HuggingFace(model=model_name, **kwargs)
        elif llm_name == 'pipe':
            if TRANSFORMERS_ENABLED is False:
                raise ConfigError(
                    "Transformes Pipelines are enabled, but not installed."
                )
            return PipelineLLM(model=model_name, **kwargs)
        elif llm_name == 'Groq':
            if GROQ_ENABLED is False:
                raise ConfigError(
                    "Groq is enabled but not installed."
                )
            return GroqLLM(model=model_name, **kwargs)
        # TODO: Add more LLMs
        return hub.pull(llm_name)

    async def configure(self, app = None) -> None:
        if isinstance(app, web.Application):
            self.app = app  # register the app into the Extension
        elif app is None:
            self.app = None
        else:
            self.app = app.get_app()  # Nav Application
        # Config File:
        config_file = BASE_DIR.joinpath(
            'etc',
            'config',
            'chatbots',
            self.name.lower(),
            "config.toml"
        )
        if config_file.exists():
            self.logger.notice(
                f"Using Bot config {config_file}"
            )
        else:
            config_file = None
        # Database-based Bot Configuration
        if self.chatbot_id is not None:
            # Configure from the Database
            await self.from_database(config_file)
        elif config_file:
            # Configure from the TOML file
            await self.from_config_file(config_file)
        # else:
        #     # Configure from a default configuration
        #     vector_config = {
        #         "vector_database": self.vector_database,
        #         "collection_name": self.collection_name
        #     }
        #     # configure vector database:
        #     await self.store_configuration(
        #         config=vector_config
        #     )
        #     # Get the Embeddings:
        #     if not self.embedding_model_name:
        #         self.embeddings = self._llm_obj.get_embedding()
        #     # Config Prompt:
        #     self._define_prompt(
        #         config={}
        #     )
        # adding this configured chatbot to app:
        if self.app:
            self.app[f"{self.name.lower()}_chatbot"] = self

    def _configure_llm(self, llm, config):
        if self._llm_obj:
            self._llm = self._llm_obj.get_llm()
        else:
            if llm:
                # LLM:
                self._llm_obj = self.load_llm(
                    llm,
                    **config
                )
                self._llm = self._llm_obj.get_llm()
            else:
                raise ValueError(
                    f"LLM is not defined in the Configuration."
                )

    def _from_bot(self, bot, key, config, default) -> Any:
        value = getattr(bot, key, None)
        file_value = config.get(key, default)
        return value if value else file_value

    async def from_database(self, config_file: PurePath = None) -> None:
        """Load the Chatbot Configuration from the Database."""
        file_config = await parse_toml_config(config_file)
        db = self.get_database('pg', dsn=default_dsn)
        bot = None
        async with await db.connection() as conn:  # pylint: disable=E1101
            # import model
            ChatbotModel.Meta.connection = conn
            try:
                if self.chatbot_id:
                    try:
                        bot = await ChatbotModel.get(chatbot_id=self.chatbot_id)
                    except Exception:
                        bot = await ChatbotModel.get(name=self.name)
                else:
                    bot = await ChatbotModel.get(name=self.name)
            except NoDataFound:
                # Fallback to File configuration:
                if file_config:
                    await self.from_config_file(config_file)
                else:
                    raise ConfigError(
                        f"Chatbot {self.name} not found in the database."
                    )
        if not bot:
            raise ConfigError(
                f"Chatbot {self.name} not found in the database."
            )
        # Start Bot configuration from Database:
        config_file = Path(bot.config_file).resolve()
        if config_file:
            file_config = await parse_toml_config(config_file)
        # basic configuration
        basic = file_config.get('chatbot', {})
        self.name = self._from_bot(bot, 'name', basic, self.name)
        self.description = self._from_bot(bot, 'description', basic, self.description)
        self.role = self._from_bot(bot, 'role', basic, self.role)
        self.goal = self._from_bot(bot, 'goal', basic, self.goal)
        self.rationale = self._from_bot(bot, 'rationale', basic, self.rationale)
        self.backstory = self._from_bot(bot, 'backstory', basic, self.backstory)
        # company information:
        self.company_information = self._from_bot(
            bot, 'company_information', basic, self.company_information
        )
        # Contextual knowledge-base
        self.kb = file_config.get('knowledge-base', [])
        if self.kb:
            self.knowledge_base = self.create_kb(
                self.kb.get('data', [])
            )
        # Model Information:
        models = file_config.get('llm', {})
        # LLM Configuration (from file and from db)
        llm_config = models.get('config', bot.llm_config)
        llm = self._from_bot(bot, 'llm', models, 'VertexLLM')
        # Configuration of LLM:
        self._configure_llm(llm, llm_config)
        # Other models:
        models = file_config.get('models', {})
        self.embedding_model_name = self._from_bot(
            bot, 'embedding_name', models, None
        )
        self.tokenizer_model_name = self._from_bot(
            bot, 'tokenizer', models, None
        )
        self.summarization_model = self._from_bot(
            bot, 'summarize_model', models, "facebook/bart-large-cnn"
        )
        self.classification_model = self._from_bot(
            bot, 'classification_model', models, None
        )
        # Database Configuration:
        vector_config = file_config.get('database', {})
        db_config = bot.database
        db_config = {**vector_config, **db_config}
        vector_db = db_config.pop('vector_database')
        await self.store_configuration(vector_db, db_config)
        # after configuration, setup the chatbot
        if bot.template_prompt:
            self.template_prompt = bot.template_prompt
        self._define_prompt(
            config={}
        )

    async def from_config_file(self, config_file: PurePath) -> None:
        """Load the Chatbot Configuration from the TOML file."""
        self.logger.debug(
            f"Using Config File: {config_file}"
        )
        file_config = await parse_toml_config(config_file)
        # getting the configuration from config
        self.config_file = config_file
        # basic config
        basic = file_config.get('chatbot', {})
        # Chatbot Name:
        self.name = basic.get('name', self.name)
        self.description = basic.get('description', self.description)
        self.role = basic.get('role', self.role)
        self.goal = basic.get('goal', self.goal)
        self.rationale = basic.get('rationale', self.rationale)
        self.backstory = basic.get('backstory', self.backstory)
        # Company Information:
        self.company_information = basic.get(
            'company_information',
            self.company_information
        )
        # Model Information:
        llminfo = file_config.get('llm')
        llm = llminfo.get('llm', 'VertexLLM')
        cfg = llminfo.get('config', {})
        # Configuration of LLM:
        self._configure_llm(llm, cfg)

        # Other models:
        models = file_config.get('models', {})
        if not self.embedding_model_name:
            self.embedding_model_name = models.get(
                'embedding', EMBEDDING_DEFAULT_MODEL
            )
        if not self.tokenizer_model_name:
            self.tokenizer_model_name = models.get('tokenizer')
        if not self.embedding_model_name:
            # Getting the Embedding Model from the LLM
            self.embeddings = self._llm_obj.get_embedding()
        self.use_bge = models.get('use_bge', False)
        self.use_fastembed = models.get('use_fastembed', False)
        self.summarization_model = models.get(
            'summarize_model',
            "facebook/bart-large-cnn"
        )
        self.classification_model = models.get(
            'classification_model',
            None
        )
        # pre-instructions
        instructions = file_config.get('pre-instructions')
        if instructions:
            self.pre_instructions = instructions.get('instructions', [])
        # Contextual knowledge-base
        self.kb = file_config.get('knowledge-base', [])
        if self.kb:
            self.knowledge_base = self.create_kb(
                self.kb.get('data', [])
            )
        vector_config = file_config.get('database', {})
        vector_db = vector_config.pop('vector_database')
        # configure vector database:
        await self.store_configuration(
            vector_db,
            vector_config
        )
        # after configuration, setup the chatbot
        if 'template_prompt' in basic:
            self.template_prompt = basic.get('template_prompt')
        self._define_prompt(
            config=basic
        )

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
                meta = { 'source': source}
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
        self.collection_name = config.get('collection_name')
        if not self.embeddings:
            embed = self.embedding_model_name
        else:
            embed = self.embeddings
        # TODO: add dynamic configuration of VectorStore
        if vector_db == 'QdrantStore':
            if QDRANT_ENABLED is True:
                ## TODO: support pluggable vector store
                self._store = QdrantStore(  # pylint: disable=E0110
                    embeddings=embed,
                    use_bge=self.use_bge,
                    use_fastembed=self.use_fastembed,
                    **config
                )
            else:
                raise ConfigError(
                    (
                        "Qdrant is enabled but not installed, "
                        "Hint: Please install with pip install -e .[qdrant]"
                    )
                )
        elif vector_db == 'MilvusStore':
            if MILVUS_ENABLED is True:
                print('EMBEDDINGS > ', self.embeddings)
                print('AQUI MILVUS >> ', embed)
                print('AQUI MILVUS >> ', self.embedding_model_name)
                self._store = MilvusStore(
                    embeddings=embed,
                    embedding_name=self.embedding_model_name,
                    use_bge=self.use_bge,
                    use_fastembed=self.use_fastembed,
                    **config
                )
            else:
                raise ConfigError(
                    (
                        "Milvus is enabled but not installed, "
                        "Hint: Please install with pip install -e .[milvus]"
                    )
                )
        else:
            raise ValueError(
                f"Invalid Vector Store {vector_db}"
            )

    def _define_prompt(self, config: dict):
        # setup the prompt variables:
        for key, val in config.items():
            setattr(self, key, val)
        if self.company_information:
            self.template_prompt = self.template_prompt.format_map(
                SafeDict(
                    company_information=(
                        "For further inquiries or detailed information, you can contact us at:\n"
                        "- Contact Information: {contact_email}\n"
                        "- Use our contact form: {contact_form}\n"
                        "- or Visit our website: {company_website}\n"
                    )
                )
            )
        # Parsing the Template:
        self.template_prompt = self.template_prompt.format_map(
            SafeDict(
                name=self.name,
                role=self.role,
                goal=self.goal,
                backstory=self.backstory,
                rationale=self.rationale,
                threshold=self.confidence_threshold,
                **self.company_information
            )
        )
        # print('Template Prompt:', self.template_prompt)

    @property
    def llm(self):
        return self._llm

    @llm.setter
    def llm(self, model):
        self._llm_obj = model
        self._llm = model.get_llm()

    def _get_device(self, cuda_number: int = 0):
        torch.backends.cudnn.deterministic = True
        if torch.cuda.is_available():
            # Use CUDA GPU if available
            device = torch.device(f'cuda:{cuda_number}')
        elif torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            device = torch.device("mps")
        elif EMBEDDING_DEVICE == 'cuda':
            device = torch.device(f'cuda:{cuda_number}')
        else:
            device = torch.device(EMBEDDING_DEVICE)
        return device

    def get_tokenizer(self, model_name: str, chunk_size: int = 768):
        return AutoTokenizer.from_pretrained(
            model_name,
            chunk_size=chunk_size
        )

    def get_model(self, model_name: str):
        device = self._get_device()
        self._model_config = AutoConfig.from_pretrained(
            model_name, trust_remote_code=True
        )
        return AutoModel.from_pretrained(
            model_name,
            trust_remote_code=True,
            config=self._model_config,
            unpad_inputs=True,
            use_memory_efficient_attention=True,
        ).to(device)

    def get_text_splitter(self, model, chunk_size: int = 1024, overlap: int = 100):
        return RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
            model,
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            add_start_index=True,  # If `True`, includes chunk's start index in metadata
            strip_whitespace=True,  # strips whitespace from the start and end
            separators=["\n\n", "\n", "\r\n", "\r", "\f", "\v", "\x0b", "\x0c"],
        )

    def chunk_documents(self, documents, chunk_size):
        # Yield successive n-sized chunks from documents.
        for i in range(0, len(documents), chunk_size):
            yield documents[i:i + chunk_size]

    def get_available_vram(self):
        """
        Returns available VRAM in megabytes.
        """
        try:
            # Clear any unused memory to get a fresher estimate
            torch.cuda.empty_cache()
            # Convert to MB
            total_memory = torch.cuda.get_device_properties(0).total_memory / (1024 ** 2)
            reserved_memory = torch.cuda.memory_reserved(0) / (1024 ** 2)
            available_memory = total_memory - reserved_memory
            self.logger.notice(f'Available VRAM : {available_memory}')
            # Limit by predefined max usage
            return min(available_memory, self._max_vram)
        except RuntimeError:
            # Limit by predefined max usage
            return min(RAM_AVAILABLE, self._max_vram)

    def _estimate_chunk_size(self):
        """Estimate chunk size based on VRAM usage.
        This is a simplistic heuristic and might need tuning based on empirical data
        """
        available_vram = self.get_available_vram()
        estimated_vram_per_doc = 50  # Estimated VRAM in megabytes per document, adjust based on empirical observation
        chunk_size = max(1, int(available_vram / estimated_vram_per_doc))
        self.logger.notice(
            f'Chunk size for Load Documents: {chunk_size}'
        )
        return chunk_size

    ## Utility Loaders
    ##

    async def load_documents(
        self,
        documents: list,
        collection: str = None,
        delete: bool = False
    ):
        # Load Raw Documents into the Vectorstore
        print('::: LEN >> ', len(documents), type(documents))
        if len(documents) < 1:
            self.logger.warning(
                "There is no documents to be loaded, skipping."
            )
            return

        self._documents_.extend(documents)
        if not collection:
            collection = self.collection_name

        self.logger.notice(f'Loading Documents: {len(documents)}')
        document_chunks = self.chunk_documents(
            documents,
            self._estimate_chunk_size()
        )
        async with self._store as store:
            # if delete is True, then delete the collection
            if delete is True:
                await store.delete_collection(collection)
                fdoc = documents.pop(0)
                await store.create_collection(
                    collection,
                    fdoc
                )
            for chunk in document_chunks:
                await store.load_documents(
                    chunk,
                    collection=collection
                )

    def load_pdf(self, path: Path, source_type: str = 'pdf', **kwargs):
        loader = PDFLoader(path, source_type=source_type, no_summarization=True, **kwargs)
        return loader.load()

    def load_github(
        self,
        url: str,
        github_token: str,
        lang: str = 'python',
        branch: str = 'master',
        source_type: str = 'code'
    ) -> list:
        git = GithubLoader(
            url,
            github_token=github_token,
            lang=lang,
            branch=branch,
            source_type=source_type
        )
        return git.load()

    def load_repository(
        self,
        path: Path,
        lang: str = 'python',
        source_type: str = 'code',
        **kwargs
    ) -> list:
        repo = RepositoryLoader(
            source_type=source_type,
            **kwargs
        )
        return repo.load(path, lang=lang)

    def process_websites(
        self,
        websites: list,
        source_type: str = 'website',
        **kwargs
    ) -> list:
        loader = WebLoader(
            urls=websites,
            source_type=source_type
        )
        return loader.load()

    def load_youtube_videos(
        self,
        urls: list,
        video_path: Union[str, Path],
        source_type: str = 'youtube',
        priority: int = 'high',
        language: str = 'en',
        **kwargs
    ) -> list:
        yt = YoutubeLoader(
            urls=urls,
            video_path=video_path,
            source_type=source_type,
            priority=priority,
            language=language,
            llm=self._llm,
            **kwargs
        )
        return yt.load()

    def load_vimeo_videos(
        self,
        urls: list,
        video_path: Union[str, Path],
        source_type: str = 'vimeo',
        priority: int = 'high',
        language: str = 'en',
        **kwargs
    ) -> list:
        yt = VimeoLoader(
            urls=urls,
            video_path=video_path,
            source_type=source_type,
            priority=priority,
            language=language,
            llm=self._llm,
            **kwargs
        )
        return yt.load()

    def load_directory(
        self,
        path: Union[str, Path],
        source_type: str = 'documents',
    ) -> list:
        return None

    def load_docx(
        self,
        path: Path,
        source_type: str = 'docx',
        **kwargs
    ) -> list:
        return MSWordLoader.from_path(
            path=path,
            source_type=source_type,
            **kwargs
        )

    def load_pptx(
        self,
        path: Path,
        source_type: str = 'pptx',
        **kwargs
    ) -> list:
        return PPTXLoader.from_path(
            path=path,
            source_type=source_type,
            **kwargs
        )

    def get_memory(
        self,
        session_id: str = None,
        key: str = 'chat_history',
        input_key: str = 'question',
        output_key: str = 'answer',
        size: int = 30,
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

    def get_retrieval(self, source_path: str = 'web', request: web.Request = None):
        pre_context = "\n".join(f"- {a}." for a in self.pre_instructions)
        custom_template = self.template_prompt.format_map(
            SafeDict(
                summaries=pre_context
            )
        )
        # Generate the Retrieval
        rm = RetrievalManager(
            chatbot_id=self.chatbot_id,
            chatbot_name=self.name,
            source_path=source_path,
            model=self._llm,
            store=self._store,
            memory=None,
            template=custom_template,
            kb=self.knowledge_base,
            request=request
        )
        return rm
