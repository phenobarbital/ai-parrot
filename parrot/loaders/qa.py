
from pathlib import Path, PurePath
from typing import Any
from collections.abc import Callable
import pandas as pd
from langchain.docstore.document import Document
from .abstract import AbstractLoader


class QAFileLoader(AbstractLoader):
    """
    Question and Answers File based on Excel.
    """
    _extension = ['.xlsx']
    chunk_size = 768

    def __init__(
        self,
        path: PurePath,
        tokenizer: Callable[..., Any] = None,
        text_splitter: Callable[..., Any] = None,
        source_type: str = 'QA',
        columns: list = ['Question', 'Answer'],
        **kwargs
    ):
        super().__init__(tokenizer, text_splitter, source_type, **kwargs)
        self.path = path
        self._columns = columns
        if isinstance(path, str):
            self.path = Path(path).resolve()
        if self.path.is_dir():
            raise ValueError(
                f"Currently only accepting single Files."
            )

    def _load_document(self, path: PurePath) -> list:
        if path.exists():
            print('Load QA Excel File: ', path)
            df = pd.read_excel(path)
            q = self._columns[0]
            a = self._columns[1]
            docs = []
            for idx, row in df.iterrows():
                # Question Document
                doc = Document(
                    page_content=f"**Question:** {row[q]}: **Answer:** {row[a]}",
                    metadata={
                        "url": '',
                        "index": f"{path.name} #{idx}",
                        "source": f"{path.name} Row.#{idx}",
                        "filename": f"{path.name}",
                        "question": row[q],
                        "answer": row[a],
                        "page_number": idx,
                        "source_type": self._source_type,
                        "type": "QA",
                        "summary": f"Question: {row[q]}?: **{row[a]}**",
                        "document_meta": {
                            "question": row[q],
                            "answer": row[a],
                        }
                    }
                )
                docs.append(doc)
            return docs
        return []

    def load(self, **kwargs) -> list:
        """
        Load Chapters from a PDF file.

        Returns:
            list: A list of Langchain Documents.
        """
        if self.path.is_file():
            documents = self._load_document(path=self.path, **kwargs)
            # after all documents are retrieved, procesed and stored
            return self.split_documents(documents)

    def parse(self, source):
        pass
