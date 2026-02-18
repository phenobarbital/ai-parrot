"""Pure utility functions for PageIndex — no LLM dependency."""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace as config
from typing import Any, Optional

import tiktoken
import yaml

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None  # type: ignore[assignment]

try:
    import pymupdf
except ImportError:
    pymupdf = None  # type: ignore[assignment]

logger = logging.getLogger("parrot.pageindex")


# --- Token Counting ---

def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens using tiktoken (approximation for non-OpenAI models)."""
    if not text:
        return 0
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


# --- JSON Helpers ---

def get_json_content(response: str) -> str:
    """Strip ```json fences from a string."""
    start_idx = response.find("```json")
    if start_idx != -1:
        start_idx += 7
        response = response[start_idx:]

    end_idx = response.rfind("```")
    if end_idx != -1:
        response = response[:end_idx]

    return response.strip()


def extract_json(content: str) -> Any:
    """Extract JSON from LLM response text."""
    try:
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7
            end_idx = content.rfind("```")
            json_content = content[start_idx:end_idx].strip()
        else:
            json_content = content.strip()

        json_content = json_content.replace("None", "null")
        json_content = json_content.replace("\n", " ").replace("\r", " ")
        json_content = " ".join(json_content.split())
        return json.loads(json_content)
    except json.JSONDecodeError:
        try:
            json_content = json_content.replace(",]", "]").replace(",}", "}")
            return json.loads(json_content)
        except Exception:
            logger.error("Failed to parse JSON even after cleanup")
            return {}
    except Exception as e:
        logger.error("Unexpected error extracting JSON: %s", e)
        return {}


# --- PDF Parsing ---

def get_page_tokens(
    pdf_path: str | BytesIO,
    model: str = "gpt-4o",
    pdf_parser: str = "PyMuPDF",
) -> list[tuple[str, int]]:
    """Extract page text and token counts from a PDF."""
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")

    if pdf_parser == "PyPDF2":
        if PyPDF2 is None:
            raise ImportError("PyPDF2 is required for PDF parsing with PyPDF2 parser")
        pdf_reader = PyPDF2.PdfReader(pdf_path)
        page_list: list[tuple[str, int]] = []
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            token_length = len(enc.encode(page_text))
            page_list.append((page_text, token_length))
        return page_list
    elif pdf_parser == "PyMuPDF":
        if pymupdf is None:
            raise ImportError("pymupdf is required for PDF parsing with PyMuPDF parser")
        if isinstance(pdf_path, BytesIO):
            doc = pymupdf.open(stream=pdf_path, filetype="pdf")
        elif isinstance(pdf_path, str) and os.path.isfile(pdf_path):
            doc = pymupdf.open(pdf_path)
        else:
            raise ValueError(f"Invalid pdf_path: {pdf_path}")
        page_list = []
        for page in doc:
            page_text = page.get_text()
            token_length = len(enc.encode(page_text))
            page_list.append((page_text, token_length))
        return page_list
    else:
        raise ValueError(f"Unsupported PDF parser: {pdf_parser}")


def get_pdf_name(pdf_path: str | BytesIO) -> str:
    """Extract a human-readable name from a PDF path or stream."""
    if isinstance(pdf_path, str):
        return os.path.basename(pdf_path)
    elif isinstance(pdf_path, BytesIO):
        if PyPDF2 is None:
            return "Untitled"
        pdf_reader = PyPDF2.PdfReader(pdf_path)
        meta = pdf_reader.metadata
        title = meta.title if meta and meta.title else "Untitled"
        return sanitize_filename(title)
    return "Untitled"


def get_pdf_title(pdf_path: str) -> str:
    """Get the title from PDF metadata."""
    if PyPDF2 is None:
        return "Untitled"
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    meta = pdf_reader.metadata
    return meta.title if meta and meta.title else "Untitled"


def get_text_of_pages(
    pdf_path: str,
    start_page: int,
    end_page: int,
    tag: bool = True,
) -> str:
    """Get text from specific pages of a PDF."""
    if PyPDF2 is None:
        raise ImportError("PyPDF2 is required")
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    text = ""
    for page_num in range(start_page - 1, end_page):
        page = pdf_reader.pages[page_num]
        page_text = page.extract_text() or ""
        if tag:
            text += f"<start_index_{page_num+1}>\n{page_text}\n<end_index_{page_num+1}>\n"
        else:
            text += page_text
    return text


def get_text_of_pdf_pages(
    pdf_pages: list[tuple[str, int]],
    start_page: int,
    end_page: int,
) -> str:
    """Get concatenated text from a page list (1-indexed)."""
    text = ""
    for page_num in range(start_page - 1, end_page):
        if 0 <= page_num < len(pdf_pages):
            text += pdf_pages[page_num][0]
    return text


def get_text_of_pdf_pages_with_labels(
    pdf_pages: list[tuple[str, int]],
    start_page: int,
    end_page: int,
) -> str:
    """Get concatenated text with physical_index tags."""
    text = ""
    for page_num in range(start_page - 1, end_page):
        if 0 <= page_num < len(pdf_pages):
            text += (
                f"<physical_index_{page_num+1}>\n"
                f"{pdf_pages[page_num][0]}\n"
                f"<physical_index_{page_num+1}>\n"
            )
    return text


def get_number_of_pages(pdf_path: str) -> int:
    """Get the number of pages in a PDF."""
    if PyPDF2 is None:
        raise ImportError("PyPDF2 is required")
    pdf_reader = PyPDF2.PdfReader(pdf_path)
    return len(pdf_reader.pages)


def sanitize_filename(filename: str, replacement: str = "-") -> str:
    """Replace filesystem-unsafe characters."""
    return filename.replace("/", replacement)


# --- Tree Utilities ---

def write_node_id(data: Any, node_id: int = 0) -> int:
    """Assign sequential node_id values to a tree structure."""
    if isinstance(data, dict):
        data["node_id"] = str(node_id).zfill(4)
        node_id += 1
        for key in list(data.keys()):
            if "nodes" in key:
                node_id = write_node_id(data[key], node_id)
    elif isinstance(data, list):
        for item in data:
            node_id = write_node_id(item, node_id)
    return node_id


def get_nodes(structure: Any) -> list[dict]:
    """Flatten a tree into a list of nodes (without children)."""
    if isinstance(structure, dict):
        structure_node = copy.deepcopy(structure)
        structure_node.pop("nodes", None)
        nodes = [structure_node]
        for key in list(structure.keys()):
            if "nodes" in key:
                nodes.extend(get_nodes(structure[key]))
        return nodes
    elif isinstance(structure, list):
        nodes: list[dict] = []
        for item in structure:
            nodes.extend(get_nodes(item))
        return nodes
    return []


def structure_to_list(structure: Any) -> list[dict]:
    """Flatten a tree into a list preserving parent nodes."""
    if isinstance(structure, dict):
        nodes = [structure]
        if "nodes" in structure:
            nodes.extend(structure_to_list(structure["nodes"]))
        return nodes
    elif isinstance(structure, list):
        nodes: list[dict] = []
        for item in structure:
            nodes.extend(structure_to_list(item))
        return nodes
    return []


def get_leaf_nodes(structure: Any) -> list[dict]:
    """Get all leaf nodes (nodes without children)."""
    if isinstance(structure, dict):
        if not structure.get("nodes"):
            structure_node = copy.deepcopy(structure)
            structure_node.pop("nodes", None)
            return [structure_node]
        leaf_nodes: list[dict] = []
        for key in list(structure.keys()):
            if "nodes" in key:
                leaf_nodes.extend(get_leaf_nodes(structure[key]))
        return leaf_nodes
    elif isinstance(structure, list):
        leaf_nodes = []
        for item in structure:
            leaf_nodes.extend(get_leaf_nodes(item))
        return leaf_nodes
    return []


def is_leaf_node(data: Any, node_id: str) -> bool:
    """Check if a node with given node_id is a leaf."""
    def find_node(d: Any, nid: str) -> Optional[dict]:
        if isinstance(d, dict):
            if d.get("node_id") == nid:
                return d
            for key in d.keys():
                if "nodes" in key:
                    result = find_node(d[key], nid)
                    if result:
                        return result
        elif isinstance(d, list):
            for item in d:
                result = find_node(item, nid)
                if result:
                    return result
        return None

    node = find_node(data, node_id)
    if node and not node.get("nodes"):
        return True
    return False


def find_node_by_id(data: Any, node_id: str) -> Optional[dict]:
    """Find a node by its node_id in the tree."""
    if isinstance(data, dict):
        if data.get("node_id") == node_id:
            return data
        for key in data.keys():
            if "nodes" in key:
                result = find_node_by_id(data[key], node_id)
                if result:
                    return result
    elif isinstance(data, list):
        for item in data:
            result = find_node_by_id(item, node_id)
            if result:
                return result
    return None


def list_to_tree(data: list[dict]) -> list[dict]:
    """Convert a flat TOC list into a hierarchical tree."""
    def get_parent_structure(structure: Optional[str]) -> Optional[str]:
        if not structure:
            return None
        parts = str(structure).split(".")
        return ".".join(parts[:-1]) if len(parts) > 1 else None

    nodes: dict[Optional[str], dict] = {}
    root_nodes: list[dict] = []

    for item in data:
        structure = item.get("structure")
        node: dict[str, Any] = {
            "title": item.get("title"),
            "start_index": item.get("start_index"),
            "end_index": item.get("end_index"),
            "nodes": [],
        }

        nodes[structure] = node
        parent_structure = get_parent_structure(structure)

        if parent_structure and parent_structure in nodes:
            nodes[parent_structure]["nodes"].append(node)
        else:
            root_nodes.append(node)

    def clean_node(node: dict) -> dict:
        if not node["nodes"]:
            del node["nodes"]
        else:
            for child in node["nodes"]:
                clean_node(child)
        return node

    return [clean_node(node) for node in root_nodes]


def add_preface_if_needed(data: list[dict]) -> list[dict]:
    """Add a preface node if the document starts after page 1."""
    if not isinstance(data, list) or not data:
        return data
    if data[0].get("physical_index") is not None and data[0]["physical_index"] > 1:
        preface_node = {
            "structure": "0",
            "title": "Preface",
            "physical_index": 1,
        }
        data.insert(0, preface_node)
    return data


# --- Post-Processing ---

def post_processing(structure: list[dict], end_physical_index: int) -> list[dict]:
    """Convert flat TOC list to tree with start/end indices."""
    for i, item in enumerate(structure):
        item["start_index"] = item.get("physical_index")
        if i < len(structure) - 1:
            if structure[i + 1].get("appear_start") == "yes":
                item["end_index"] = structure[i + 1]["physical_index"] - 1
            else:
                item["end_index"] = structure[i + 1]["physical_index"]
        else:
            item["end_index"] = end_physical_index
    tree = list_to_tree(structure)
    if tree:
        return tree
    for node in structure:
        node.pop("appear_start", None)
        node.pop("physical_index", None)
    return structure


def remove_page_number(data: Any) -> Any:
    """Remove page_number field from all nodes."""
    if isinstance(data, dict):
        data.pop("page_number", None)
        for key in list(data.keys()):
            if "nodes" in key:
                remove_page_number(data[key])
    elif isinstance(data, list):
        for item in data:
            remove_page_number(item)
    return data


def clean_structure_post(data: Any) -> Any:
    """Remove page_number, start_index, end_index from structure."""
    if isinstance(data, dict):
        data.pop("page_number", None)
        data.pop("start_index", None)
        data.pop("end_index", None)
        if "nodes" in data:
            clean_structure_post(data["nodes"])
    elif isinstance(data, list):
        for section in data:
            clean_structure_post(section)
    return data


def remove_fields(data: Any, fields: list[str] | None = None) -> Any:
    """Remove specified fields from a nested structure."""
    if fields is None:
        fields = ["text"]
    if isinstance(data, dict):
        return {
            k: remove_fields(v, fields) for k, v in data.items() if k not in fields
        }
    elif isinstance(data, list):
        return [remove_fields(item, fields) for item in data]
    return data


def remove_structure_text(data: Any) -> Any:
    """Remove 'text' field from all nodes in the tree."""
    if isinstance(data, dict):
        data.pop("text", None)
        if "nodes" in data:
            remove_structure_text(data["nodes"])
    elif isinstance(data, list):
        for item in data:
            remove_structure_text(item)
    return data


# --- Node Text & Summaries ---

def add_node_text(node: Any, pdf_pages: list[tuple[str, int]]) -> None:
    """Add page text to tree nodes based on start/end indices."""
    if isinstance(node, dict):
        start_page = node.get("start_index")
        end_page = node.get("end_index")
        if start_page and end_page:
            node["text"] = get_text_of_pdf_pages(pdf_pages, start_page, end_page)
        if "nodes" in node:
            add_node_text(node["nodes"], pdf_pages)
    elif isinstance(node, list):
        for item in node:
            add_node_text(item, pdf_pages)


def add_node_text_with_labels(node: Any, pdf_pages: list[tuple[str, int]]) -> None:
    """Add page text with physical_index tags to tree nodes."""
    if isinstance(node, dict):
        start_page = node.get("start_index")
        end_page = node.get("end_index")
        if start_page and end_page:
            node["text"] = get_text_of_pdf_pages_with_labels(pdf_pages, start_page, end_page)
        if "nodes" in node:
            add_node_text_with_labels(node["nodes"], pdf_pages)
    elif isinstance(node, list):
        for item in node:
            add_node_text_with_labels(item, pdf_pages)


# --- Physical Index Conversion ---

def convert_physical_index_to_int(data: Any) -> Any:
    """Convert '<physical_index_X>' strings to integers."""
    if isinstance(data, list):
        for i in range(len(data)):
            if isinstance(data[i], dict) and "physical_index" in data[i]:
                val = data[i]["physical_index"]
                if isinstance(val, str):
                    if val.startswith("<physical_index_"):
                        data[i]["physical_index"] = int(
                            val.split("_")[-1].rstrip(">").strip()
                        )
                    elif val.startswith("physical_index_"):
                        data[i]["physical_index"] = int(val.split("_")[-1].strip())
    elif isinstance(data, str):
        if data.startswith("<physical_index_"):
            return int(data.split("_")[-1].rstrip(">").strip())
        elif data.startswith("physical_index_"):
            return int(data.split("_")[-1].strip())
        try:
            return int(data)
        except (ValueError, TypeError):
            return None
    return data


def convert_page_to_int(data: list[dict]) -> list[dict]:
    """Convert page string values to integers."""
    for item in data:
        if "page" in item and isinstance(item["page"], str):
            try:
                item["page"] = int(item["page"])
            except ValueError:
                pass
    return data


# --- Validation ---

def validate_and_truncate_physical_indices(
    toc_with_page_number: list[dict],
    page_list_length: int,
    start_index: int = 1,
) -> list[dict]:
    """Remove physical indices exceeding actual document length."""
    if not toc_with_page_number:
        return toc_with_page_number

    max_allowed_page = page_list_length + start_index - 1

    for item in toc_with_page_number:
        if item.get("physical_index") is not None:
            if item["physical_index"] > max_allowed_page:
                logger.info(
                    "Removed physical_index for '%s' (was %d, beyond document)",
                    item.get("title", "Unknown"),
                    item["physical_index"],
                )
                item["physical_index"] = None

    return toc_with_page_number


# --- Page Grouping ---

def page_list_to_group_text(
    page_contents: list[str],
    token_lengths: list[int],
    max_tokens: int = 20000,
    overlap_page: int = 1,
) -> list[str]:
    """Split page contents into groups respecting token limits."""
    num_tokens = sum(token_lengths)

    if num_tokens <= max_tokens:
        return ["".join(page_contents)]

    subsets: list[str] = []
    current_subset: list[str] = []
    current_token_count = 0

    expected_parts_num = math.ceil(num_tokens / max_tokens)
    average_tokens_per_part = math.ceil(
        ((num_tokens / expected_parts_num) + max_tokens) / 2
    )

    for i, (page_content, page_tokens) in enumerate(
        zip(page_contents, token_lengths)
    ):
        if current_token_count + page_tokens > average_tokens_per_part:
            subsets.append("".join(current_subset))
            overlap_start = max(i - overlap_page, 0)
            current_subset = list(page_contents[overlap_start:i])
            current_token_count = sum(token_lengths[overlap_start:i])

        current_subset.append(page_content)
        current_token_count += page_tokens

    if current_subset:
        subsets.append("".join(current_subset))

    return subsets


# --- Matching & Offset ---

def extract_matching_page_pairs(
    toc_page: list[dict],
    toc_physical_index: list[dict],
    start_page_index: int,
) -> list[dict]:
    """Find matching title pairs between TOC pages and physical indices."""
    pairs: list[dict] = []
    for phy_item in toc_physical_index:
        for page_item in toc_page:
            if phy_item.get("title") == page_item.get("title"):
                physical_index = phy_item.get("physical_index")
                if physical_index is not None and int(physical_index) >= start_page_index:
                    pairs.append({
                        "title": phy_item.get("title"),
                        "page": page_item.get("page"),
                        "physical_index": physical_index,
                    })
    return pairs


def calculate_page_offset(pairs: list[dict]) -> Optional[int]:
    """Calculate the most common difference between physical and page indices."""
    differences: list[int] = []
    for pair in pairs:
        try:
            physical_index = pair["physical_index"]
            page_number = pair["page"]
            differences.append(physical_index - page_number)
        except (KeyError, TypeError):
            continue

    if not differences:
        return None

    difference_counts: dict[int, int] = {}
    for diff in differences:
        difference_counts[diff] = difference_counts.get(diff, 0) + 1

    return max(difference_counts.items(), key=lambda x: x[1])[0]


def add_page_offset_to_toc_json(data: list[dict], offset: int) -> list[dict]:
    """Apply page offset to convert page numbers to physical indices."""
    for item in data:
        if item.get("page") is not None and isinstance(item["page"], int):
            item["physical_index"] = item["page"] + offset
            del item["page"]
    return data


# --- Formatting ---

def reorder_dict(data: dict, key_order: list[str]) -> dict:
    """Reorder dictionary keys."""
    if not key_order:
        return data
    return {key: data[key] for key in key_order if key in data}


def format_structure(structure: Any, order: Optional[list[str]] = None) -> Any:
    """Recursively format tree nodes with ordered keys."""
    if not order:
        return structure
    if isinstance(structure, dict):
        if "nodes" in structure:
            structure["nodes"] = format_structure(structure["nodes"], order)
        if not structure.get("nodes"):
            structure.pop("nodes", None)
        structure = reorder_dict(structure, order)
    elif isinstance(structure, list):
        structure = [format_structure(item, order) for item in structure]
    return structure


def create_clean_structure_for_description(structure: Any) -> Any:
    """Create a clean structure without text for description generation."""
    if isinstance(structure, dict):
        clean_node: dict[str, Any] = {}
        for key in ["title", "node_id", "summary", "prefix_summary"]:
            if key in structure:
                clean_node[key] = structure[key]
        if "nodes" in structure and structure["nodes"]:
            clean_node["nodes"] = create_clean_structure_for_description(structure["nodes"])
        return clean_node
    elif isinstance(structure, list):
        return [create_clean_structure_for_description(item) for item in structure]
    return structure


def print_toc(tree: list[dict], indent: int = 0) -> None:
    """Print a tree structure as indented text."""
    for node in tree:
        print("  " * indent + node["title"])
        if node.get("nodes"):
            print_toc(node["nodes"], indent + 1)


# --- Regex Helpers ---

def get_first_start_page_from_text(text: str) -> int:
    """Extract first start_index page number from tagged text."""
    match = re.search(r"<start_index_(\d+)>", text)
    return int(match.group(1)) if match else -1


def get_last_start_page_from_text(text: str) -> int:
    """Extract last start_index page number from tagged text."""
    matches = list(re.finditer(r"<start_index_(\d+)>", text))
    return int(matches[-1].group(1)) if matches else -1


def remove_first_physical_index_section(text: str) -> str:
    """Remove first physical_index tagged section from text."""
    pattern = r"<physical_index_\d+>.*?<physical_index_\d+>"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return text.replace(match.group(0), "", 1)
    return text


# --- Config ---

class ConfigLoader:
    """Load PageIndex configuration from YAML with user overrides."""

    _DEFAULTS = {
        "model": "gpt-4o",
        "toc_check_page_num": 20,
        "max_page_num_each_node": 10,
        "max_token_num_each_node": 20000,
        "if_add_node_id": "yes",
        "if_add_node_summary": "yes",
        "if_add_doc_description": "no",
        "if_add_node_text": "no",
    }

    def __init__(self, default_path: Optional[str] = None):
        if default_path and os.path.exists(default_path):
            self._default_dict = self._load_yaml(default_path)
        else:
            self._default_dict = dict(self._DEFAULTS)

    @staticmethod
    def _load_yaml(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _validate_keys(self, user_dict: dict) -> None:
        unknown_keys = set(user_dict) - set(self._default_dict)
        if unknown_keys:
            raise ValueError(f"Unknown config keys: {unknown_keys}")

    def load(self, user_opt: dict | config | None = None) -> config:
        """Merge user options with defaults."""
        if user_opt is None:
            user_dict: dict = {}
        elif isinstance(user_opt, config):
            user_dict = vars(user_opt)
        elif isinstance(user_opt, dict):
            user_dict = user_opt
        else:
            raise TypeError("user_opt must be dict, config (SimpleNamespace) or None")

        self._validate_keys(user_dict)
        merged = {**self._default_dict, **user_dict}
        return config(**merged)
