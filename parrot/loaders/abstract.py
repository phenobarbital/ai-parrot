from typing import Generator, Union, List, Any, Optional, TypeVar
from collections.abc import Callable
from abc import ABC, abstractmethod
from datetime import datetime
import uuid
from pathlib import Path, PosixPath, PurePath
import asyncio
import pandas as pd
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    pipeline
)
from navconfig.logging import logging
from navigator.libs.json import JSONContent  # pylint: disable=E0611
from ..stores.models import Document
## AI Clients:
from ..clients.google import GoogleGenAIClient
from ..models.google import GoogleModel
from ..clients.groq import GroqClient
from ..models.groq import GroqModel
from ..clients.gpt import OpenAIClient
from .splitters import (
    TokenTextSplitter,
    MarkdownTextSplitter
)
from ..stores.utils.chunking import LateChunkingProcessor
from ..conf import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_GROQ_MODEL,
    CUDA_DEFAULT_DEVICE,
    CUDA_DEFAULT_DEVICE_NUMBER
)


T = TypeVar('T')


class AbstractLoader(ABC):
    """
    Base class for all loaders.
    Loaders are responsible for loading data from various sources.
    """
    extensions: List[str] = ['.*']
    skip_directories: List[str] = []

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        **kwargs
    ):
        """
        Initialize the AbstractLoader.

        Args:
            source: Path, URL, or list of paths/URLs to load from
            tokenizer: Tokenizer to use (string model name or callable)
            text_splitter: Text splitter to use
            source_type: Type of source ('file', 'url', etc.)
            **kwargs: Additional keyword arguments for configuration
        """
        self.chunk_size: int = kwargs.get('chunk_size', 800)
        self.chunk_overlap: int = kwargs.get('chunk_overlap', 100)
        self.token_size: int = kwargs.get('token_size', 20)
        self.semaphore = asyncio.Semaphore(kwargs.get('semaphore', 10))
        self.extensions = kwargs.get('extensions', self.extensions)
        self.skip_directories = kwargs.get(
            'skip_directories',
            self.skip_directories
        )
        self.encoding = kwargs.get('encoding', 'utf-8')
        self._source_type = source_type
        self._recursive: bool = kwargs.get('recursive', False)
        self.category: str = kwargs.get('category', 'document')
        self.doctype: str = kwargs.get('doctype', 'text')
        # Chunking configuration
        self._use_markdown_splitter: bool = kwargs.get('use_markdown_splitter', True)
        self._use_huggingface_splitter: bool = kwargs.get('use_huggingface_splitter', False)
        self._auto_detect_content_type: bool = kwargs.get('auto_detect_content_type', True)

        # Advanced features
        self._summarization = kwargs.get('summarization', False)
        self._summary_model: Optional[Any] = kwargs.get('summary_model', None)
        self._use_summary_pipeline: bool = kwargs.get('use_summary_pipeline', False)
        self._use_translation_pipeline: bool = kwargs.get('use_translation_pipeline', False)
        self._translation = kwargs.get('translation', False)

        # Handle source/path initialization
        self.path = None
        if source is not None:
            self.path = source
        elif 'path' in kwargs:
            self.path = kwargs['path']

        # Normalize path if it's a string
        if self.path is not None and isinstance(self.path, str):
            self.path = Path(self.path).resolve()
        elif self.path is not None and isinstance(self.path, (Path, PurePath)):
            self.path = Path(self.path).resolve()

        # Tokenizer
        self.tokenizer = tokenizer
        # Text Splitter
        self.text_splitter = kwargs.get('text_splitter', None)
        self.markdown_splitter = kwargs.get('markdown_splitter', None)

        # Initialize text splitter based on configuration
        self._setup_text_splitters(tokenizer, text_splitter, kwargs)

        # Summarization Model:
        self.summarization_model = kwargs.get('summarizer', None)
        # LLM (if required)
        self._setup_llm(kwargs)
        # Logger
        self.logger = logging.getLogger(
            f"Parrot.Loaders.{self.__class__.__name__}"
        )
        # JSON encoder:
        self._encoder = JSONContent()
        # Use CUDA if available:
        self._setup_device(kwargs)

    def _get_token_splitter(
        self,
        model_name: str = "gpt-3.5-turbo",
        chunk_size: int = 4000,
        chunk_overlap: int = 200
    ) -> TokenTextSplitter:
        """Create a TokenTextSplitter with common settings"""
        if self.text_splitter:
            return self.text_splitter
        return TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            model_name=model_name
        )

    def _get_markdown_splitter(
        self,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        strip_headers: bool = False
    ) -> MarkdownTextSplitter:
        """Create a MarkdownTextSplitter with common settings"""
        if self.text_splitter:
            return self.text_splitter
        return MarkdownTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strip_headers=strip_headers
        )

    def _create_hf_token_splitter(
        self,
        model_name: str,
        chunk_size: int = 4000,
        chunk_overlap: int = 200
    ) -> TokenTextSplitter:
        """Create a TokenTextSplitter using a HuggingFace Tokenizer"""
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        return TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            tokenizer=tokenizer
        )

    def _setup_text_splitters(self, tokenizer, text_splitter, kwargs):
        """Initialize text splitters based on configuration."""
        # Always create a markdown splitter
        self.markdown_splitter = self._get_markdown_splitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )

        # Choose primary text splitter based on configuration
        if self._use_markdown_splitter:
            self.text_splitter = text_splitter or self.markdown_splitter
        else:
            if self._use_huggingface_splitter:
                self.text_splitter = self._create_hf_token_splitter(
                    model_name=kwargs.get('model_name', 'gpt-3.5-turbo'),
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap
                )
            else:
                # Default to TokenTextSplitter
                if isinstance(tokenizer, str):
                    self.text_splitter = self._get_token_splitter(
                        model_name=tokenizer,
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.chunk_overlap
                    )
                elif callable(tokenizer):
                    self.text_splitter = TokenTextSplitter(
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.chunk_overlap,
                        tokenizer_function=tokenizer
                    )
                else:
                    # Use default TokenTextSplitter
                    self.text_splitter = TokenTextSplitter(
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.chunk_overlap,
                        model_name=kwargs.get('model_name', 'gpt-3.5-turbo')
                    )

    def _setup_llm(self, kwargs):
        """Initialize LLM if required."""
        self._use_llm = kwargs.get('use_llm', False)
        self._llm_model = kwargs.get('llm_model', None)
        self._llm_model_kwargs = kwargs.get('model_kwargs', {})
        self._llm = kwargs.get('llm', None)
        if self._use_llm:
            self._llm = self.get_default_llm(
                model=self._llm_model,
                model_kwargs=self._llm_model_kwargs,
            )

    def get_default_llm(
        self,
        model: str = None,
        model_kwargs: dict = None,
        use_groq: bool = False,
        use_openai: bool = False
    ) -> Any:
        """Return a AI Client instance."""
        if not model_kwargs:
            model_kwargs = {
                "temperature": DEFAULT_LLM_TEMPERATURE,
                "top_k": 30,
                "top_p": 0.5,
            }
        if use_groq:
            return GroqClient(
                model=model or DEFAULT_GROQ_MODEL,
                **model_kwargs
            )
        elif use_openai:
            return OpenAIClient(
                model=model or 'gpt-4-turbo',
                **model_kwargs
            )
        return GoogleGenAIClient(
            model=model or DEFAULT_LLM_MODEL,
            **model_kwargs
        )

    def _setup_device(self, kwargs):
        """Initialize device configuration."""
        self.device_name = kwargs.get('device', CUDA_DEFAULT_DEVICE)
        self.cuda_number = kwargs.get('cuda_number', CUDA_DEFAULT_DEVICE_NUMBER)
        self._device = None

    def _get_device(
        self,
        device_type: str = None,
        cuda_number: int = 0
    ):
        """
        Get device configuration for Torch and transformers.

        Returns:
            tuple: (pipeline_device_idx, torch_device, dtype)
            - pipeline_device_idx: int for HuggingFace pipeline (-1 for CPU, 0+ for GPU)
            - torch_device: torch.device object for model loading
            - dtype: torch data type for model weights
        """
        import torch
        # Default values for CPU usage
        pipeline_idx = -1  # This is what HuggingFace pipeline expects for CPU
        torch_dev = torch.device("cpu")
        dtype = torch.float32

        # Check if we're forcing CPU usage globally
        if CUDA_DEFAULT_DEVICE == 'cpu' or device_type == 'cpu':
            # CPU is explicitly requested
            return -1, torch.device('cpu'), torch.float32

        # Check for CUDA availability and use it if possible
        if torch.cuda.is_available():
            # For GPU, pipeline wants an integer index
            pipeline_idx = cuda_number  # 0 for first GPU, 1 for second, etc.
            torch_dev = torch.device(f"cuda:{cuda_number}")

            # Choose the best dtype for this GPU
            if torch.cuda.is_bf16_supported():
                dtype = torch.bfloat16
            else:
                dtype = torch.float16

            return pipeline_idx, torch_dev, dtype

        # Check for Apple Silicon GPU (MPS)
        if torch.backends.mps.is_available():
            # MPS is tricky - HuggingFace pipelines don't always support it well
            # We return "mps" as a string for pipeline, and torch.device for model
            # Note: You might need to handle this specially in your pipeline code
            return "mps", torch.device("mps"), torch.float32

        # Fallback to CPU if nothing else is available
        return -1, torch.device("cpu"), torch.float32

    def clear_cuda(self):
        self.tokenizer = None  # Reset the tokenizer
        self.text_splitter = None  # Reset the text splitter
        try:
            import torch
            torch.cuda.synchronize()  # Wait for all kernels to finish
            torch.cuda.empty_cache()  # Clear unused memory
        except Exception as e:
            self.logger.warning(f"Error clearing CUDA memory: {e}")

    async def __aenter__(self):
        """Open the loader if it has an open method."""
        # Check if the loader has an open method and call it
        if hasattr(self, "open"):
            await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close the loader if it has a close method."""
        if hasattr(self, "close"):
            await self.close()
        return True

    def supported_extensions(self):
        """Get the supported file extensions."""
        return self.extensions

    def _detect_content_type(self, document: Document) -> str:
        """
        Auto-detect content type based on document metadata and content.

        Args:
            document: Document to analyze

        Returns:
            Content type string ('markdown', 'code', 'text', etc.)
        """
        if not self._auto_detect_content_type:
            return 'text'

        # Check metadata for hints
        metadata = document.metadata or {}
        filename = metadata.get('filename', '').lower()
        source_type = metadata.get('source_type', '').lower()

        # File extension based detection
        if filename.endswith(('.md', '.markdown')):
            return 'markdown'
        elif filename.endswith(('.py', '.pyx', '.js', '.java', '.cpp', '.c', '.go', '.rs')):
            return 'code'
        elif filename.endswith(('.html', '.htm', '.xml')):
            return 'html'
        elif source_type in ['markdown', 'md']:
            return 'markdown'

        # Content based detection
        content = document.page_content[:1000].lower()  # Check first 1000 chars

        # Simple heuristics for markdown
        markdown_indicators = ['#', '```', '**', '*', '[', '](', '|', '---']
        markdown_score = sum(1 for indicator in markdown_indicators if indicator in content)

        if markdown_score >= 3:  # If multiple markdown indicators found
            return 'markdown'

        # Default to text
        return 'text'

    def _select_splitter_for_content(self, content_type: str):
        """
        Select the appropriate text splitter based on content type.

        Args:
            content_type: Detected or specified content type

        Returns:
            Appropriate text splitter
        """
        if content_type == 'markdown':
            return self.markdown_splitter
        elif content_type == 'code':
            # Use token splitter with smaller chunks for code
            return TokenTextSplitter(
                chunk_size=min(self.chunk_size, 2048),
                chunk_overlap=self.chunk_overlap,
                model_name='gpt-3.5-turbo'
            )
        else:
            # Default to the configured text splitter
            return self.text_splitter

    def is_valid_path(self, path: Union[str, Path]) -> bool:
        """Check if a path is valid."""
        if self.extensions == '*':
            return True
        if isinstance(path, str):
            path = Path(path)
        if not path.exists():
            return False
        if path.is_dir() and path.name in self.skip_directories:
            return False
        if path.is_file():
            if path.suffix not in self.extensions:
                return False
            if path.name.startswith("."):
                return False
            # check if file is empty
            if path.stat().st_size == 0:
                return False
            # check if file is inside of skip directories:
            for skip_dir in self.skip_directories:
                if path.is_relative_to(skip_dir):
                    return False
        return True

    @abstractmethod
    async def _load(self, source: Union[str, PurePath], **kwargs) -> List[Document]:
        """Load a single data/url/file from a source and return it as a Langchain Document.

        Args:
            source (str): The source of the data.

        Returns:
            List[Document]: A list of Langchain Documents.
        """
        pass

    async def from_path(
        self,
        path: Union[str, Path],
        recursive: bool = False,
        **kwargs
    ) -> List[asyncio.Task]:
        """
        Load data from a path.
        """
        tasks = []
        if isinstance(path, str):
            path = PurePath(path)
        if path.is_dir():
            for ext in self.extensions:
                glob_method = path.rglob if recursive else path.glob
                # Use glob to find all files with the specified extension
                for item in glob_method(f'*{ext}'):
                    # Check if the item is a directory and if it should be skipped
                    if set(item.parts).isdisjoint(self.skip_directories):
                        if self.is_valid_path(item):
                            tasks.append(
                                asyncio.create_task(self._load(item, **kwargs))
                            )
        elif path.is_file():
            if self.is_valid_path(path):
                tasks.append(
                    asyncio.create_task(self._load(path, **kwargs))
                )
        else:
            self.logger.warning(
                f"Path {path} is not valid."
            )
        return tasks

    async def from_url(
        self,
        url: Union[str, List[str]],
        **kwargs
    ) -> List[asyncio.Task]:
        """
        Load data from a URL.
        """
        tasks = []
        if isinstance(url, str):
            url = [url]
        for item in url:
            tasks.append(
                asyncio.create_task(self._load(item, **kwargs))
            )
        return tasks

    async def from_dataframe(
        self,
        source: pd.DataFrame,
        **kwargs
    ) -> List[asyncio.Task]:
        """
        Load data from a pandas DataFrame.
        """
        tasks = []
        if isinstance(source, pd.DataFrame):
            tasks.append(
                asyncio.create_task(self._load(source, **kwargs))
            )
        else:
            self.logger.warning(
                f"Source {source} is not a valid pandas DataFrame."
            )
        return tasks

    def chunkify(self, lst: List[T], n: int = 50) -> Generator[List[T], None, None]:
        """Split a List of objects into chunks of size n.

        Args:
            lst: The list to split into chunks
            n: The maximum size of each chunk

        Yields:
            List[T]: Chunks of the original list, each of size at most n
        """
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    async def _async_map(self, func: Callable, iterable: list) -> list:
        """Run a function on a list of items asynchronously."""
        async def async_func(item):
            async with self.semaphore:
                return await func(item)

        tasks = [async_func(item) for item in iterable]
        return await asyncio.gather(*tasks)

    async def _load_tasks(self, tasks: list) -> list:
        """Load a list of tasks asynchronously."""
        results = []

        if not tasks:
            return results

        # Create a controlled task function to limit concurrency
        async def controlled_task(task):
            async with self.semaphore:
                try:
                    return await task
                except Exception as e:
                    self.logger.error(f"Task error: {e}")
                    return e

        for chunk in self.chunkify(tasks, self.chunk_size):
            # Wrap each task with semaphore control
            controlled_tasks = [controlled_task(task) for task in chunk]
            result = await asyncio.gather(*controlled_tasks, return_exceptions=True)
            if result:
                for res in result:
                    if isinstance(res, Exception):
                        # Handle the exception
                        self.logger.error(f"Error loading {res}")
                    else:
                        # Handle both single documents and lists of documents
                        if isinstance(res, list):
                            results.extend(res)
                        else:
                            results.append(res)
        return results

    async def load(
        self,
        source: Optional[Any] = None,
        split_documents: bool = True,
        late_chunking: bool = False,
        vector_store=None,
        store_full_document: bool = True,
        auto_detect_content_type: bool = None,
        **kwargs
    ) -> List[Document]:
        """
        Load data from a source and return it as a list of Documents.

        The source can be:
        - None: Uses self.path attribute if available
        - Path or str: Treated as file path or directory
        - List[str/Path]: Treated as list of file paths
        - URL string: Treated as a URL
        - List of URLs: Treated as list of URLs

        Args:
            source (Optional[Any]): The source of the data.
            split_documents (bool): Whether to split documents into chunks, defaults to True
            late_chunking (bool): Whether to use late chunking strategy
            vector_store: Vector store instance (required for late chunking)
            store_full_document (bool): Whether to store full documents alongside chunks
            auto_detect_content_type (bool): Override auto-detection setting
            **kwargs: Additional keyword arguments

        Returns:
            List[Document]: A list of Documents (chunked if requested).
        """
        tasks = []
        # If no source is provided, use self.path
        if source is None:
            if self.path is None:
                raise ValueError(
                    "No source provided and self.path is not set. "
                    "Please provide a source parameter or set path during initialization."
                )
            source = self.path

        if isinstance(source, (str, Path, PosixPath, PurePath)):
            # Check if it's a URL
            if isinstance(source, str) and (
                source.startswith('http://') or source.startswith('https://')
            ):
                tasks = await self.from_url(source, **kwargs)
            else:
                # Assume it's a file path or directory
                tasks = await self.from_path(
                    source,
                    recursive=self._recursive,
                    **kwargs
                )
        elif isinstance(source, list):
            # Check if it's a list of URLs or paths
            if all(
                isinstance(item, str) and (
                    item.startswith('http://') or item.startswith('https://')
                ) for item in source
            ):
                tasks = await self.from_url(source, **kwargs)
            else:
                # Assume it's a list of file paths
                path_tasks = []
                for path in source:
                    path_tasks.extend(
                        await self.from_path(path, recursive=self._recursive, **kwargs)
                    )
                tasks = path_tasks
        elif isinstance(source, pd.DataFrame):
            tasks = await self.from_dataframe(source, **kwargs)
        else:
            raise ValueError(
                f"Unsupported source type: {type(source)}"
            )
        # Load tasks and get raw documents
        documents = []
        if tasks:
            results = await self._load_tasks(tasks)
            documents = results

        # Apply chunking if requested
        if split_documents and documents:
            self.logger.debug(
                f"Splitting {len(documents)} documents into chunks..."
            )

            if late_chunking and vector_store is None:
                raise ValueError(
                    "Vector store is required when using late_chunking=True"
                )

            documents = await self.chunk_documents(
                documents=documents,
                use_late_chunking=late_chunking,
                vector_store=vector_store,
                store_full_document=store_full_document,
                auto_detect_content_type=auto_detect_content_type
            )

            self.logger.debug(
                f"Document chunking complete: {len(documents)} final documents"
            )

        return documents

    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        **kwargs
    ):
        if not doc_metadata:
            doc_metadata = {}
        if isinstance(path, PurePath):
            origin = path.name
            url = f'file://{path.name}'
            filename = path
        else:
            origin = path
            url = path
            filename = f'file://{path}'
        metadata = {
            "url": url,
            "source": origin,
            "filename": str(filename),
            "type": doctype,
            "source_type": source_type or self._source_type,
            "created_at": datetime.now().strftime("%Y-%m-%d, %H:%M:%S"),
            "category": self.category,
            "document_meta": {
                **doc_metadata
            },
            **kwargs
        }
        return metadata

    def create_document(
        self,
        content: Any,
        path: Union[str, PurePath],
        metadata: Optional[dict] = None,
        **kwargs
    ) -> Document:
        """Create a Langchain Document from the content.
        Args:
            content (Any): The content to create the document from.
        Returns:
            Document: A Langchain Document.
        """
        if metadata:
            _meta = metadata
        else:
            _meta = self.create_metadata(
                path=path,
                doctype=self.doctype,
                source_type=self._source_type,
                **kwargs
            )
        return Document(
            page_content=content,
            metadata=_meta
        )

    async def summary_from_text(
        self,
        text: str,
        max_length: int = 500,
        min_length: int = 50
    ) -> str:
        """
        Get a summary of a text.
        """
        if not text:
            return ''
        try:
            summarizer = self.get_summarization_model()
            if self._use_summary_pipeline:
                # Use Huggingface pipeline
                content = summarizer(
                    text,
                    max_length=max_length,
                    min_length=min_length,
                    do_sample=False,
                    truncation=True
                )
                return content[0].get('summary_text', '')
            # Use Summarize Method from GroqClient
            system_prompt = f"""
Your job is to produce a final summary from the following text and identify the main theme.
- The summary should be concise and to the point.
- The summary should be no longer than {max_length} characters and no less than {min_length} characters.
- The summary should be in a single paragraph.
"""
            summary = await summarizer.summarize_text(
                text=text,
                model=GroqModel.LLAMA_3_3_70B_VERSATILE,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=1000,
                top_p=0.5
            )
            return summary.output
        except Exception as e:
            self.logger.error(
                f'ERROR on summary_from_text: {e}'
            )
            return ""

    def get_summarization_model(
        self,
        model_name: str = 'facebook/bart-large-cnn'
    ):
        if not self._summary_model:
            if self._use_summary_pipeline:
                _, pipe_dev, torch_dtype = self._get_device()
                summarize_model = AutoModelForSeq2SeqLM.from_pretrained(
                    model_name,
                )
                summarize_tokenizer = AutoTokenizer.from_pretrained(
                    model_name,
                    padding_side="left"
                )
                self._summary_model = pipeline(
                    "summarization",
                    model=summarize_model,
                    tokenizer=summarize_tokenizer,
                    device=pipe_dev,             # 0 for CUDA, mps device, or -1
                    torch_dtype=torch_dtype if pipe_dev != -1 else None,
                )
            else:
                # Use Groq for Summarization:
                self._summary_model = GroqClient()
        return self._summary_model

    def translate_text(
        self,
        text: str,
        source_lang: str = None,
        target_lang: str = "es"
    ) -> str:
        """
        Translate text from source language to target language.

        Args:
            text: Text to translate
            source_lang: Source language code (default: 'en')
            target_lang: Target language code (default: 'es')

        Returns:
            Translated text
        """
        if not text:
            return ''
        try:
            translator = self.get_translation_model(source_lang, target_lang)
            if self._use_translation_pipeline:
                # Use Huggingface pipeline
                content = translator(
                    text,
                    max_length=len(text) * 2,  # Allow for expansion in target language
                    truncation=True
                )
                return content[0].get('translation_text', '')
            else:
                # Use LLM for translation
                translation = translator.translate_text(
                    text=text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    model=GoogleModel.GEMINI_2_5_FLASH_LITE_PREVIEW,
                    temperature=0.1,
                    max_tokens=1000
                )
                return translation.get('text', '')
        except Exception as e:
            self.logger.error(f'ERROR on translate_text: {e}')
            return ""

    def get_translation_model(
        self,
        source_lang: str = "en",
        target_lang: str = "es",
        model_name: str = None
    ):
        """
        Get or create a translation model.

        Args:
            source_lang: Source language code
            target_lang: Target language code
            model_name: Optional model name override

        Returns:
            Translation model/chain
        """
        # Create a cache key for the language pair
        cache_key = f"{source_lang}_{target_lang}"

        # Check if we already have a model for this language pair
        if not hasattr(self, '_translation_models'):
            self._translation_models = {}

        if cache_key not in self._translation_models:
            if self._use_translation_pipeline:
                # Select appropriate model based on language pair if not specified
                if model_name is None:
                    if source_lang == "en" and target_lang in ["es", "fr", "de", "it", "pt", "ru"]:
                        model_name = "Helsinki-NLP/opus-mt-en-ROMANCE"
                    elif source_lang in ["es", "fr", "de", "it", "pt"] and target_lang == "en":
                        model_name = "Helsinki-NLP/opus-mt-ROMANCE-en"
                    else:
                        # Default to a specific model for the language pair
                        model_name = f"Helsinki-NLP/opus-mt-{source_lang}-{target_lang}"

                try:
                    translate_model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
                    translate_tokenizer = AutoTokenizer.from_pretrained(model_name)

                    self._translation_models[cache_key] = pipeline(
                        "translation",
                        model=translate_model,
                        tokenizer=translate_tokenizer
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error loading translation model {model_name}: {e}"
                    )
                    # Fallback to using LLM for translation
                    self._use_translation_pipeline = False

            if not self._use_translation_pipeline:
                # Use LLM for translation
                translation_model = self.get_default_llm(
                    model=GoogleModel.GEMINI_2_5_FLASH_LITE_PREVIEW
                )
                self._translation_models[cache_key] = translation_model

        return self._translation_models[cache_key]

    def create_translated_document(
        self,
        content: str,
        metadata: dict,
        source_lang: str = "en",
        target_lang: str = "es"
    ) -> Document:
        """
        Create a document with translated content.

        Args:
            content: Original content
            metadata: Document metadata
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            Document with translated content
        """
        translated_content = self.translate_text(content, source_lang, target_lang)

        # Clone the metadata and add translation info
        translation_metadata = metadata.copy()
        translation_metadata.update({
            "original_language": source_lang,
            "language": target_lang,
            "is_translation": True
        })

        return Document(
            page_content=translated_content,
            metadata=translation_metadata
        )

    def saving_file(self, filename: PurePath, data: Any):
        """Save data to a file.

        Args:
            filename (PurePath): The path to the file.
            data (Any): The data to save.
        """
        with open(filename, 'wb') as f:
            f.write(data)
            f.flush()
        print(f':: Saved File on {filename}')

    async def chunk_documents(
        self,
        documents: List[Document],
        use_late_chunking: bool = False,
        vector_store=None,
        store_full_document: bool = True,
        auto_detect_content_type: bool = None
    ) -> List[Document]:
        """
        Chunk documents using the configured text splitter or late chunking strategy.

        Args:
            documents: List of documents to chunk
            use_late_chunking: Whether to use late chunking strategy
            vector_store: Vector store instance (required for late chunking)
            store_full_document: Whether to store full documents alongside chunks (late chunking only)
            auto_detect_content_type: Override auto-detection setting

        Returns:
            List of chunked documents
        """
        if use_late_chunking:
            return await self._chunk_with_late_chunking(
                documents, vector_store, store_full_document
            )
        else:
            return self._chunk_with_text_splitter(
                documents, auto_detect_content_type
            )

    def _chunk_with_text_splitter(
        self,
        documents: List[Document],
        auto_detect_content_type: bool = None
    ) -> List[Document]:
        """
        Chunk documents using regular text splitters.

        Args:
            documents: List of documents to chunk
            auto_detect_content_type: Override auto-detection setting

        Returns:
            List of chunked documents
        """
        chunked_docs = []
        detect_content = auto_detect_content_type if auto_detect_content_type is not None else self._auto_detect_content_type

        for doc in documents:
            try:
                # Detect content type and select appropriate splitter
                if detect_content:
                    content_type = self._detect_content_type(doc)
                    splitter = self._select_splitter_for_content(content_type)
                    # self.logger.debug(f"Detected content type: {content_type} for document")
                else:
                    content_type = 'text'
                    splitter = self.text_splitter

                # Create chunks using the selected splitter
                chunks = splitter.create_chunks(
                    text=doc.page_content,
                    metadata=doc.metadata
                )

                # Convert chunks to Document objects
                for chunk in chunks:
                    chunked_doc = Document(
                        page_content=chunk.text,
                        metadata={
                            **chunk.metadata,
                            'chunk_id': chunk.chunk_id,
                            'token_count': chunk.token_count,
                            'start_position': chunk.start_position,
                            'end_position': chunk.end_position,
                            'content_type': content_type,
                            'splitter_type': splitter.__class__.__name__,
                            'is_chunk': True,
                            'parent_document_id': doc.metadata.get('document_id', f"doc_{uuid.uuid4().hex[:8]}")
                        }
                    )
                    chunked_docs.append(chunked_doc)

            except Exception as e:
                self.logger.error(f"Error chunking document: {e}")
                # Fall back to adding the original document
                chunked_docs.append(doc)

        self.logger.info(f"Chunked {len(documents)} documents into {len(chunked_docs)} chunks")
        return chunked_docs

    async def _chunk_with_late_chunking(
        self,
        documents: List[Document],
        vector_store=None,
        store_full_document: bool = True
    ) -> List[Document]:
        """
        Chunk documents using late chunking strategy.

        Args:
            documents: List of documents to chunk
            vector_store: Vector store instance (required)
            store_full_document: Whether to store full documents alongside chunks

        Returns:
            List of chunked documents (and optionally full documents)
        """
        if LateChunkingProcessor is None:
            self.logger.warning(
                "LateChunkingProcessor not available, falling back to regular chunking"
            )
            return self._chunk_with_text_splitter(documents)

        if vector_store is None:
            raise ValueError("Vector store is required for late chunking strategy")

        chunked_docs = []

        # Initialize late chunking processor
        chunking_processor = LateChunkingProcessor(
            vector_store=vector_store,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )

        for doc_idx, document in enumerate(documents):
            try:
                document_id = document.metadata.get('document_id', f"doc_{doc_idx:06d}_{uuid.uuid4().hex[:8]}")

                # Process document with late chunking
                _, chunk_infos = await chunking_processor.process_document_late_chunking(
                    document_text=document.page_content,
                    document_id=document_id,
                    metadata=document.metadata
                )

                # Store full document if requested
                if store_full_document:
                    full_doc_metadata = {
                        **(document.metadata or {}),
                        'document_id': document_id,
                        'is_full_document': True,
                        'total_chunks': len(chunk_infos),
                        'document_type': 'parent',
                        'chunking_strategy': 'late_chunking'
                    }

                    full_doc = Document(
                        page_content=document.page_content,
                        metadata=full_doc_metadata
                    )
                    chunked_docs.append(full_doc)

                # Add all chunks as documents
                for chunk_info in chunk_infos:
                    chunk_doc = Document(
                        page_content=chunk_info.chunk_text,
                        metadata=chunk_info.metadata
                    )
                    chunked_docs.append(chunk_doc)

            except Exception as e:
                self.logger.error(f"Error in late chunking for document {doc_idx}: {e}")
                # Fall back to adding the original document
                chunked_docs.append(document)

        self.logger.info(
            f"Late chunking processed {len(documents)} documents into {len(chunked_docs)} items"
        )
        return chunked_docs
