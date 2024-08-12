"""Loaders are classes that are responsible for loading data from a source
and returning it as a Langchain Document.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import List, Union, Optional, Any
from pathlib import Path, PurePath
import torch
from langchain.docstore.document import Document
from langchain.chains.summarize import load_summarize_chain
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter,
    TokenTextSplitter
)
from langchain_core.prompts import PromptTemplate
from langchain_core.document_loaders.blob_loaders import Blob
from langchain_community.llms.huggingface_pipeline import HuggingFacePipeline

from navconfig.logging import logging
from navigator.libs.json import JSONContent  # pylint: disable=E0611
from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    AutoConfig,
    AutoModel,
    pipeline
)
from ..conf import EMBEDDING_DEVICE, EMBEDDING_DEFAULT_MODEL


logging.getLogger(name='httpx').setLevel(logging.WARNING)
logging.getLogger(name='httpcore').setLevel(logging.WARNING)
logging.getLogger(name='pdfminer').setLevel(logging.WARNING)
logging.getLogger(name='langchain_community').setLevel(logging.WARNING)
logging.getLogger(name='numba').setLevel(logging.WARNING)
logging.getLogger(name='PIL').setLevel(level=logging.WARNING)


def as_string(self) -> str:
    """Read data as a string."""
    if self.data is None and self.path:
        with open(str(self.path), "r", encoding=self.encoding) as f:
            try:
                return f.read()
            except UnicodeDecodeError:
                try:
                    with open(str(self.path), "r", encoding="latin-1") as f:
                        return f.read()
                except UnicodeDecodeError:
                    with open(str(self.path), "rb") as f:
                        return f.read().decode("utf-8", "replace")
    elif isinstance(self.data, bytes):
        return self.data.decode(self.encoding)
    elif isinstance(self.data, str):
        return self.data
    else:
        raise ValueError(f"Unable to get string for blob {self}")

# Monkey patch the Blob class's as_string method
Blob.as_string = as_string


class AbstractLoader(ABC):
    """
    Abstract class for Document loaders.
    """
    _extension: List[str] = ['.txt']
    encoding: str = 'utf-8'
    skip_directories: List[str] = []
    _chunk_size: int = 768

    def __init__(
        self,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        **kwargs
    ):
        self.tokenizer = tokenizer
        self._summary_model = None
        self.text_splitter = text_splitter
        self._device = self._get_device()
        self._chunk_size = kwargs.get('chunk_size', 768)
        self._no_summarization = bool(
            kwargs.get('no_summarization', False)
        )
        self.summarization_model = kwargs.get(
            'summarization_model',
            "facebook/bart-large-cnn"
        )
        self._no_summarization = bool(
            kwargs.get('no_summarization', False)
        )
        self._source_type = source_type
        self.logger = logging.getLogger(
            f"Loader.{self.__class__.__name__}"
        )
        if 'extension' in kwargs:
            self._extension = kwargs['extension']
        self.encoding = kwargs.get('encoding', 'utf-8')
        self.skip_directories: List[str] = kwargs.get('skip_directories', [])
        # LLM (if required)
        self._llm = kwargs.get('llm', None)
        if not self.tokenizer:
            self.tokenizer = self.default_tokenizer()
        elif isinstance(self.tokenizer, str):
            self.tokenizer = self.get_tokenizer(
                model_name=self.tokenizer
            )
        if not text_splitter:
            self.text_splitter = self.default_splitter(
                model=self.tokenizer
            )
        # JSON encoder:
        self._encoder = JSONContent()


    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.post_load()

    def default_tokenizer(self):
        return self.get_tokenizer(
            EMBEDDING_DEFAULT_MODEL,
            chunk_size=768
        )

    def get_tokenizer(self, model_name: str, chunk_size: int = 768):
        return AutoTokenizer.from_pretrained(
            model_name,
            chunk_size=chunk_size
        )

    def _get_device(self, cuda_number: int = 0):
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

    def get_model(self, model_name: str):
        self._model_config = AutoConfig.from_pretrained(
            model_name, trust_remote_code=True
        )
        return AutoModel.from_pretrained(
            model_name,
            trust_remote_code=True,
            config=self._model_config,
            unpad_inputs=True,
            use_memory_efficient_attention=True,
        ).to(self._device)

    def get_summarization_model(self, model_name: str = 'facebook/bart-large-cnn'):
        if self._no_summarization is True:
            return None
        if not self._summary_model:
            summarize_model = AutoModelForSeq2SeqLM.from_pretrained(
                model_name,
                device_map="auto",
                torch_dtype=torch.bfloat16,
                trust_remote_code=True
            )
            summarize_tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                padding_side="left"
            )
            pipe_summary = pipeline(
                "summarization",
                model=summarize_model,
                tokenizer=summarize_tokenizer,
                batch_size=True,
                max_new_tokens=500,
                min_new_tokens=300,
                use_fast=True
            )
            self._summary_model = HuggingFacePipeline(
                model_id=model_name,
                pipeline=pipe_summary,
                verbose=True
            )
        return self._summary_model

    def get_text_splitter(self, model, chunk_size: int = 2000, overlap: int = 100):
        return RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
            model,
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            add_start_index=True,  # If `True`, includes chunk's start index in metadata
            strip_whitespace=True,  # strips whitespace from the start and end
            separators=["\n\n", "\n", "\r\n", "\r", "\f", "\v", "\x0b", "\x0c"],
        )

    def default_splitter(self, model: Callable):
        """Get the text splitter."""
        return self.get_text_splitter(
            model,
            chunk_size=2000,
            overlap=100
        )

    def get_summary_from_text(self, text: str) -> str:
        """
        Get a summary of a text.
        """
        if not text:
            # NO data to be summarized
            return ''
        try:
            splitter = TokenTextSplitter(
                chunk_size=5000,
                chunk_overlap=100,
            )
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
            if self._llm:
                llm = self._llm
            else:
                llm = self.get_summarization_model(
                    self.summarization_model
                )
                if not llm:
                    return ''
            summarize_chain = load_summarize_chain(
                llm=llm,
                chain_type="refine",
                question_prompt=prompt,
                refine_prompt=refine_prompt,
                return_intermediate_steps=True,
                input_key="input_documents",
                output_key="output_text",
            )
            chunks = splitter.split_text(text)
            documents = [Document(page_content=chunk) for chunk in chunks]
            summary = summarize_chain.invoke(
                {"input_documents": documents}, return_only_outputs=True
            )
            return summary['output_text']
        except Exception as e:
            print('ERROR in get_summary_from_text:', e)
            return ""

    def split_documents(self, documents: List[Document], max_tokens: int = None) -> List[Document]:
        """Split the documents into chunks."""
        if not max_tokens:
            max_tokens = self._chunk_size
        split_documents = []
        for doc in documents:
            metadata = doc.metadata.copy()
            chunks = self.text_splitter.split_text(doc.page_content)
            for chunk in chunks:
                split_documents.append(
                    Document(page_content=chunk, metadata=metadata)
                )
        return split_documents

    def split_by_tokens(self, documents: List[Document], max_tokens: int = 768) -> List[Document]:
        """Split the documents into chunks."""
        split_documents = []
        current_chunk = []
        for doc in documents:
            metadata = doc.metadata.copy()
            tokens = self.tokenizer.tokenize(doc.page_content)
            with torch.no_grad():
                current_chunk = []
                for token in tokens:
                    current_chunk.append(token)
                    if len(current_chunk) >= max_tokens:
                        chunk_text = self.tokenizer.convert_tokens_to_string(current_chunk)
                        # Create a new Document for this chunk, preserving metadata
                        split_doc = Document(
                            page_content=chunk_text,
                            metadata=metadata
                        )
                        split_documents.append(split_doc)
                        current_chunk = []  # Reset for the next chunk
            # Handle the last chunk if it didn't reach the max_tokens limit
            if current_chunk:
                chunk_text = self.tokenizer.convert_tokens_to_string(current_chunk)
                split_documents.append(
                    Document(page_content=chunk_text, metadata=metadata)
                )
            del tokens, current_chunk
            torch.cuda.empty_cache()
        return split_documents

    def post_load(self):
        self.tokenizer = None # Reset the tokenizer
        self.text_splitter = None # Reset the text splitter
        torch.cuda.synchronize()  # Wait for all kernels to finish
        torch.cuda.empty_cache()  # Clear unused memory

    def read_bytes(self, path: Union[str, PurePath]) -> bytes:
        """Read the bytes from a file.

        Args:
            path (Union[str, PurePath]): The path to the file.

        Returns:
            bytes: The bytes of the file.
        """
        if isinstance(path, str):
            path = PurePath(path)
        with open(str(path), 'rb') as f:
            return f.read()

    def open_bytes(self, path: Union[str, PurePath]) -> Any:
        """Open the bytes from a file.

        Args:
            path (Union[str, PurePath]): The path to the file.

        Returns:
            Any: The bytes of the file.
        """
        if isinstance(path, str):
            path = PurePath(path)
        return open(str(path), 'rb')

    def read_string(self, path: Union[str, PurePath]) -> str:
        """Read the string from a file.

        Args:
            path (Union[str, PurePath]): The path to the file.

        Returns:
            str: The string of the file.
        """
        if isinstance(path, str):
            path = PurePath(path)
        with open(str(path), 'r', encoding=self.encoding) as f:
            return f.read()

    def _check_path(
        self,
        path: PurePath,
        suffix: Optional[List[str]] = None
    ) -> bool:
        """Check if the file path exists.
        Args:
            path (PurePath): The path to the file.
        Returns:
            bool: True if the file exists, False otherwise.
        """
        if isinstance(path, str):
            path = Path(path).resolve()
        if not suffix:
            suffix = self._extension
        return path.exists() and path.is_file() and path.suffix in suffix


    @abstractmethod
    def load(self, path: Union[str, PurePath]) -> List[Document]:
        """Load data from a source and return it as a Langchain Document.

        Args:
            path (str): The source of the data.

        Returns:
            List[Document]: A list of Langchain Documents.
        """
        pass

    @abstractmethod
    def parse(self, source: Any) -> List[Document]:
        """Parse data from a source and return it as a Langchain Document.

        Args:
            source (Any): The source of the data.

        Returns:
            List[Document]: A list of Langchain Documents.
        """
        pass

    @classmethod
    def from_path(
        cls,
        path: Union[str, PurePath],
        text_splitter: Callable,
        source_type: str = 'file',
        **kwargs
    ) -> List[Document]:
        """Load Multiple documents from a Path

        Args:
            path (Union[str, PurePath]): The path to the file.

        Returns:
            -> List[Document]: A list of Langchain Documents.
        """
        if isinstance(path, str):
            path = PurePath(path)
        if path.is_dir():
            documents = []
            obj = cls(
                tokenizer=kwargs.pop('tokenizer', None),
                text_splitter=text_splitter,
                source_type=source_type,
            )
            for ext in cls._extension:
                for item in path.glob(f'*{ext}'):
                    if set(item.parts).isdisjoint(cls.skip_directories):
                        documents += obj.load(path=item, **kwargs)
                        # documents += cls.load(cls, path=item, **kwargs)
            return documents

    @classmethod
    def from_url(
        cls,
        urls: List[str],
        text_splitter: Callable,
        source_type: str = 'content',
        **kwargs
    ) -> List[Document]:
        """Load Multiple documents from a URL

        Args:
            urls (List[str]): The list of URLs.

        Returns:
            -> List[Document]: A list of Langchain Documents.
        """
        documents = []
        cls.tokenizer=kwargs.pop('tokenizer', None),
        cls.text_splitter = text_splitter
        cls._source_type = source_type
        cls.summarization_model = kwargs.pop(
            'summarization_model',
            "facebook/bart-large-cnn"
        )
        for url in urls:
            documents += cls.load(url, **kwargs)
        return documents
