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
    python_requires=">=3.9.20",
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
            "env",
            "etc",
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
            "templates",
            "resources",
            "settings",
            "videos"  # Exclude the 'videos' folder
        ]
    ),
    package_data={"parrot": ["py.typed"]},
    setup_requires=[
        "setuptools_scm>=8.0.4",
        "wheel>=0.44.0",
        'Cython==3.0.11',
    ],
    install_requires=[
        "Cython==3.0.11",
        "langchain>=0.3.4",
        "langchain-community==0.3.3",
        "langchain-experimental==0.3.2",
        "langchainhub==0.1.21",
        "huggingface-hub==0.26.2",
        "faiss-cpu>=1.9.0",
        "jq==1.7.0",
        "rank_bm25==0.2.2",
        "matplotlib==3.9.2",
        "tabulate==0.9.0",
        "selenium>=4.18.1",
        "webdriver_manager>=4.0.1",
        "transitions==0.9.0",
        "sentencepiece==0.2.0",
        "weasyprint==61.2",
        "markdown2==2.4.13",
    ],
    extras_require={
        "agents": [
            "numba==0.59.0",
            "yfinance==0.2.40",
            "youtube_search==2.1.2",
            "wikipedia==1.4.0",
            "mediawikiapi==1.2",
            # "wikibase-rest-api-client==0.2.1",
            # "asknews==0.7.30",
            "pyowm==3.3.0",
            "O365==2.0.35",
            "stackapi==0.3.1",
            "duckduckgo-search==5.3.0",
            "google-search-results==2.4.2",
            "google-api-python-client>=2.86.0",
        ],
        "chatbots": [
            "torch==2.5.1",
            "langchain_huggingface==0.1.2",
            "langchain-text-splitters==0.3.1",
            "fastembed==0.3.4",
            "tiktoken==0.7.0",
            "accelerate==0.34.2",
            "llama-index==0.11.20",
            "llama_cpp_python==0.2.56",
            "bitsandbytes==0.44.1",
            "datasets>=3.0.2",
            "safetensors>=0.4.3",
            "transformers>=4.44.2",
            "sentence-transformers==3.0.1",
            "tokenizers==0.20.1",
            "torchvision==0.20.1",
            "tensorflow==2.18.0",
            "tf-keras==2.18.0",
            "simsimd==4.3.1",
            "opencv-python==4.10.0.84",
        ],
        "anthropic": [
            "langchain-anthropic==0.2.4",
            "anthropic==0.25.2",
        ],
        "openai": [
            "langchain-openai==0.1.21",
            "openai==1.40.3",
            "llama-index-llms-openai==0.1.11",
            "tiktoken==0.7.0"
        ],
        "google": [
            "langchain-google-genai==2.0.1",
            "langchain-google-vertexai==2.0.5",
            "vertexai==1.71.1",
            "pydantic==2.9.2",
            "pydantic-core==2.23.4"
        ],
        "hunggingfaces": [
            "llama-index-llms-huggingface==0.2.7"
        ],
        "groq": [
            "groq==0.11.0",
            "langchain-groq==0.2.0"
        ],
        "qdrant": [
            "qdrant-client==1.12.1",
        ],
        "milvus": [
            "langchain-milvus>=0.1.6",
            "pymilvus==2.4.8",
            "milvus==2.3.5"
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
            # "timm==0.9.16", # image-processor
            # "ultralytics==8.2.4", # image-processor
            # "albumentations-1.4.4",
            # "yolov8-0.0.2"
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
