import os
import glob
from pathlib import PurePath
from langchain_community.document_loaders import (
    DirectoryLoader
)


def load_directory(
    path: PurePath,
    text_splitter,
    source_type,
    file_pattern: str = "**/*.txt"
):
    """
    Load all Text documents from a directory.

    Args:
        path (str): The path to the directory.
        text_splitter (TextSplitter): A text splitter object.
        source_type (str): The type of source.

    Returns:
        list: A list of documents.
    """
    documents = []
    loader = DirectoryLoader(
        path=str(path),
        glob=file_pattern,
        recursive=True,
        show_progress=True,
        use_multithreading=True
    )
    documents = loader.load()
    for doc in documents:
        doc.metadata['source_type'] = source_type
    return text_splitter.split_documents(documents)
