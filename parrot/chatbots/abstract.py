"""
Foundational base of every Chatbot and Agent in ai-parrot.
"""
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
)
# Langchain
from langchain.docstore.document import Document
from langchain.memory import (
    ConversationBufferMemory
)
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter
)
from langchain_community.chat_message_histories import (
    RedisChatMessageHistory
)
# Navconfig
from navconfig import BASE_DIR
from navconfig.exceptions import ConfigError  # pylint: disable=E0611
from navconfig.logging import logging
from asyncdb.exceptions import NoDataFound

## LLM configuration
from ..llms import get_llm, AbstractLLM

## Vector Database configuration:
from ..stores import get_vectordb

from ..utils import SafeDict, parse_toml_config
from .retrievals import RetrievalManager
from ..conf import (
    EMBEDDING_DEVICE,
    MAX_VRAM_AVAILABLE,
    RAM_AVAILABLE,
    default_dsn,
    REDIS_HISTORY_URL,
    EMBEDDING_DEFAULT_MODEL
)
from ..interfaces import DBInterface
from ..models import ChatbotModel


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
        # Start initialization:
        self.kb = None
        self.knowledge_base: list = []
        # Chatbot ID:
        self.chatbot_id: uuid.UUID = kwargs.get(
            'chatbot_id',
            str(uuid.uuid4().hex)
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
        # Overrriding LLM object
        self._llm_obj: Callable = kwargs.get('llm', None)
        # LLM base Object:
        self._llm: Callable = None

        # Max VRAM usage:
        self._max_vram = int(
            kwargs.get('max_vram', MAX_VRAM_AVAILABLE)
        )

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
        return (
            "I am a language model trained by Google.\n"
            "I am designed to provide helpful information to users."
            "Remember to maintain a professional tone."
            "If I cannot find relevant information in the documents,"
            "I will indicate this and suggest alternative avenues for the user to find an answer."
        )

    def default_backstory(self) -> str:
        return (
            "help with Human Resources related queries or knowledge-based questions about T-ROC Global.\n"
            "You can ask me about the company's products and services, the company's culture, the company's clients.\n"
            "You have the capability to read and understand various Human Resources documents, "
            "such as employee handbooks, policy documents, onboarding materials, company's website, and more.\n"
            "I can also provide information about the company's policies and procedures, benefits, and other HR-related topics."
        )

    async def configure(self, app = None) -> None:
        if app is None:
            self.app = None
        else:
            if isinstance(app, web.Application):
                self.app = app  # register the app into the Extension
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
                f"Loading Bot {self.name} from config: {config_file.name}"
            )
        if (bot := await self.bot_exists(name=self.name, uuid=self.chatbot_id)):
            self.logger.notice(
                f"Loading Bot {self.name} from Database: {bot.chatbot_id}"
            )
            # Bot exists on Database, Configure from the Database
            await self.from_database(bot, config_file)
        elif config_file.exists():
            # Configure from the TOML file
            await self.from_config_file(config_file)
        else:
            raise ValueError(
                f'Bad configuration procedure for bot {self.name}'
            )
        # adding this configured chatbot to app:
        if self.app:
            self.app[f"{self.name.lower()}_chatbot"] = self

    def _configure_llm(self, llm, config):
        """
        Configuration of LLM.
        """
        if isinstance(self._llm_obj, AbstractLLM):
            self._llm = self._llm_obj.get_llm()
        elif self._llm_obj is not None:
            self._llm = self._llm_obj
        else:
            if llm:
                # LLM:
                self._llm_obj = get_llm(
                    llm,
                    **config
                )
                # getting langchain LLM from Obj:
                self._llm = self._llm_obj.get_llm()
            else:
                raise ValueError(
                    f"{self.name}: LLM is not defined in bot Configuration."
                )

    def _from_bot(self, bot, key, config, default) -> Any:
        value = getattr(bot, key, None)
        file_value = config.get(key, default)
        return value if value else file_value

    def _from_db(self, botobj, key, default = None) -> Any:
        value = getattr(botobj, key, default)
        return value if value else default

    async def bot_exists(
        self,
        name: str = None,
        uuid: uuid.UUID = None
    ) -> Union[ChatbotModel, bool]:
        """Check if the Chatbot exists in the Database."""
        db = self.get_database('pg', dsn=default_dsn)
        async with await db.connection() as conn:  # pylint: disable=E1101
            ChatbotModel.Meta.connection = conn
            try:
                if self.chatbot_id:
                    try:
                        bot = await ChatbotModel.get(chatbot_id=uuid)
                    except Exception:
                        bot = await ChatbotModel.get(name=name)
                else:
                    bot = await ChatbotModel.get(name=self.name)
                if bot:
                    return bot
            except NoDataFound:
                return False

    async def from_database(
        self,
        bot: Union[ChatbotModel, None] = None,
        config_file: PurePath = None
    ) -> None:
        """Load the Chatbot Configuration from the Database."""
        if not bot:
            db = self.get_database('pg', dsn=default_dsn)
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
                    raise ConfigError(
                        f"Chatbot {self.name} not found in the database."
                    )
        # Start Bot configuration from Database:
        if config_file and config_file.exists():
            file_config = await parse_toml_config(config_file)
            # Knowledge Base come from file:
            # Contextual knowledge-base
            self.kb = file_config.get('knowledge-base', [])
            if self.kb:
                self.knowledge_base = self.create_kb(
                    self.kb.get('data', [])
                )
        self.name = self._from_db(bot, 'name', default=self.name)
        self.chatbot_id = str(self._from_db(bot, 'chatbot_id', default=self.chatbot_id))
        self.description = self._from_db(bot, 'description', default=self.description)
        self.role = self._from_db(bot, 'role', default=self.role)
        self.goal = self._from_db(bot, 'goal', default=self.goal)
        self.rationale = self._from_db(bot, 'rationale', default=self.rationale)
        self.backstory = self._from_db(bot, 'backstory', default=self.backstory)
        # company information:
        self.company_information = self._from_db(
            bot, 'company_information', default=self.company_information
        )
        # LLM Configuration:
        llm = self._from_db(bot, 'llm', default='VertexLLM')
        llm_config = self._from_db(bot, 'llm_config', default={})
        # Configuration of LLM:
        self._configure_llm(llm, llm_config)
        # Other models:
        self.embedding_model_name = self._from_db(
            bot, 'embedding_name', None
        )
        self.tokenizer_model_name = self._from_db(
            bot, 'tokenizer', None
        )
        self.summarization_model = self._from_db(
            bot, 'summarize_model', "facebook/bart-large-cnn"
        )
        self.classification_model = self._from_db(
            bot, 'classification_model', None
        )
        # Database Configuration:
        db_config = bot.database
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
        self._store = get_vectordb(
            vector_db,
            embeddings=embed,
            use_bge=self.use_bge,
            use_fastembed=self.use_fastembed,
            **config
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
        async with self._store.connection(alias='default') as store:
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
