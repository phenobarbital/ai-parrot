
from pathlib import PurePath
from typing import List
import pandas as pd
from parrot.stores.models import Document
from parrot.loaders.abstract import AbstractLoader


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
        if q not in df.columns or a not in df.columns:
            raise ValueError(
                f"Columns {q} and {a} must be present in the DataFrame."
            )

        # Build the list of valid Q&A pairs first so row_count reflects
        # only the pairs actually emitted (skipping NaN/empty cells).
        pairs: List[tuple[str, str]] = []
        for _, row in df.iterrows():
            qs_raw = row[q]
            ans_raw = row[a]
            qs = "" if pd.isna(qs_raw) else str(qs_raw).strip()
            answer = "" if pd.isna(ans_raw) else str(ans_raw).strip()
            if not qs or not answer:
                continue
            pairs.append((qs, answer))

        total = len(pairs)
        docs: List[Document] = []
        # Mirror WebScrapingLoader._docs_from_faqpage: keep Q&A together as
        # a single "Q: …\n\nA: …" block and tag with content_kind="faq" so
        # AbstractLoader._chunk_with_text_splitter passes it through atomic
        # (no splitter, no truncation).
        for idx, (qs, answer) in enumerate(pairs):
            metadata = self.create_metadata(
                path=path,
                doctype=self.doctype,
                source_type=self._source_type,
                type="FAQ",
                content_kind="faq",
                selector_name="faq",
                row_index=idx,
                row_count=total,
                row_data={"question": qs, "answer": answer},
                question=qs,
                answer=answer,
            )
            doc = Document(
                page_content=f"Q: {qs}\n\nA: {answer}",
                metadata=metadata,
            )
            docs.append(doc)
        return docs
