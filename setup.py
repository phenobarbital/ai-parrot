#!/usr/bin/env python
"""Navigator AI Parrot.

    Chatbot services for Navigator, based on Langchain.
See:
https://github.com/phenobarbital/ai-parrot
"""
import ast
from os import path

from Cython.Build import cythonize
from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext

def get_path(filename):
    return path.join(path.dirname(path.abspath(__file__)), filename)


def readme():
    with open(get_path('README.md'), encoding='utf-8') as rd:
        return rd.read()


version = get_path('parrot/version.py')
with open(version, 'r', encoding='utf-8') as meta:
    # exec(meta.read())
    t = compile(meta.read(), version, 'exec', ast.PyCF_ONLY_AST)
    for node in (n for n in t.body if isinstance(n, ast.Assign)):
        if len(node.targets) == 1:
            name = node.targets[0]
            if isinstance(name, ast.Name) and \
                    name.id in {
                        '__version__',
                        '__title__',
                        '__description__',
                        '__author__',
                        '__license__', '__author_email__'}:
                v = node.value
                if name.id == '__version__':
                    __version__ = v.s
                if name.id == '__title__':
                    __title__ = v.s
                if name.id == '__description__':
                    __description__ = v.s
                if name.id == '__license__':
                    __license__ = v.s
                if name.id == '__author__':
                    __author__ = v.s
                if name.id == '__author_email__':
                    __author_email__ = v.s

COMPILE_ARGS = ["-O2"]

extensions = [
    Extension(
        name='parrot.exceptions',
        sources=['parrot/exceptions.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c"
    ),
    Extension(
        name='parrot.utils.types',
        sources=['parrot/utils/types.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c++"
    ),
    Extension(
        name='parrot.utils.parsers.toml',
        sources=['parrot/utils/parsers/toml.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c"
    ),
]

# Custom build_ext command to ensure cythonization during the build step
class BuildExtensions(build_ext):
    """Custom build_ext command to ensure cythonization during the build step."""
    def build_extensions(self):
        try:
            from Cython.Build import cythonize  # pylint: disable=import-outside-toplevel
            self.extensions = cythonize(self.extensions)
        except ImportError:
            print(
                "Cython not found. Extensions will be compiled without cythonization!"
            )
        super().build_extensions()

setup(
    name=__title__,
    version=__version__,
    author='Jesus Lara',
    author_email='jesuslara@phenobarbital.info',
    url='https://github.com/phenobarbital/ai-parrot',
    description=__description__,
    long_description=readme(),
    long_description_content_type='text/markdown',
    license=__license__,
    python_requires=">=3.10.12",
    keywords=['asyncio', 'asyncpg', 'aioredis', 'aiomcache', 'langchain', 'chatbot', 'agents'],
    platforms=['POSIX'],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Operating System :: POSIX :: Linux",
        "Environment :: Web Environment",
        "License :: OSI Approved :: MIT License",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3 :: Only",
        "Framework :: AsyncIO",
    ],
    packages=find_packages(
        exclude=[
            "bin",
            "contrib",
            "docs",
            "documents",
            "tests",
            "examples",
            "libraries",
            "db",
            "cache",
            ".jupyter",
            "locale",
            "lab",
            "notebooks",
            "resources",
            "static",
            "templates"
        ]
    ),
    package_data={"parrot": ["py.typed"]},
    setup_requires=[
        "setuptools_scm>=8.0.4",
        "wheel>=0.42.0",
        "Cython==3.0.9",
    ],
    install_requires=[
        "Cython==3.0.9",
        "pymupdf==1.24.4",
        "pymupdf4llm==0.0.1",
        "pdf4llm==0.0.6",
        "PyPDF2==3.0.1",
        "pdfminer.six==20231228",
        "pdfplumber==0.11.0",
        "bitsandbytes==0.43.0",
        "Cartopy==0.22.0",
        "chromadb==0.4.24",
        "contourpy==1.2.0",
        "datasets==2.18.0",
        "faiss-cpu==1.8.0",
        "fastavro==1.9.4",
        "GitPython==3.1.42",
        "gunicorn==21.2.0",
        "jq==1.7.0",
        "rank_bm25==0.2.2",
        "matplotlib==3.8.3",
        "numba==0.59.0",
        "opentelemetry-sdk==1.24.0",
        "rapidocr-onnxruntime==1.3.15",
        "pytesseract==0.3.10",
        "python-docx==1.1.0",
        "python-pptx==0.6.23",
        "docx2txt==0.8",
        "pytube==15.0.0",
        "pydub==0.25.1",
        "markdownify==0.12.1",
        "librosa==0.10.1",
        "yt_dlp==2024.4.9",
        "moviepy==1.0.3",
        "safetensors==0.4.2",
        "sentence-transformers==2.6.1",
        "tabulate==0.9.0",
        "tiktoken==0.7.0",
        "tokenizers==0.19.1",
        "unstructured==0.14.3",
        "unstructured-client==0.18.0",
        "uvloop==0.19.0",
        "XlsxWriter==3.2.0",
        "youtube-transcript-api==0.6.2",
        "selenium==4.18.1",
        "webdriver_manager==4.0.1",
        "transitions==0.9.0",
        "sentencepiece==0.2.0",
        "duckduckgo-search==5.3.0",
        "google-search-results==2.4.2",
        "google-api-python-client>=2.86.0",
        "gdown==5.1.0",
        "weasyprint==61.2",
        "markdown2==2.4.13",
        "xformers==0.0.25.post1",
        "fastembed==0.3.4",
        "mammoth==1.7.1",
        "accelerate==0.29.3",
        "langchain>=0.2.6",
        "langchain-community>=0.2.6",
        "langchain-core==0.2.32",
        "langchain-experimental==0.0.62",
        "langchainhub==0.1.15",
        "langchain-text-splitters==0.2.2",
        "huggingface-hub==0.23.5",
        "llama-index==0.10.20",
        "llama_cpp_python==0.2.56",
        "asyncdb[all]>=2.7.10",
        "querysource>=3.10.1",
        "yfinance==0.2.40",
        "youtube_search==2.1.2",
        "wikipedia==1.4.0",
        "mediawikiapi==1.2",
        "wikibase-rest-api-client==0.2.0",
        "asknews==0.7.30",
        "pyowm==3.3.0",
        "O365==2.0.35",
        "langchain-huggingface==0.0.3",
        "stackapi==0.3.1"
    ],
    extras_require={
        "anthropic": [
            "langchain-anthropic==0.1.11",
            "anthropic==0.25.2",
        ],
        "openai": [
            "langchain-openai==0.1.21",
            "openai==1.40.3",
            "llama-index-llms-openai==0.1.11",
            "tiktoken==0.7.0"
        ],
        "google": [
            "langchain-google-vertexai==1.0.4",
            "langchain-google-genai==1.0.4",
            "google-generativeai==0.5.4",
            "vertexai==1.49.0",
            "google-cloud-aiplatform==1.49.0",
            "grpc-google-iam-v1==0.13.0",
        ],
        "hunggingfaces": [
            "llama-index-llms-huggingface==0.2.7"
        ],
        "groq": [
            "groq==0.6.0",
            "langchain-groq==0.1.4"
        ],
        "qdrant": [
            "qdrant-client==1.8.0",
        ],
        "milvus": [
            "langchain-milvus==0.1.1",
            "milvus==2.3.5",
            "pymilvus==2.4.4",
        ],
        "crew": [
            "colbert-ai==0.2.19",
            "vanna==0.3.4", # Vanna:
            "crewai[tools]==0.28.8"
        ],
        "analytics": [
            "annoy==1.17.3",
            "gradio_tools==0.0.9",
            "gradio-client==0.2.9",
            "streamlit==1.37.1",
            "simsimd==4.3.1",
            "opencv-python==4.10.0.84"
            # "timm==0.9.16", # image-processor
            # "ultralytics==8.2.4", # image-processor
            # "albumentations-1.4.4",
            # "yolov8-0.0.2"
        ],
        "all": [
            # Install all LLM Models
            "langchain-milvus==0.1.1",
            "milvus==2.3.5",
            "pymilvus==2.4.4",
            # GroQ
            "groq==0.6.0",
            "langchain-groq==0.1.4",
            # HF
            "llama-index-llms-huggingface==0.2.7",
            # Google
            "langchain-google-vertexai==1.0.8",
            "langchain-google-genai==1.0.8",
            "google-generativeai==0.7.2",
            "vertexai==1.60.0",
            "google-cloud-aiplatform>=1.60.0",
            "grpc-google-iam-v1==0.13.0",
            # OpenAI
            "langchain-openai==0.1.21",
            "openai==1.40.8",
            "llama-index-llms-openai==0.1.11",
            # Antropic
            "langchain-anthropic==0.1.23",
            "anthropic==0.34.0",
        ]
    },
    tests_require=[
        'pytest>=7.2.2',
        'pytest-asyncio==0.21.1',
        'pytest-xdist==3.3.1',
        'pytest-assume==2.4.3'
    ],
    test_suite='tests',
    ext_modules=cythonize(extensions),
    # cmdclass={"build_ext": BuildExtensions},
    project_urls={  # Optional
        'Source': 'https://github.com/phenobarbital/ai-parrot',
        'Tracker': 'https://github.com/phenobarbital/ai-parrot/issues',
        'Documentation': 'https://github.com/phenobarbital/ai-parrot/',
        "Funding": "https://paypal.me/phenobarbital",
        "Say Thanks!": "https://saythanks.io/to/phenobarbital",
    },
)
