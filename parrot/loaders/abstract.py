from typing import Generator, Union, List, Any, Optional, TypeVar
from collections.abc import Callable
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PosixPath, PurePath
import asyncio
import torch
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
        self.chunk_size: int = kwargs.get('chunk_size', 5000)
        self.chunk_overlap: int = kwargs.get('chunk_overlap', 20)
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
        self._use_markdown_splitter: bool = kwargs.get(
            'use_markdown_splitter', True
        )
        self._use_huggingface_splitter: bool = kwargs.get(
            'use_huggingface_splitter', False
        )
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
        self.text_splitter = None
        self.markdown_splitter = kwargs.get('markdown_splitter', None)
        if self._use_markdown_splitter:
            splitter = text_splitter or self._get_markdown_splitter()
            self.markdown_splitter = self._get_markdown_splitter()
        else:
            if self._use_huggingface_splitter:
                splitter = self._create_hf_token_splitter(
                    model_name=kwargs.get('model_name', 'gpt-3.5-turbo'),
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap
                )
            else:
                # Default to TokenTextSplitter
                if isinstance(tokenizer, str):
                    splitter = self._get_token_splitter(
                        model_name=tokenizer,
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.chunk_overlap
                    )
                elif callable(tokenizer):
                    splitter = TokenTextSplitter(
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.chunk_overlap,
                        tokenizer_function=tokenizer
                    )
                else:
                    # Use default TokenTextSplitter
                    splitter = TokenTextSplitter(
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.chunk_overlap,
                        model_name=kwargs.get('model_name', 'gpt-3.5-turbo')
                    )
        self.text_splitter = splitter
        # Summarization Model:
        self.summarization_model = kwargs.get('summarizer', None)
        # LLM (if required)
        self._use_llm = kwargs.get('use_llm', False)
        self._llm_model = kwargs.get('llm_model', None)
        self._llm_model_kwargs = kwargs.get('model_kwargs', {})
        self._llm = kwargs.get('llm', None)
        if self._use_llm:
            self._llm = self.get_default_llm(
                model=self._llm_model,
                model_kwargs=self._llm_model_kwargs,
            )
        self.logger = logging.getLogger(
            f"Parrot.Loaders.{self.__class__.__name__}"
        )
        # JSON encoder:
        self._encoder = JSONContent()
        # Use CUDA if available:
        self.device_name = kwargs.get(
            'device', CUDA_DEFAULT_DEVICE
        )
        self.cuda_number = kwargs.get(
            'cuda_number',
            CUDA_DEFAULT_DEVICE_NUMBER
        )
        self._device = None

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

    def _get_device(
        self,
        device_type: str = None,
        cuda_number: int = 0
    ):
        """Get Default device for Torch and transformers.

        """
        if device_type == 'cpu':
            return torch.device('cpu')
        if device_type == 'cuda':
            return torch.device(f'cuda:{cuda_number}')
        if CUDA_DEFAULT_DEVICE == 'cpu':
            # Use CPU if CUDA is not available
            return torch.device('cpu')
        if torch.cuda.is_available():
            # Use CUDA GPU if available
            return torch.device(f'cuda:{cuda_number}')
        if torch.backends.mps.is_available():
            # Use CUDA Multi-Processing Service if available
            return torch.device("mps")
        if CUDA_DEFAULT_DEVICE == 'cuda':
            return torch.device(f'cuda:{cuda_number}')
        else:
            return torch.device(CUDA_DEFAULT_DEVICE)

    def clear_cuda(self):
        self.tokenizer = None  # Reset the tokenizer
        self.text_splitter = None  # Reset the text splitter
        torch.cuda.synchronize()  # Wait for all kernels to finish
        torch.cuda.empty_cache()  # Clear unused memory

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
        Load data from a path. This method should be overridden by subclasses.
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
        Load data from a URL. This method should be overridden by subclasses.
        """
        tasks = []
        if isinstance(url, str):
            url = [url]
        for item in url:
            tasks.append(
                asyncio.create_task(self._load(item, **kwargs))
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
        **kwargs
    ) -> List[Document]:
        """Load data from a source and return it as a list of Langchain Documents.

        The source can be:
        - None: Uses self.path attribute if available
        - Path or str: Treated as file path or directory
        - List[str/Path]: Treated as list of file paths
        - URL string: Treated as a URL
        - List of URLs: Treated as list of URLs

        Args:
            source (Optional[Any]): The source of the data.

        Returns:
            List[Document]: A list of Langchain Documents.
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
        else:
            raise ValueError(
                f"Unsupported source type: {type(source)}"
            )
        # Load tasks
        if tasks:
            results = await self._load_tasks(tasks)
            return results

        return []

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
                    tokenizer=summarize_tokenizer
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

    def chunk_documents(
        self,
        documents: List[Document],
        use_late_chunking: bool = False
    ) -> List[Document]:
        """
        Chunk documents using the configured text splitter.

        Args:
            documents: List of documents to chunk
            use_late_chunking: Whether to use late chunking strategy

        Returns:
            List of chunked documents
        """
        chunked_docs = []

        for doc in documents:
            if use_late_chunking:
                # Use late chunking strategy
                pass
            else:
                # Use regular text splitter
                chunks = self.text_splitter.create_chunks(
                    text=doc.page_content,
                    metadata=doc.metadata
                )

                for chunk in chunks:
                    chunked_doc = Document(
                        page_content=chunk.text,
                        metadata={
                            **chunk.metadata,
                            'chunk_id': chunk.chunk_id,
                            'token_count': chunk.token_count,
                            'start_position': chunk.start_position,
                            'end_position': chunk.end_position
                        }
                    )
                    chunked_docs.append(chunked_doc)

        return chunked_docs
