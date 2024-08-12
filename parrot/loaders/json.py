from collections.abc import Callable
from pathlib import PurePath
from langchain_community.document_loaders import JSONLoader as JSLoader
from .abstract import AbstractLoader


class JSONLoader(AbstractLoader):
    """
    Loader for JSON files.
    """
    _extension = ['.json']
    extract_metadata: Callable = None

    def extract_metadata(self, record: dict, metadata: dict) -> dict:
        meta = {
            "source_type": self._source_type,
            "priority": self._priority,
        }
        return meta

    def load(self, path: PurePath) -> list:
        """
        Load data from a JSON file.

        Args:
            source (str): The path to the JSON file.

        Returns:
            list: A list of Langchain Documents.
        """
        if self._check_path(path):
            self.logger.info(f"Loading JSON file: {path}")
            # Create metadata for each chunk
            meta = {
                "filename": str(path),
            }
            args = {
                "metadata_func": self.extract_metadata,
            }
            loader = JSLoader(
                file_path=path,
                jq_schema=".",
                text_content=False,
                **args
            )
            documents = loader.load()
            for doc in documents:
                doc.metadata.update(meta)
            # Split the documents into chunks
            return self.split_documents(documents)
        else:
            return []
