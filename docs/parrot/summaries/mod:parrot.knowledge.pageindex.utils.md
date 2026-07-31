---
type: Wiki Summary
title: parrot.knowledge.pageindex.utils
id: mod:parrot.knowledge.pageindex.utils
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pure utility functions for PageIndex — no LLM dependency.
relates_to:
- concept: class:parrot.knowledge.pageindex.utils.ConfigLoader
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.add_node_text
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.add_node_text_with_labels
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.add_page_offset_to_toc_json
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.add_preface_if_needed
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.calculate_page_offset
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.clean_structure_post
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.convert_page_to_int
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.convert_physical_index_to_int
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.count_tokens
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.create_clean_structure_for_description
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.extract_json
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.extract_matching_page_pairs
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.find_node_by_id
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.format_structure
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_first_start_page_from_text
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_json_content
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_last_start_page_from_text
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_leaf_nodes
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_nodes
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_number_of_pages
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_page_tokens
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_pdf_name
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_pdf_title
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_text_of_pages
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_text_of_pdf_pages
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.get_text_of_pdf_pages_with_labels
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.is_leaf_node
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.list_to_tree
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.page_list_to_group_text
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.post_processing
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.print_toc
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.remove_fields
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.remove_first_physical_index_section
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.remove_page_number
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.remove_structure_text
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.reorder_dict
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.sanitize_filename
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.structure_to_list
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.validate_and_truncate_physical_indices
  rel: defines
- concept: func:parrot.knowledge.pageindex.utils.write_node_id
  rel: defines
---

# `parrot.knowledge.pageindex.utils`

Pure utility functions for PageIndex — no LLM dependency.

## Classes

- **`ConfigLoader`** — Load PageIndex configuration from YAML with user overrides.

## Functions

- `def count_tokens(text: str, model: str='gpt-4o') -> int` — Count tokens using tiktoken (approximation for non-OpenAI models).
- `def get_json_content(response: str) -> str` — Strip ```json fences from a string.
- `def extract_json(content: str) -> Any` — Extract JSON from LLM response text.
- `def get_page_tokens(pdf_path: str | BytesIO, model: str='gpt-4o', pdf_parser: str='PyMuPDF') -> list[tuple[str, int]]` — Extract page text and token counts from a PDF.
- `def get_pdf_name(pdf_path: str | BytesIO) -> str` — Extract a human-readable name from a PDF path or stream.
- `def get_pdf_title(pdf_path: str) -> str` — Get the title from PDF metadata.
- `def get_text_of_pages(pdf_path: str, start_page: int, end_page: int, tag: bool=True) -> str` — Get text from specific pages of a PDF.
- `def get_text_of_pdf_pages(pdf_pages: list[tuple[str, int]], start_page: int, end_page: int) -> str` — Get concatenated text from a page list (1-indexed).
- `def get_text_of_pdf_pages_with_labels(pdf_pages: list[tuple[str, int]], start_page: int, end_page: int) -> str` — Get concatenated text with physical_index tags.
- `def get_number_of_pages(pdf_path: str) -> int` — Get the number of pages in a PDF.
- `def sanitize_filename(filename: str, replacement: str='-') -> str` — Replace filesystem-unsafe characters.
- `def write_node_id(data: Any, node_id: int=0) -> int` — Assign sequential node_id values to a tree structure.
- `def get_nodes(structure: Any) -> list[dict]` — Flatten a tree into a list of nodes (without children).
- `def structure_to_list(structure: Any) -> list[dict]` — Flatten a tree into a list preserving parent nodes.
- `def get_leaf_nodes(structure: Any) -> list[dict]` — Get all leaf nodes (nodes without children).
- `def is_leaf_node(data: Any, node_id: str) -> bool` — Check if a node with given node_id is a leaf.
- `def find_node_by_id(data: Any, node_id: str) -> Optional[dict]` — Find a node by its node_id in the tree.
- `def list_to_tree(data: list[dict]) -> list[dict]` — Convert a flat TOC list into a hierarchical tree.
- `def add_preface_if_needed(data: list[dict]) -> list[dict]` — Add a preface node if the document starts after page 1.
- `def post_processing(structure: list[dict], end_physical_index: int) -> list[dict]` — Convert flat TOC list to tree with start/end indices.
- `def remove_page_number(data: Any) -> Any` — Remove page_number field from all nodes.
- `def clean_structure_post(data: Any) -> Any` — Remove page_number, start_index, end_index from structure.
- `def remove_fields(data: Any, fields: list[str] | None=None) -> Any` — Remove specified fields from a nested structure.
- `def remove_structure_text(data: Any) -> Any` — Remove 'text' field from all nodes in the tree.
- `def add_node_text(node: Any, pdf_pages: list[tuple[str, int]]) -> None` — Add page text to tree nodes based on start/end indices.
- `def add_node_text_with_labels(node: Any, pdf_pages: list[tuple[str, int]]) -> None` — Add page text with physical_index tags to tree nodes.
- `def convert_physical_index_to_int(data: Any) -> Any` — Convert '<physical_index_X>' strings to integers.
- `def convert_page_to_int(data: list[dict]) -> list[dict]` — Convert page string values to integers.
- `def validate_and_truncate_physical_indices(toc_with_page_number: list[dict], page_list_length: int, start_index: int=1) -> list[dict]` — Remove physical indices exceeding actual document length.
- `def page_list_to_group_text(page_contents: list[str], token_lengths: list[int], max_tokens: int=20000, overlap_page: int=1) -> list[str]` — Split page contents into groups respecting token limits.
- `def extract_matching_page_pairs(toc_page: list[dict], toc_physical_index: list[dict], start_page_index: int) -> list[dict]` — Find matching title pairs between TOC pages and physical indices.
- `def calculate_page_offset(pairs: list[dict]) -> Optional[int]` — Calculate the most common difference between physical and page indices.
- `def add_page_offset_to_toc_json(data: list[dict], offset: int) -> list[dict]` — Apply page offset to convert page numbers to physical indices.
- `def reorder_dict(data: dict, key_order: list[str]) -> dict` — Reorder dictionary keys.
- `def format_structure(structure: Any, order: Optional[list[str]]=None) -> Any` — Recursively format tree nodes with ordered keys.
- `def create_clean_structure_for_description(structure: Any) -> Any` — Create a clean structure without text for description generation.
- `def print_toc(tree: list[dict], indent: int=0) -> None` — Print a tree structure as indented text.
- `def get_first_start_page_from_text(text: str) -> int` — Extract first start_index page number from tagged text.
- `def get_last_start_page_from_text(text: str) -> int` — Extract last start_index page number from tagged text.
- `def remove_first_physical_index_section(text: str) -> str` — Remove first physical_index tagged section from text.
