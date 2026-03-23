# AI-Parrot Loaders

**ai-parrot-loaders** provides document loaders for [AI-Parrot](https://pypi.org/project/ai-parrot/) RAG (Retrieval-Augmented Generation) pipelines. Each loader transforms a specific document format into text chunks that can be embedded and searched.

## Installation

```bash
pip install ai-parrot-loaders
```

Install only the extras you need:

```bash
pip install ai-parrot-loaders[pdf]
pip install ai-parrot-loaders[youtube]
pip install ai-parrot-loaders[audio]
pip install ai-parrot-loaders[web]

# Everything
pip install ai-parrot-loaders[all]
```

## Available Extras

| Extra | Description |
|-------|-------------|
| `pdf` | PDF loading with OCR support (PaddleOCR) |
| `youtube` | YouTube transcript and video download |
| `audio` | Audio transcription (WhisperX, pyannote) |
| `web` | HTML/web page loading |
| `ebook` | EPUB e-book loading |
| `video` | Video processing (MoviePy, FFmpeg) |

## Supported Formats

| Loader | Format | Description |
|--------|--------|-------------|
| `TextLoader` | `.txt` | Plain text files |
| `CSVLoader` | `.csv` | CSV files |
| `ExcelLoader` | `.xlsx`, `.xls` | Excel spreadsheets |
| `MSWordLoader` | `.docx` | Microsoft Word documents |
| `HTMLLoader` | `.html` | HTML files |
| `MarkdownLoader` | `.md` | Markdown files |
| `PDFLoader` | `.pdf` | PDF documents |
| `PDFMarkdownLoader` | `.pdf` | PDF to Markdown conversion |
| `PDFTablesLoader` | `.pdf` | PDF table extraction |
| `PowerPointLoader` | `.pptx` | PowerPoint presentations |
| `EpubLoader` | `.epub` | EPUB e-books |
| `WebLoader` | URL | Web pages |
| `YoutubeLoader` | URL | YouTube video transcripts |
| `VimeoLoader` | URL | Vimeo video transcripts |
| `AudioLoader` | `.mp3`, `.wav`, etc. | Audio transcription |
| `VideoLoader` | URL | Video download + transcription |
| `VideoLocalLoader` | `.mp4`, etc. | Local video transcription |
| `DocumentConverterLoader` | multiple | Auto-detect format and convert |

## Quick Start

```python
from parrot_loaders.factory import get_loader_class

# Auto-detect loader by file extension
LoaderClass = get_loader_class("report.pdf")
loader = LoaderClass(source="report.pdf")
documents = await loader.load()

for doc in documents:
    print(doc.page_content[:200])
```

Or use a specific loader directly:

```python
from parrot_loaders.youtube import YoutubeLoader

loader = YoutubeLoader(source="https://www.youtube.com/watch?v=...")
documents = await loader.load()
```

## Requirements

- Python >= 3.11
- [ai-parrot](https://pypi.org/project/ai-parrot/) >= 0.23.18

## License

MIT
