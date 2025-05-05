from typing import Generator, Union, List, Any, Optional, TypeVar
from collections.abc import Callable
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path, PurePath
import asyncio
from langchain.docstore.document import Document
from navconfig.logging import logging
from navigator.libs.json import JSONContent  # pylint: disable=E0611


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
        self.tokenizer = tokenizer
        self.text_splitter = text_splitter
        self._source_type = source_type
        self._recursive: bool = kwargs.get('recursive', False)
        self.category: str = kwargs.get('category', 'document')
        self.doctype: str = kwargs.get('doctype', 'text')
        if 'path' in kwargs:
            self.path = kwargs['path']
            if isinstance(self.path, str):
                self.path = Path(self.path).resolve()
        # LLM (if required)
        self._llm = kwargs.get('llm', None)
        self.logger = logging.getLogger(
            f"Parrot.Loaders.{self.__class__.__name__}"
        )
        # JSON encoder:
        self._encoder = JSONContent()

    async def __aenter__(self):
        if hasattr(self, "open"):
            await self.open()
        return self

    def supported_extensions(self):
        return self.extensions

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "close"):
            await self.close()
        return True

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

    async def from_url(self, url: Union[str, List[str]], **kwargs) -> List[asyncio.Task]:
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

    async def load(self, source: Optional[Any] = None, **kwargs) -> List[Document]:
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
