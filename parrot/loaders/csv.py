from typing import List, Union
from pathlib import PurePath
from langchain_community.document_loaders.csv_loader import CSVLoader as CSVL
from langchain.docstore.document import Document
from .abstract import AbstractLoader


class CSVLoader(AbstractLoader):
    """
    Loader for CSV files.
    """
    extensions: List[str] = ['.csv']
    csv_args: dict = {
        "delimiter": ",",
        "quotechar": '"',
        "escapechar": "\\",
        "skipinitialspace": False,
        "lineterminator": "\n",
        "quoting": 0,
        "skiprows": 0,
        "encoding": None
    }

    async def _load(self, path: Union[str, PurePath, List[PurePath]], **kwargs) -> List[Document]:
        """
        Load data from a CSV file.

        Args:
            source (str): The path to the CSV file.

        Returns:
            list: A list of Langchain Documents.
        """
        self.logger.info(f"Loading CSV file: {path}")
        loader = CSVL(
            file_path=path,
            csv_args=self.csv_args,
            autodetect_encoding=True
        )
        documents = loader.load()
        # split documents using text-splitter
        docs = self.text_splitter.split_documents(documents)
        if not docs:
            self.logger.warning(f"No documents found in CSV file: {path}")
            return []
        return docs
