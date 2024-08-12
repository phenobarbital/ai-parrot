from pathlib import PurePath
from langchain_core.document_loaders.blob_loaders import Blob
from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_community.document_loaders import (
    DirectoryLoader,
    TextLoader,
    JSONLoader
)
from langchain_text_splitters import Language
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter
)
from .abstract import AbstractLoader


class RepositoryLoader(AbstractLoader):
    """Repository (Code Directory) loader.
    """
    exclude_paths: list = [
        ".venv/**",
        ".venv/**/**/*",
        ".git/**",
        "node_modules/**",
        "build/**",
        "dist/**",
        "templates/**",
        "tmp/**"
    ]

    def load(self, path: PurePath, lang: str = 'python', excludes: list = []) -> list:
        """
        Load data from a repository and return it as a Langchain Document.
        """
        if isinstance(path, str):
            path = PurePath(path)
        if excludes:
            self.exclude_paths += excludes
        excludes_path = [
            str(path.joinpath(p).resolve()) for p in self.exclude_paths
        ]
        if lang == 'python':
            parser = LanguageParser(language=Language.PYTHON, parser_threshold=100)
            splitter = RecursiveCharacterTextSplitter.from_language(
                language=Language.PYTHON, chunk_size=1024, chunk_overlap=200
            )
            suffixes = [".py", ".pyx"]
            glob = "**/[!.]*.py?"
        elif lang == 'javascript':
            parser = LanguageParser(language=Language.JS, parser_threshold=100)
            splitter = RecursiveCharacterTextSplitter.from_language(
                language=Language.JS, chunk_size=1024, chunk_overlap=200
            )
            suffixes = [".js", ".jsx", ".json", ".ts", ".tsx"]
        elif lang == 'typescript':
            parser = LanguageParser(language=Language.TS, parser_threshold=100)
            splitter = RecursiveCharacterTextSplitter.from_language(
                language=Language.TS, chunk_size=1024, chunk_overlap=200
            )
            suffixes = [".js", ".jsx", ".json", ".ts", ".tsx"]
        elif lang == 'json':
            loader = DirectoryLoader(
                path,
                glob="**/*.json",
                show_progress=True,
                exclude=excludes_path,
                silent_errors=True,
                recursive=True,
                # loader_cls=TextLoader,
                loader_cls=JSONLoader,
                loader_kwargs={
                    'jq_schema': '.',
                    'text_content': False
                }
            )
            docs = loader.load()
            for doc in docs:
                doc.metadata['url'] = ''
                doc.metadata['source_type'] = self._source_type
                doc.metadata['language'] = lang
            return self.text_splitter.split_documents(docs)
        else:
            raise ValueError(
                f"Language {lang} not supported for Repository"
            )
        loader = GenericLoader.from_filesystem(
            path,
            glob=glob,
            suffixes=suffixes,
            exclude=self.exclude_paths,
            parser=parser,
            show_progress=True
        )
        docs = loader.load()
        for doc in docs:
            doc.metadata['url'] = ''
            doc.metadata['source_type'] = self._source_type
            doc.metadata['language'] = lang
        documents = splitter.split_documents(docs)
        return documents

    def parse(self, source):
        raise NotImplementedError("Parser method is not implemented for PDFLoader.")
