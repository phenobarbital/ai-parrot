from pathlib import PurePath
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_community.document_loaders import GithubFileLoader
from langchain_text_splitters import Language
from langchain.text_splitter import (
    RecursiveCharacterTextSplitter
)
from navconfig import config
from .abstract import AbstractLoader

class GithubLoader(AbstractLoader):
    """
    Load Code from a Github Repository.
    """
    def __init__(
        self,
        repository_url: str,
        lang: str = 'python',
        source_type: str = 'code',
        branch: str = 'main',
        **kwargs
    ):
        super().__init__(source_type=source_type, **kwargs)
        self._url = repository_url
        self.branch = branch
        self.github_token = kwargs.get('github_token', config.get('GITHUB_TOKEN'))
        self.lang = lang
        if lang == 'python':
            self.parser = LanguageParser(language=Language.PYTHON, parser_threshold=500)
            self.splitter = RecursiveCharacterTextSplitter.from_language(
                language=Language.PYTHON, chunk_size=1024, chunk_overlap=200
            )
            self.suffixes = [".py", ".pyx"]
        elif lang == 'javascript':
            self.parser = LanguageParser(language=Language.JS, parser_threshold=500)
            self.splitter = RecursiveCharacterTextSplitter.from_language(
                language=Language.JS, chunk_size=1024, chunk_overlap=200
            )
            self.suffixes = [".js", ".jsx", ".json", ".ts", ".tsx"]
        elif lang == 'typescript':
            self.parser = LanguageParser(language=Language.TS, parser_threshold=500)
            self.splitter = RecursiveCharacterTextSplitter.from_language(
                language=Language.TS, chunk_size=1024, chunk_overlap=200
            )
            self.suffixes = [".js", ".jsx", ".json", ".ts", ".tsx"]
        else:
            raise ValueError(
                f"Language {lang} not supported for Repository"
            )

    def load(self) -> list:
        self.logger.info(f'Loading Github Repository > {self._url}:<{self.branch}>')
        loader = GithubFileLoader(
            repo=self._url,
            github_api_url='https://api.github.com',
            access_token=self.github_token,
            branch=self.branch,
        )
        docs = loader.load()
        for doc in docs:
            doc.metadata['source_type'] = self._source_type
        return self.split_documents(docs)

    def parse(self, source):
        raise NotImplementedError("Parser method is not implemented for PDFLoader.")
