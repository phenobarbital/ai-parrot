####
# Copyright 2023 Jesus Lara.
# Licensed under the Apache License, Version 2.0 (the "License");
#
# Loaders.
# Open, extract and load data from different sources.
#####
from langchain.docstore.document import Document
from .abstract import AbstractLoader
from .txt import TextLoader
from .docx import MSWordLoader
from .qa import QAFileLoader
from .html import HTMLLoader
from .pdfmark import PDFMarkdownLoader
from .pdftables import PDFTables
from .pdfblock import PDFBlock
from .csv import CSVLoader
