####
# Copyright 2023 Jesus Lara.
# Licensed under the Apache License, Version 2.0 (the "License");
#
# Loaders.
# Open, extract and load data from different sources.
#####
from ..stores.models import Document
from .abstract import AbstractLoader
from .pdf import PDFLoader
from .txt import TextLoader
from .docx import MSWordLoader
from .qa import QAFileLoader
from .html import HTMLLoader
from .pdfmark import PDFMarkdownLoader
from .pdftables import PDFTablesLoader
from .csv import CSVLoader
from .youtube import YoutubeLoader
from .web import WebLoader
from .ppt import PowerPointLoader
from .markdown import MarkdownLoader
from .epubloader import EpubLoader
from .excel import ExcelLoader
# from .video import VideoLoader
from .videolocal import VideoLocalLoader
from .videounderstanding import VideoUnderstandingLoader
# from .vimeo import VimeoLoader
from .audio import AudioLoader

AVAILABLE_LOADERS = {
    '.pdf': PDFLoader,
    '.txt': TextLoader,
    '.docx': MSWordLoader,
    '.qa': QAFileLoader,
    '.xlsx': ExcelLoader,
    '.xlsm': ExcelLoader,
    '.xls': ExcelLoader,
    '.html': HTMLLoader,
    '.pdfmd': PDFMarkdownLoader,
    '.pdftables': PDFTablesLoader,
    '.csv': CSVLoader,
    '.youtube': YoutubeLoader,
    '.web': WebLoader,
    '.ppt': PowerPointLoader,
    '.pptx': PowerPointLoader,
    '.md': MarkdownLoader,
    '.json': MarkdownLoader,
    '.xml': MarkdownLoader,
    '.epub': EpubLoader,
    '.mp3': AudioLoader,
    '.wav': AudioLoader,
    '.avi': VideoUnderstandingLoader,
    '.mp4': VideoUnderstandingLoader,
    '.webm': VideoUnderstandingLoader,
    '.mov': VideoUnderstandingLoader,
    '.mkv': VideoUnderstandingLoader,
}
