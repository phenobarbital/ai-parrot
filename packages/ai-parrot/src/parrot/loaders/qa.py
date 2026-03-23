
from pathlib import PurePath
from typing import List
import pandas as pd
from ..stores.models import Document
from .abstract import AbstractLoader


class QAFileLoader(AbstractLoader):
    """
    Question and Answers File based on Excel, coverted to Parrot Documents.
    """
    extensions: List[str] = ['.xlsx']
    chunk_size = 1024
    _source_type = 'QA-File'

    def __init__(
        self,
        *args,
        **kwargs
    ):
        self._columns = kwargs.pop('columns', ['Question', 'Answer'])
        self._question_col = kwargs.pop('question_column', 'Question')
        self._answer_col = kwargs.pop('answer_column', 'Answer')
        self.doctype = kwargs.pop('doctype', 'qa')
        super().__init__(*args, **kwargs)


    async def _load(self, path: PurePath, **kwargs) -> List[Document]:
        df = pd.read_excel(path, header=0, engine='openpyxl')
        # trip spaces on columns names:
        df.columns = df.columns.str.strip()
        q = self._columns[0]
        a = self._columns[1]
        docs = []
        if q not in df.columns or a not in df.columns:
            raise ValueError(
                f"Columns {q} and {a} must be present in the DataFrame."
            )
        for idx, row in df.iterrows():
            # check first if columns q and a are present:
            # Question Document
            qs = row[q]
            answer = row[a]
            document_meta = {
                "question": qs,
                "answer": answer,
            }
            metadata = self.create_metadata(
                path=path,
                doctype=self.doctype,
                source_type=self._source_type,
                doc_metadata=document_meta,
                type="FAQ",
                question=qs,
                answer=answer,
            )
            doc = Document(
                page_content=f"{idx}. Question: {qs}: Answer: {answer}",
                metadata=metadata,
            )
            docs.append(doc)
        return docs
