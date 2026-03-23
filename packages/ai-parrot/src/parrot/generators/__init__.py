"""
Web App Generator Implementation for AI-Parrot
========================================================

This module provides generators for creating full web applications with LLMs.

Directory structure to create:
parrot/
├── generators/
│   ├── __init__.py          # This file
│   ├── base.py              # Base generator class
│   ├── streamlit.py         # Streamlit generator
│   ├── react.py             # React generator
│   └── html.py              # HTML/JS generator
"""
from .base import WebAppGenerator
from .streamlit import StreamlitGenerator, StreamlitApp
from .react import ReactGenerator, ReactApp
from .html import HTMLGenerator, HTMLApp

__all__ = [
    'WebAppGenerator',
    'StreamlitGenerator',
    'StreamlitApp',
    'ReactGenerator',
    'ReactApp',
    'HTMLGenerator',
    'HTMLApp'
]
