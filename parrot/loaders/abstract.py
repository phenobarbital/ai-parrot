from typing import Generator, Union, List, Any, Optional, TypeVar
from collections.abc import Callable
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePath
import asyncio
import torch
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    pipeline
)
from langchain.schema.runnable import RunnablePassthrough
from langchain.chains.summarize import load_summarize_chain
from langchain.docstore.document import Document
from langchain.text_splitter import (
    TokenTextSplitter
)
from langchain_core.prompts import PromptTemplate
from navconfig.logging import logging
from navigator.libs.json import JSONContent  # pylint: disable=E0611
from parrot.llms.vertex import VertexLLM
from ..conf import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    CUDA_DEFAULT_DEVICE,
    CUDA_DEFAULT_DEVICE_NUMBER
)


T = TypeVar('T')


class AbstractLoader(ABC):
    """
    Base class for all loaders. Loaders are responsible for loading data from various sources.
    """
    extensions: List[str] = ['.*']
    skip_directories: List[str] = []

    def __init__(
        self,
        *args,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        **kwargs
    ):
        self.chunk_size: int = kwargs.get('chunk_size', 50)
        self.semaphore = asyncio.Semaphore(kwargs.get('semaphore', 10))
        self.extensions = kwargs.get('extensions', self.extensions)
        self.skip_directories = kwargs.get('skip_directories', self.skip_directories)
        self.encoding = kwargs.get('encoding', 'utf-8')
        self._source_type = source_type
        self._recursive: bool = kwargs.get('recursive', False)
        self.category: str = kwargs.get('category', 'document')
        self.doctype: str = kwargs.get('doctype', 'text')
        self._summarization = kwargs.get('summarization', False)
        self._summary_model: Optional[Any] = kwargs.get('summary_model', None)
        self._use_summary_pipeline: bool = kwargs.get('use_summary_pipeline', False)
        self._use_translation_pipeline: bool = kwargs.get('use_translation_pipeline', False)
        self._translation = kwargs.get('translation', False)
        # Tokenizer
        self.tokenizer = tokenizer
        # Text Splitter
        self.text_splitter = text_splitter
        # Summarization Model:
        self.summarization_model = kwargs.get('summarizer', None)
        # Markdown Splitter:
        self.markdown_splitter = kwargs.get('markdown_splitter', None)
        if 'path' in kwargs:
            self.path = kwargs['path']
            if isinstance(self.path, str):
                self.path = Path(self.path).resolve()
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
        self.device_name = kwargs.get('device', CUDA_DEFAULT_DEVICE)
        self.cuda_number = kwargs.get('cuda_number', CUDA_DEFAULT_DEVICE_NUMBER)
        self._device = None

    def get_default_llm(self, model: str = None, model_kwargs: dict = None):
        """Return a VertexLLM instance."""
        if not model_kwargs:
            model_kwargs = {
                "temperature": DEFAULT_LLM_TEMPERATURE,
                "top_k": 30,
                "top_p": 0.5,
            }
        return VertexLLM(
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

    async def from_path(self, path: Union[str, Path], recursive: bool = False, **kwargs) -> List[asyncio.Task]:
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
            self.logger.warning(f"Path {path} is not valid.")
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
            if not hasattr(self, 'path') or self.path is None:
                raise ValueError(
                    "No source provided and self.path is not set"
                )
            source = self.path

        if isinstance(source, (str, Path, PurePath)):
            # Check if it's a URL
            if isinstance(source, str) and (source.startswith('http://') or
                                        source.startswith('https://')):
                tasks = await self.from_url(source, **kwargs)
            else:
                # Assume it's a file path or directory
                tasks = await self.from_path(source, recursive=self._recursive, **kwargs)
        elif isinstance(source, list):
            # Check if it's a list of URLs or paths
            if all(isinstance(item, str) and (item.startswith('http://') or
                                            item.startswith('https://'))
                for item in source):
                tasks = await self.from_url(source, **kwargs)
            else:
                # Assume it's a list of file paths
                path_tasks = []
                for path in source:
                    path_tasks.extend(await self.from_path(path, recursive=self._recursive, **kwargs))
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
        summary: Optional[str] = '',
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
            "summary": summary,
            "source_type": source_type or self._source_type,
            "created_at": datetime.now().strftime("%Y-%m-%d, %H:%M:%S"),
            "category": self.category,
            "document_meta": {
                **doc_metadata
            },
            **kwargs
        }
        return metadata

    def create_document(self, content: Any, path: Union[str, PurePath]) -> Document:
        """Create a Langchain Document from the content.
        Args:
            content (Any): The content to create the document from.
        Returns:
            Document: A Langchain Document.
        """
        return Document(
            page_content=content,
            metadata=self.create_metadata(
                path=path,
                doctype=self.doctype,
                source_type=self._source_type
            )
        )


    def summary_from_text(self, text: str, max_length: int = 500, min_length: int = 50) -> str:
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
            # Use Summarize Chain from Langchain
            doc = Document(page_content=text)
            summary = summarizer.invoke(
                {"input_documents": [doc]}, return_only_outputs=True
            )
            return summary.get('output_text', '')
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
                # Use Summarize Chain from Langchain
                prompt_template = """Write a summary of the following, please also identify the main theme:
                {text}
                SUMMARY:"""
                prompt = PromptTemplate.from_template(prompt_template)
                refine_template = (
                    "Your job is to produce a final summary\n"
                    "We have provided an existing summary up to a certain point: {existing_answer}\n"
                    "We have the opportunity to refine the existing summary"
                    "(only if needed) with some more context below.\n"
                    "------------\n"
                    "{text}\n"
                    "------------\n"
                    "Given the new context, refine the original summary adding more explanation."
                    "If the context isn't useful, return the original summary."
                )
                refine_prompt = PromptTemplate.from_template(refine_template)
                llm = self.get_default_llm()
                llm = llm.get_llm()
                summarize_chain = load_summarize_chain(
                    llm=llm,
                    chain_type="refine",
                    question_prompt=prompt,
                    refine_prompt=refine_prompt,
                    return_intermediate_steps=False,
                    input_key="input_documents",
                    output_key="output_text",
                )
                self._summary_model = summarize_chain
        return self._summary_model

    def translate_text(self, text: str, source_lang: str = "en", target_lang: str = "es") -> str:
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
                translation = translator.invoke(
                    {
                        "text": text,
                        "source_lang": source_lang,
                        "target_lang": target_lang
                    }
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
                    self.logger.error(f"Error loading translation model {model_name}: {e}")
                    # Fallback to using LLM for translation
                    self._use_translation_pipeline = False

            if not self._use_translation_pipeline:
                # Use LLM Chain for translation
                prompt_template = """Translate the following text from {source_lang} to {target_lang}:

                Text: {text}

                Translation:"""

                prompt = PromptTemplate(
                    template=prompt_template,
                    input_variables=["text", "source_lang", "target_lang"]
                )

                llm = self.get_default_llm().get_llm()
                # Create a simple translation chain
                translation_chain = (
                    {
                        "text": RunnablePassthrough(),
                        "source_lang": lambda x: source_lang,
                        "target_lang": lambda x: target_lang,
                    }
                    | prompt
                    | llm
                    | (lambda x: {"text": x})
                )
                self._translation_models[cache_key] = translation_chain

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

        return Document(page_content=translated_content, metadata=translation_metadata)
