from pathlib import PurePath
from langchain_community.document_loaders.csv_loader import CSVLoader as CSVL
from .abstract import AbstractLoader


class CSVLoader(AbstractLoader):
    """
    Loader for CSV files.
    """
    _extension = ['.csv']
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

    def load(self, path: PurePath) -> list:
        """
        Load data from a CSV file.

        Args:
            source (str): The path to the CSV file.

        Returns:
            list: A list of Langchain Documents.
        """
        if self._check_path(path):
            self.logger.info(f"Loading CSV file: {path}")
            loader = CSVL(
                file_path=path,
                csv_args=self.csv_args,
                autodetect_encoding=True
            )
            documents = loader.load()
            return self.split_documents(documents)
        else:
            return []
