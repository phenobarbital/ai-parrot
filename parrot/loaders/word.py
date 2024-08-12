from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Union
import mammoth
import docx
from markdownify import markdownify as md
from langchain_community.document_loaders.word_document import (
    UnstructuredWordDocumentLoader
)
from langchain.text_splitter import MarkdownTextSplitter
from langchain.docstore.document import Document
from .abstract import AbstractLoader


class MSWordLoader(AbstractLoader):
    """
    Loader for Microsoft Word files.
    """
    _extension: list = ['.docx', '.doc']

    def __init__(
        self,
        path: PurePath,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'document',
        **kwargs
    ):
        self.path = path
        if isinstance(path, str):
            path = Path(path)
        self._use_mammoth: bool = kwargs.pop('use_mammoth', True)
        self._md_splitter = MarkdownTextSplitter(chunk_size = 1024, chunk_overlap=10)
        super().__init__(
            tokenizer=tokenizer,
            text_splitter=text_splitter,
            source_type=source_type,
            **kwargs
        )

    def _load_document(self, path: PurePath) -> list:
        if self._check_path(path):
            docs = []
            self.logger.info(f"Loading Word file: {path}")
            if self._use_mammoth:
                with open(path, "rb") as docx_file:
                    doc = docx.Document(str(path))
                    prop = doc.core_properties
                    result = mammoth.convert_to_html(docx_file)
                    # result = mammoth.extract_raw_text(docx_file)
                    html = result.value # The generated HTML
                    md_text = md(html) # The generated Markdown
                    try:
                        summary = self.get_summary_from_text(md_text)
                    except ValueError:
                        summary = ''
                    metadata = {
                        "url": '',
                        "source": path.name,
                        "filename": path.name,
                        "index": str(path.name),
                        "type": 'document',
                        "question": '',
                        "answer": '',
                        "source_type": self._source_type,
                        "data": {},
                        "summary": summary,
                        "document_meta": {
                            "author": prop.author,
                            "version": prop.version,
                            "title": prop.title,
                            "created": prop.created.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_modified": prop.modified.strftime("%Y-%m-%d %H:%M:%S")
                        }
                    }
                    for chunk in self._md_splitter.split_text(md_text):
                        _idx = {
                            **metadata
                        }
                        docs.append(
                            Document(
                                page_content=chunk,
                                metadata=_idx
                            )
                        )
                return docs
            else:
                word_loader = UnstructuredWordDocumentLoader(
                    file_path=str(path)
                )
                docs = word_loader.load()
                for doc in docs:
                    # Fix This
                    doc.metadata['source_type'] = self._source_type
        return []

    def load(self) -> list:
        """
        Load data from a DOCX file.

        Args:
            source (str): The path to the DOCX file.

        Returns:
            list: A list of Langchain Documents.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"DOCX file/directory not found: {self.path}")
        if self.path.is_dir():
            documents = []
            # iterate over the files in the directory
            for ext in self._extension:
                for item in self.path.glob(f'*{ext}'):
                    documents.extend(self._load_document(item))
        elif self.path.is_file():
            documents = self._load_document(self.path)
        else:
            raise ValueError(
                f"DOCX Loader: Invalid path: {self.path}"
            )
        # return documents
        return self.split_documents(documents)

    def parse(self, source):
        pass
