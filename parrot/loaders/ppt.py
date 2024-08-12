from pathlib import PurePath
from langchain_community.document_loaders import (
    UnstructuredPowerPointLoader
)
from .abstract import AbstractLoader


class PPTXLoader(AbstractLoader):
    """
    Loader for PPTX files.
    """
    _extension: list = ['.pptx']

    def load(self, path: PurePath) -> list:
        if self._check_path(path):
            docs = []
            self.logger.info(f"Loading PPTX file: {path}")
            ppt_loader = UnstructuredPowerPointLoader(
                file_path=str(path)
            )
            docs += ppt_loader.load()
            for doc in docs:
                doc.metadata['source_type'] = self._source_type
            # Split the documents into chunks
            return self.split_documents(docs)
        else:
            return []

    def parse(self, source):
        pass
