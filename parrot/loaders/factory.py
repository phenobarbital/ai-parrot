####
# Copyright 2023 Jesus Lara.
# Licensed under the Apache License, Version 2.0 (the "License");
#
# Loaders.
# Open, extract and load data from different sources.
#####
import importlib



# Map extensions to (module_name, class_name)
# module_name is relative to parrot.loaders
LOADER_MAPPING = {
    '.pdf': ('pdf', 'PDFLoader'),
    '.txt': ('txt', 'TextLoader'),
    '.docx': ('docx', 'MSWordLoader'),
    '.qa': ('qa', 'QAFileLoader'),
    '.xlsx': ('excel', 'ExcelLoader'),
    '.xlsm': ('excel', 'ExcelLoader'),
    '.xls': ('excel', 'ExcelLoader'),
    '.html': ('html', 'HTMLLoader'),
    '.pdfmd': ('pdfmark', 'PDFMarkdownLoader'),
    '.pdftables': ('pdftables', 'PDFTablesLoader'),
    '.csv': ('csv', 'CSVLoader'),
    '.youtube': ('youtube', 'YoutubeLoader'),
    '.web': ('web', 'WebLoader'),
    '.ppt': ('ppt', 'PowerPointLoader'),
    '.pptx': ('ppt', 'PowerPointLoader'),
    '.md': ('markdown', 'MarkdownLoader'),
    '.json': ('markdown', 'MarkdownLoader'),
    '.xml': ('markdown', 'MarkdownLoader'),
    '.epub': ('epubloader', 'EpubLoader'),
    '.mp3': ('audio', 'AudioLoader'),
    '.wav': ('audio', 'AudioLoader'),
    '.avi': ('videounderstanding', 'VideoUnderstandingLoader'),
    '.mp4': ('videounderstanding', 'VideoUnderstandingLoader'),
    '.webm': ('videounderstanding', 'VideoUnderstandingLoader'),
    '.mov': ('videounderstanding', 'VideoUnderstandingLoader'),
    '.mkv': ('videounderstanding', 'VideoUnderstandingLoader'),
}

def get_loader_class(extension: str):
    """
    Get the loader class for the given extension.
    Lazy loads the module to avoid eager dependency loading.
    """
    if extension not in LOADER_MAPPING:
        from .markdown import MarkdownLoader
        return MarkdownLoader
        
    module_name, class_name = LOADER_MAPPING[extension]
    try:
        # Import the module
        if module_name.startswith('.'):
            module = importlib.import_module(module_name, package='parrot.loaders')
        else:
            module = importlib.import_module(f'.{module_name}', package='parrot.loaders')
            
        # Get the class
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        # Fallback to MarkdownLoader
        print(f"Error loading loader for {extension}: {e}")
        from .markdown import MarkdownLoader
        return MarkdownLoader

# For backward compatibility if needed, but better to use get_loader_class
# AVAILABLE_LOADERS = ... # This would trigger imports if we defined it fully here.
# So we remove AVAILABLE_LOADERS and fix consumers.
