from collections.abc import Callable
from pathlib import PurePath
from typing import Any
import re
from langchain_community.document_loaders import ReadTheDocsLoader as RTLoader
from .abstract import AbstractLoader


class ReadTheDocsLoader(AbstractLoader):
    """
    Loading documents from ReadTheDocs.
    """
    _extension: list = []

    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'documentation',
        encoding: str = 'utf-8',
        origin: str = '',
        **kwargs
    ):
        super().__init__(tokenizer, text_splitter, source_type=source_type, **kwargs)
        self.path = path
        self.encoding = encoding
        self.origin = origin
        self._prefix = ''
        match = re.search(r'://([^/]+)', origin)
        if match:
            self._prefix = match.group(1)

    def load(self) -> list:
        documents = []
        self.logger.info(
            f"Loading ReadTheDocs from: {self.path}"
        )
        rt_loader = RTLoader(path=self.path, encoding=self.encoding)
        documents = rt_loader.load()
        for doc in documents:
            src = doc.metadata.get('source')
            suffix = src.replace(f'{self.path}', '').replace(self._prefix, '')
            if suffix.startswith('//'):
                suffix = suffix[1:]
            url = f"{self.origin}{suffix}"
            metadata = {
                "source": url,
                "url": url,
                "index": suffix,
                "filename": src,
                "question": '',
                "answer": '',
                'type': 'documentation',
                "source_type": self._source_type,
                "summary": '',
                "document_meta": {
                    **doc.metadata
                }
            }
            doc.metadata = metadata
        return documents

    def parse(self, source):
        pass
