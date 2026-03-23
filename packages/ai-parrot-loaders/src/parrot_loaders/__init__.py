"""
AI-Parrot Document Loaders package.

LOADER_REGISTRY maps loader names to their dotted import paths.
This enables lazy discovery without importing any loader modules at startup.
"""

LOADER_REGISTRY: dict[str, str] = {
    # --- Text / Document loaders ---
    "TextLoader": "parrot_loaders.txt.TextLoader",
    "CSVLoader": "parrot_loaders.csv.CSVLoader",
    "ExcelLoader": "parrot_loaders.excel.ExcelLoader",
    "MSWordLoader": "parrot_loaders.docx.MSWordLoader",
    "HTMLLoader": "parrot_loaders.html.HTMLLoader",
    "MarkdownLoader": "parrot_loaders.markdown.MarkdownLoader",
    "PDFLoader": "parrot_loaders.pdf.PDFLoader",
    "QAFileLoader": "parrot_loaders.qa.QAFileLoader",
    "EpubLoader": "parrot_loaders.epubloader.EpubLoader",
    "PowerPointLoader": "parrot_loaders.ppt.PowerPointLoader",
    "DocumentConverterLoader": "parrot_loaders.doc_converter.DocumentConverterLoader",
    # --- PDF variants ---
    "BasePDF": "parrot_loaders.basepdf.BasePDF",
    "PDFMarkdownLoader": "parrot_loaders.pdfmark.PDFMarkdownLoader",
    "PDFTablesLoader": "parrot_loaders.pdftables.PDFTablesLoader",
    # --- Web ---
    "WebLoader": "parrot_loaders.web.WebLoader",
    # --- Video / Audio ---
    "BaseVideoLoader": "parrot_loaders.basevideo.BaseVideoLoader",
    "VideoLoader": "parrot_loaders.video.VideoLoader",
    "VideoLocalLoader": "parrot_loaders.videolocal.VideoLocalLoader",
    "VideoUnderstandingLoader": "parrot_loaders.videounderstanding.VideoUnderstandingLoader",
    "YoutubeLoader": "parrot_loaders.youtube.YoutubeLoader",
    "VimeoLoader": "parrot_loaders.vimeo.VimeoLoader",
    "AudioLoader": "parrot_loaders.audio.AudioLoader",
    # --- Factory ---
    "get_loader_class": "parrot_loaders.factory.get_loader_class",
    "LOADER_MAPPING": "parrot_loaders.factory.LOADER_MAPPING",
}
