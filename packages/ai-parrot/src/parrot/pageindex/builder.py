"""PageIndex tree builder — LLM-agnostic port of the page_index pipeline."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
from io import BytesIO
from types import SimpleNamespace as config
from typing import Any, Optional

from .llm_adapter import PageIndexLLMAdapter
from .schemas import (
    GeneratedTocItem,
    PageIndexDetection,
    PhysicalIndexFix,
    TitleAppearanceCheck,
    TitleStartCheck,
    TocCompletionCheck,
    TocDetectionResult,
    TocItem,
    TocJson,
)
from .utils import (
    ConfigLoader,
    add_node_text,
    add_preface_if_needed,
    convert_page_to_int,
    convert_physical_index_to_int,
    count_tokens,
    extract_json,
    extract_matching_page_pairs,
    calculate_page_offset,
    add_page_offset_to_toc_json,
    get_json_content,
    get_page_tokens,
    get_pdf_name,
    list_to_tree,
    page_list_to_group_text,
    post_processing,
    remove_page_number,
    remove_structure_text,
    validate_and_truncate_physical_indices,
    write_node_id,
    create_clean_structure_for_description,
)

logger = logging.getLogger("parrot.pageindex")


# ======================== TOC Detection ========================

async def toc_detector_single_page(
    content: str,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Detect if a page contains a table of contents."""
    prompt = f"""
    Your job is to detect if there is a table of content provided in the given text.

    Given text: {content}

    return the following JSON format:
    {{
        "thinking": <why do you think there is a table of content in the given text>
        "toc_detected": "<yes or no>",
    }}

    Directly return the final JSON structure. Do not output anything else.
    Please note: abstract,summary, notation list, figure list, table list, etc. are not table of contents."""

    result = await adapter.ask_structured(prompt, TocDetectionResult)
    if isinstance(result, TocDetectionResult):
        return result.toc_detected
    return "no"


async def find_toc_pages(
    start_page_index: int,
    page_list: list[tuple[str, int]],
    opt: config,
    adapter: PageIndexLLMAdapter,
) -> list[int]:
    """Find pages containing table of contents."""
    last_page_is_yes = False
    toc_page_list: list[int] = []
    i = start_page_index

    while i < len(page_list):
        if i >= opt.toc_check_page_num and not last_page_is_yes:
            break
        detected_result = await toc_detector_single_page(page_list[i][0], adapter)
        if detected_result == "yes":
            logger.info("Page %d has TOC", i)
            toc_page_list.append(i)
            last_page_is_yes = True
        elif detected_result == "no" and last_page_is_yes:
            logger.info("Found last TOC page: %d", i - 1)
            break
        i += 1

    if not toc_page_list:
        logger.info("No TOC found")

    return toc_page_list


# ======================== TOC Extraction ========================

async def detect_page_index(
    toc_content: str,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Detect if page numbers/indices are present in the TOC."""
    prompt = f"""
    You will be given a table of contents.

    Your job is to detect if there are page numbers/indices given within the table of contents.

    Given text: {toc_content}

    Reply format:
    {{
        "thinking": <why do you think there are page numbers/indices given within the table of contents>
        "page_index_given_in_toc": "<yes or no>"
    }}
    Directly return the final JSON structure. Do not output anything else."""

    result = await adapter.ask_structured(prompt, PageIndexDetection)
    if isinstance(result, PageIndexDetection):
        return result.page_index_given_in_toc
    return "no"


async def toc_extractor(
    page_list: list[tuple[str, int]],
    toc_page_list: list[int],
    adapter: PageIndexLLMAdapter,
) -> dict[str, Any]:
    """Extract TOC content and check for page indices."""
    def transform_dots_to_colon(text: str) -> str:
        text = re.sub(r"\.{5,}", ": ", text)
        text = re.sub(r"(?:\. ){5,}\.?", ": ", text)
        return text

    toc_content = ""
    for page_index in toc_page_list:
        toc_content += page_list[page_index][0]
    toc_content = transform_dots_to_colon(toc_content)
    has_page_index = await detect_page_index(toc_content, adapter)

    return {
        "toc_content": toc_content,
        "page_index_given_in_toc": has_page_index,
    }


async def check_if_toc_extraction_is_complete(
    content: str,
    toc: str,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Check if a TOC extraction is complete."""
    prompt = f"""
    You are given a partial document and a table of contents.
    Your job is to check if the table of contents is complete, which it contains all the main sections in the partial document.

    Reply format:
    {{
        "thinking": <why do you think the table of contents is complete or not>
        "completed": "yes" or "no"
    }}
    Directly return the final JSON structure. Do not output anything else.

    Document:
    {content}

    Table of contents:
    {toc}"""

    result = await adapter.ask_structured(prompt, TocCompletionCheck)
    if isinstance(result, TocCompletionCheck):
        return result.completed
    return "no"


async def check_if_toc_transformation_is_complete(
    content: str,
    toc: str,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Check if a TOC transformation is complete."""
    prompt = f"""
    You are given a raw table of contents and a table of contents.
    Your job is to check if the table of contents is complete.

    Reply format:
    {{
        "thinking": <why do you think the cleaned table of contents is complete or not>
        "completed": "yes" or "no"
    }}
    Directly return the final JSON structure. Do not output anything else.

    Raw Table of contents:
    {content}

    Cleaned Table of contents:
    {toc}"""

    result = await adapter.ask_structured(prompt, TocCompletionCheck)
    if isinstance(result, TocCompletionCheck):
        return result.completed
    return "no"


async def extract_toc_content(
    content: str,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Extract full table of contents from raw text."""
    prompt = f"""
    Your job is to extract the full table of contents from the given text, replace ... with :

    Given text: {content}

    Directly return the full table of contents content. Do not output anything else."""

    response, finish_reason = await adapter.ask_with_finish_info(prompt)
    if_complete = await check_if_toc_transformation_is_complete(content, response, adapter)

    if if_complete == "yes" and finish_reason == "finished":
        return response

    chat_history = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response},
    ]
    continuation_prompt = "please continue the generation of table of contents, directly output the remaining part of the structure"
    new_response, finish_reason = await adapter.ask_with_finish_info(
        continuation_prompt, chat_history=chat_history
    )
    response = response + new_response
    if_complete = await check_if_toc_transformation_is_complete(content, response, adapter)

    retry_count = 0
    while not (if_complete == "yes" and finish_reason == "finished"):
        chat_history = [
            {"role": "user", "content": continuation_prompt},
            {"role": "assistant", "content": response},
        ]
        new_response, finish_reason = await adapter.ask_with_finish_info(
            continuation_prompt, chat_history=chat_history
        )
        response = response + new_response
        if_complete = await check_if_toc_transformation_is_complete(content, response, adapter)
        retry_count += 1
        if retry_count > 5:
            raise RuntimeError("Failed to complete table of contents after maximum retries")

    return response


# ======================== TOC Transformation ========================

async def toc_transformer(
    toc_content: str,
    adapter: PageIndexLLMAdapter,
) -> list[dict]:
    """Transform raw TOC text into structured JSON."""
    init_prompt = f"""
    You are given a table of contents, You job is to transform the whole table of content into a JSON format included table_of_contents.

    structure is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    The response should be in the following JSON format:
    {{
    table_of_contents: [
        {{
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "page": <page number or None>,
        }},
        ...
        ],
    }}
    You should transform the full table of contents in one go.
    Directly return the final JSON structure, do not output anything else.

    Given table of contents:
    {toc_content}"""

    last_complete, finish_reason = await adapter.ask_with_finish_info(init_prompt)
    if_complete = await check_if_toc_transformation_is_complete(
        toc_content, last_complete, adapter
    )
    if if_complete == "yes" and finish_reason == "finished":
        parsed = extract_json(last_complete)
        if isinstance(parsed, dict) and "table_of_contents" in parsed:
            return convert_page_to_int(parsed["table_of_contents"])
        return convert_page_to_int(parsed) if isinstance(parsed, list) else []

    last_complete = get_json_content(last_complete)
    retry_count = 0
    while not (if_complete == "yes" and finish_reason == "finished"):
        position = last_complete.rfind("}")
        if position != -1:
            last_complete = last_complete[: position + 2]
        continuation = f"""
        Your task is to continue the table of contents json structure, directly output the remaining part of the json structure.

        The raw table of contents json structure is:
        {toc_content}

        The incomplete transformed table of contents json structure is:
        {last_complete}

        Please continue the json structure, directly output the remaining part of the json structure."""

        new_complete, finish_reason = await adapter.ask_with_finish_info(continuation)

        if new_complete.startswith("```json"):
            new_complete = get_json_content(new_complete)
            last_complete = last_complete + new_complete

        if_complete = await check_if_toc_transformation_is_complete(
            toc_content, last_complete, adapter
        )
        retry_count += 1
        if retry_count > 5:
            break

    parsed = json.loads(last_complete) if isinstance(last_complete, str) else last_complete
    if isinstance(parsed, dict) and "table_of_contents" in parsed:
        return convert_page_to_int(parsed["table_of_contents"])
    return convert_page_to_int(parsed) if isinstance(parsed, list) else []


async def toc_index_extractor(
    toc: list[dict],
    content: str,
    adapter: PageIndexLLMAdapter,
) -> list[dict]:
    """Add physical_index to TOC items from tagged document content."""
    prompt = f"""
    You are given a table of contents in a json format and several pages of a document, your job is to add the physical_index to the table of contents in the json format.

    The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents.

    The response should be in the following JSON format:
    [
        {{
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "physical_index": "<physical_index_X>" (keep the format)
        }},
        ...
    ]

    Only add the physical_index to the sections that are in the provided pages.
    Directly return the final JSON structure. Do not output anything else.

    Table of contents:
    {json.dumps(toc)}

    Document pages:
    {content}"""

    return await adapter.ask_json(prompt)


# ======================== Page Number Mapping ========================

async def add_page_number_to_toc(
    part: str | list[str],
    structure: list[dict] | dict,
    adapter: PageIndexLLMAdapter,
) -> list[dict]:
    """Map section titles to physical indices in a document part."""
    if isinstance(part, list):
        part = "".join(part)
    if isinstance(structure, dict):
        structure = [structure]

    prompt = f"""
    You are given an JSON structure of a document and a partial part of the document. Your task is to check if the title that is described in the structure is started in the partial given document.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

    If the full target section starts in the partial given document, insert the given JSON structure with the "start": "yes", and "start_index": "<physical_index_X>".

    If the full target section does not start in the partial given document, insert "start": "no", "start_index": None.

    The response should be in the following format.
        [
            {{
                "structure": <structure index, "x.x.x" or None> (string),
                "title": <title of the section>,
                "start": "<yes or no>",
                "physical_index": "<physical_index_X> (keep the format)" or None
            }},
            ...
        ]
    The given structure contains the result of the previous part, you need to fill the result of the current part, do not change the previous result.
    Directly return the final JSON structure. Do not output anything else.

    Current Partial Document:
    {part}

    Given Structure:
    {json.dumps(structure, indent=2)}"""

    json_result = await adapter.ask_json(prompt)

    if isinstance(json_result, list):
        for item in json_result:
            if isinstance(item, dict) and "start" in item:
                del item["start"]
    return json_result


# ======================== Title Verification ========================

async def check_title_appearance(
    item: dict,
    page_list: list[tuple[str, int]],
    start_index: int = 1,
    adapter: PageIndexLLMAdapter = None,
) -> dict:
    """Check if a section title appears on its assigned page."""
    title = item["title"]
    if "physical_index" not in item or item["physical_index"] is None:
        return {
            "list_index": item.get("list_index"),
            "answer": "no",
            "title": title,
            "page_number": None,
        }

    page_number = item["physical_index"]
    list_idx = page_number - start_index
    if list_idx < 0 or list_idx >= len(page_list):
        return {
            "list_index": item.get("list_index"),
            "answer": "no",
            "title": title,
            "page_number": page_number,
        }
    page_text = page_list[list_idx][0]

    prompt = f"""
    Your job is to check if the given section appears or starts in the given page_text.

    Note: do fuzzy matching, ignore any space inconsistency in the page_text.

    The given section title is {title}.
    The given page_text is {page_text}.

    Reply format:
    {{
        "thinking": <why do you think the section appears or starts in the page_text>
        "answer": "yes or no" (yes if the section appears or starts in the page_text, no otherwise)
    }}
    Directly return the final JSON structure. Do not output anything else."""

    result = await adapter.ask_structured(prompt, TitleAppearanceCheck)
    answer = result.answer if isinstance(result, TitleAppearanceCheck) else "no"
    return {
        "list_index": item.get("list_index"),
        "answer": answer,
        "title": title,
        "page_number": page_number,
    }


async def check_title_appearance_in_start(
    title: str,
    page_text: str,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Check if a section starts at the beginning of a page."""
    prompt = f"""
    You will be given the current section title and the current page_text.
    Your job is to check if the current section starts in the beginning of the given page_text.
    If there are other contents before the current section title, then the current section does not start in the beginning of the given page_text.

    Note: do fuzzy matching, ignore any space inconsistency in the page_text.

    The given section title is {title}.
    The given page_text is {page_text}.

    reply format:
    {{
        "thinking": <why do you think the section appears or starts in the page_text>
        "start_begin": "yes or no" (yes if the section starts in the beginning of the page_text, no otherwise)
    }}
    Directly return the final JSON structure. Do not output anything else."""

    result = await adapter.ask_structured(prompt, TitleStartCheck)
    return result.start_begin if isinstance(result, TitleStartCheck) else "no"


async def check_title_appearance_in_start_concurrent(
    structure: list[dict],
    page_list: list[tuple[str, int]],
    adapter: PageIndexLLMAdapter,
) -> list[dict]:
    """Concurrently check title starts for all items."""
    for item in structure:
        if item.get("physical_index") is None:
            item["appear_start"] = "no"

    tasks = []
    valid_items = []
    for item in structure:
        if item.get("physical_index") is not None:
            idx = item["physical_index"] - 1
            if 0 <= idx < len(page_list):
                page_text = page_list[idx][0]
                tasks.append(
                    check_title_appearance_in_start(item["title"], page_text, adapter)
                )
                valid_items.append(item)
            else:
                item["appear_start"] = "no"

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item, result in zip(valid_items, results):
        if isinstance(result, Exception):
            logger.error("Error checking start for %s: %s", item["title"], result)
            item["appear_start"] = "no"
        else:
            item["appear_start"] = result

    return structure


# ======================== TOC Fixing ========================

async def single_toc_item_index_fixer(
    section_title: str,
    content: str,
    adapter: PageIndexLLMAdapter,
) -> int | None:
    """Find the correct physical index for a misaligned section."""
    prompt = f"""
    You are given a section title and several pages of a document, your job is to find the physical index of the start page of the section in the partial document.

    The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

    Reply in a JSON format:
    {{
        "thinking": <explain which page, started and closed by <physical_index_X>, contains the start of this section>,
        "physical_index": "<physical_index_X>" (keep the format)
    }}
    Directly return the final JSON structure. Do not output anything else.

    Section Title:
    {section_title}

    Document pages:
    {content}"""

    result = await adapter.ask_structured(prompt, PhysicalIndexFix)
    if isinstance(result, PhysicalIndexFix):
        return convert_physical_index_to_int(result.physical_index)
    return None


async def fix_incorrect_toc(
    toc_with_page_number: list[dict],
    page_list: list[tuple[str, int]],
    incorrect_results: list[dict],
    start_index: int = 1,
    adapter: PageIndexLLMAdapter = None,
) -> tuple[list[dict], list[dict]]:
    """Fix incorrect TOC entries by re-searching nearby pages."""
    incorrect_indices = {result["list_index"] for result in incorrect_results}
    end_index = len(page_list) + start_index - 1

    async def process_and_check_item(incorrect_item: dict) -> dict:
        list_index = incorrect_item["list_index"]

        if list_index < 0 or list_index >= len(toc_with_page_number):
            return {
                "list_index": list_index,
                "title": incorrect_item["title"],
                "physical_index": incorrect_item.get("physical_index"),
                "is_valid": False,
            }

        # Find previous correct item
        prev_correct = start_index - 1
        for i in range(list_index - 1, -1, -1):
            if i not in incorrect_indices and 0 <= i < len(toc_with_page_number):
                pi = toc_with_page_number[i].get("physical_index")
                if pi is not None:
                    prev_correct = pi
                    break

        # Find next correct item
        next_correct = end_index
        for i in range(list_index + 1, len(toc_with_page_number)):
            if i not in incorrect_indices and 0 <= i < len(toc_with_page_number):
                pi = toc_with_page_number[i].get("physical_index")
                if pi is not None:
                    next_correct = pi
                    break

        page_contents = []
        for page_index in range(prev_correct, next_correct + 1):
            li = page_index - start_index
            if 0 <= li < len(page_list):
                page_text = (
                    f"<physical_index_{page_index}>\n"
                    f"{page_list[li][0]}\n"
                    f"<physical_index_{page_index}>\n\n"
                )
                page_contents.append(page_text)

        content_range = "".join(page_contents)
        physical_index_int = await single_toc_item_index_fixer(
            incorrect_item["title"], content_range, adapter
        )

        check_item = incorrect_item.copy()
        check_item["physical_index"] = physical_index_int
        check_result = await check_title_appearance(
            check_item, page_list, start_index, adapter
        )

        return {
            "list_index": list_index,
            "title": incorrect_item["title"],
            "physical_index": physical_index_int,
            "is_valid": check_result["answer"] == "yes",
        }

    tasks = [process_and_check_item(item) for item in incorrect_results]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    results = [r for r in results if not isinstance(r, Exception)]

    invalid_results: list[dict] = []
    for result in results:
        if result["is_valid"]:
            idx = result["list_index"]
            if 0 <= idx < len(toc_with_page_number):
                toc_with_page_number[idx]["physical_index"] = result["physical_index"]
            else:
                invalid_results.append(result)
        else:
            invalid_results.append(result)

    return toc_with_page_number, invalid_results


async def fix_incorrect_toc_with_retries(
    toc_with_page_number: list[dict],
    page_list: list[tuple[str, int]],
    incorrect_results: list[dict],
    start_index: int = 1,
    max_attempts: int = 3,
    adapter: PageIndexLLMAdapter = None,
) -> tuple[list[dict], list[dict]]:
    """Fix incorrect TOC entries with retries."""
    fix_attempt = 0
    current_toc = toc_with_page_number
    current_incorrect = incorrect_results

    while current_incorrect:
        logger.info("Fixing %d incorrect results (attempt %d)", len(current_incorrect), fix_attempt + 1)
        current_toc, current_incorrect = await fix_incorrect_toc(
            current_toc, page_list, current_incorrect, start_index, adapter
        )
        fix_attempt += 1
        if fix_attempt >= max_attempts:
            logger.info("Maximum fix attempts reached")
            break

    return current_toc, current_incorrect


# ======================== TOC Verification ========================

async def verify_toc(
    page_list: list[tuple[str, int]],
    list_result: list[dict],
    start_index: int = 1,
    adapter: PageIndexLLMAdapter = None,
) -> tuple[float, list[dict]]:
    """Verify TOC accuracy by checking title appearances."""
    import random

    last_physical_index = None
    for item in reversed(list_result):
        if item.get("physical_index") is not None:
            last_physical_index = item["physical_index"]
            break

    if last_physical_index is None or last_physical_index < len(page_list) / 2:
        return 0, []

    sample_indices = range(0, len(list_result))

    indexed_sample_list = []
    for idx in sample_indices:
        item = list_result[idx]
        if item.get("physical_index") is not None:
            item_with_index = item.copy()
            item_with_index["list_index"] = idx
            indexed_sample_list.append(item_with_index)

    tasks = [
        check_title_appearance(item, page_list, start_index, adapter)
        for item in indexed_sample_list
    ]
    results = await asyncio.gather(*tasks)

    correct_count = 0
    incorrect_results: list[dict] = []
    for result in results:
        if result["answer"] == "yes":
            correct_count += 1
        else:
            incorrect_results.append(result)

    checked_count = len(results)
    accuracy = correct_count / checked_count if checked_count > 0 else 0
    logger.info("TOC verification accuracy: %.2f%%", accuracy * 100)
    return accuracy, incorrect_results


# ======================== No-TOC Processing ========================

async def generate_toc_init(
    part: str,
    adapter: PageIndexLLMAdapter,
) -> list[dict]:
    """Generate initial TOC from document content when no TOC exists."""
    prompt = f"""
    You are an expert in extracting hierarchical tree structure, your task is to generate the tree structure of the document.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents.

    For the title, you need to extract the original title from the text, only fix the space inconsistency.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

    For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

    The response should be in the following format.
        [
            {{
                "structure": <structure index, "x.x.x"> (string),
                "title": <title of the section, keep the original title>,
                "physical_index": "<physical_index_X> (keep the format)"
            }},
        ],

    Directly return the final JSON structure. Do not output anything else.

    Given text:
    {part}"""

    response, finish_reason = await adapter.ask_with_finish_info(prompt)
    if finish_reason == "finished":
        return extract_json(response)
    raise RuntimeError(f"Unexpected finish reason: {finish_reason}")


async def generate_toc_continue(
    toc_content: list[dict],
    part: str,
    adapter: PageIndexLLMAdapter,
) -> list[dict]:
    """Continue TOC generation for the next document part."""
    prompt = f"""
    You are an expert in extracting hierarchical tree structure.
    You are given a tree structure of the previous part and the text of the current part.
    Your task is to continue the tree structure from the previous part to include the current part.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents.

    For the title, you need to extract the original title from the text, only fix the space inconsistency.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

    For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

    The response should be in the following format.
        [
            {{
                "structure": <structure index, "x.x.x"> (string),
                "title": <title of the section, keep the original title>,
                "physical_index": "<physical_index_X> (keep the format)"
            }},
            ...
        ]

    Directly return the additional part of the final JSON structure. Do not output anything else.

    Given text:
    {part}

    Previous tree structure:
    {json.dumps(toc_content, indent=2)}"""

    response, finish_reason = await adapter.ask_with_finish_info(prompt)
    if finish_reason == "finished":
        return extract_json(response)
    raise RuntimeError(f"Unexpected finish reason: {finish_reason}")


async def process_no_toc(
    page_list: list[tuple[str, int]],
    start_index: int = 1,
    adapter: PageIndexLLMAdapter = None,
) -> list[dict]:
    """Process document without existing TOC."""
    page_contents = []
    token_lengths = []
    for page_index in range(start_index, start_index + len(page_list)):
        page_text = (
            f"<physical_index_{page_index}>\n"
            f"{page_list[page_index - start_index][0]}\n"
            f"<physical_index_{page_index}>\n\n"
        )
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text))

    group_texts = page_list_to_group_text(page_contents, token_lengths)
    logger.info("No-TOC processing: %d text groups", len(group_texts))

    toc_with_page_number = await generate_toc_init(group_texts[0], adapter)
    for group_text in group_texts[1:]:
        additional = await generate_toc_continue(toc_with_page_number, group_text, adapter)
        toc_with_page_number.extend(additional)

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    return toc_with_page_number


# ======================== TOC with/without Page Numbers ========================

async def process_toc_no_page_numbers(
    toc_content: str,
    toc_page_list: list[int],
    page_list: list[tuple[str, int]],
    start_index: int = 1,
    adapter: PageIndexLLMAdapter = None,
) -> list[dict]:
    """Process TOC that exists but lacks page numbers."""
    toc_items = await toc_transformer(toc_content, adapter)
    logger.info("TOC transformed: %d items", len(toc_items))

    page_contents = []
    token_lengths = []
    for page_index in range(start_index, start_index + len(page_list)):
        page_text = (
            f"<physical_index_{page_index}>\n"
            f"{page_list[page_index - start_index][0]}\n"
            f"<physical_index_{page_index}>\n\n"
        )
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text))

    group_texts = page_list_to_group_text(page_contents, token_lengths)

    toc_with_page_number = copy.deepcopy(toc_items)
    for group_text in group_texts:
        toc_with_page_number = await add_page_number_to_toc(
            group_text, toc_with_page_number, adapter
        )

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    return toc_with_page_number


async def process_none_page_numbers(
    toc_items: list[dict],
    page_list: list[tuple[str, int]],
    start_index: int = 1,
    adapter: PageIndexLLMAdapter = None,
) -> list[dict]:
    """Fill in missing physical indices for items that lack them."""
    for i, item in enumerate(toc_items):
        if "physical_index" not in item:
            prev_physical_index = 0
            for j in range(i - 1, -1, -1):
                if toc_items[j].get("physical_index") is not None:
                    prev_physical_index = toc_items[j]["physical_index"]
                    break

            next_physical_index = -1
            for j in range(i + 1, len(toc_items)):
                if toc_items[j].get("physical_index") is not None:
                    next_physical_index = toc_items[j]["physical_index"]
                    break

            page_contents = []
            for page_index in range(prev_physical_index, next_physical_index + 1):
                list_index = page_index - start_index
                if 0 <= list_index < len(page_list):
                    page_text = (
                        f"<physical_index_{page_index}>\n"
                        f"{page_list[list_index][0]}\n"
                        f"<physical_index_{page_index}>\n\n"
                    )
                    page_contents.append(page_text)

            item_copy = copy.deepcopy(item)
            item_copy.pop("page", None)
            result = await add_page_number_to_toc(page_contents, item_copy, adapter)
            if (
                isinstance(result, list)
                and result
                and isinstance(result[0].get("physical_index"), str)
                and result[0]["physical_index"].startswith("<physical_index")
            ):
                item["physical_index"] = int(
                    result[0]["physical_index"].split("_")[-1].rstrip(">").strip()
                )
                item.pop("page", None)

    return toc_items


async def process_toc_with_page_numbers(
    toc_content: str,
    toc_page_list: list[int],
    page_list: list[tuple[str, int]],
    toc_check_page_num: int = 20,
    adapter: PageIndexLLMAdapter = None,
) -> list[dict]:
    """Process TOC that has page numbers."""
    toc_with_page_number = await toc_transformer(toc_content, adapter)

    toc_no_page = remove_page_number(copy.deepcopy(toc_with_page_number))

    start_page_index = toc_page_list[-1] + 1
    main_content = ""
    for page_index in range(
        start_page_index,
        min(start_page_index + toc_check_page_num, len(page_list)),
    ):
        main_content += (
            f"<physical_index_{page_index+1}>\n"
            f"{page_list[page_index][0]}\n"
            f"<physical_index_{page_index+1}>\n\n"
        )

    toc_with_physical_index = await toc_index_extractor(toc_no_page, main_content, adapter)
    toc_with_physical_index = convert_physical_index_to_int(toc_with_physical_index)

    matching_pairs = extract_matching_page_pairs(
        toc_with_page_number, toc_with_physical_index, start_page_index
    )
    offset = calculate_page_offset(matching_pairs)

    if offset is not None:
        toc_with_page_number = add_page_offset_to_toc_json(toc_with_page_number, offset)

    toc_with_page_number = await process_none_page_numbers(
        toc_with_page_number, page_list, adapter=adapter
    )

    return toc_with_page_number


# ======================== TOC Check ========================

async def check_toc(
    page_list: list[tuple[str, int]],
    opt: config,
    adapter: PageIndexLLMAdapter,
) -> dict[str, Any]:
    """Check for TOC presence and extract if found."""
    toc_page_list = await find_toc_pages(0, page_list, opt, adapter)
    if not toc_page_list:
        logger.info("No TOC found")
        return {"toc_content": None, "toc_page_list": [], "page_index_given_in_toc": "no"}

    logger.info("TOC found on pages: %s", toc_page_list)
    toc_json = await toc_extractor(page_list, toc_page_list, adapter)

    if toc_json["page_index_given_in_toc"] == "yes":
        return {
            "toc_content": toc_json["toc_content"],
            "toc_page_list": toc_page_list,
            "page_index_given_in_toc": "yes",
        }

    current_start_index = toc_page_list[-1] + 1
    while (
        toc_json["page_index_given_in_toc"] == "no"
        and current_start_index < len(page_list)
        and current_start_index < opt.toc_check_page_num
    ):
        additional_toc_pages = await find_toc_pages(
            current_start_index, page_list, opt, adapter
        )
        if not additional_toc_pages:
            break
        additional_toc_json = await toc_extractor(page_list, additional_toc_pages, adapter)
        if additional_toc_json["page_index_given_in_toc"] == "yes":
            return {
                "toc_content": additional_toc_json["toc_content"],
                "toc_page_list": additional_toc_pages,
                "page_index_given_in_toc": "yes",
            }
        current_start_index = additional_toc_pages[-1] + 1

    return {
        "toc_content": toc_json["toc_content"],
        "toc_page_list": toc_page_list,
        "page_index_given_in_toc": "no",
    }


# ======================== Main Pipeline ========================

async def meta_processor(
    page_list: list[tuple[str, int]],
    mode: str | None = None,
    toc_content: str | None = None,
    toc_page_list: list[int] | None = None,
    start_index: int = 1,
    opt: config | None = None,
    adapter: PageIndexLLMAdapter = None,
) -> list[dict]:
    """Main processing orchestrator for different TOC modes."""
    logger.info("meta_processor mode=%s, start_index=%d", mode, start_index)

    if mode == "process_toc_with_page_numbers":
        toc_with_page_number = await process_toc_with_page_numbers(
            toc_content, toc_page_list, page_list,
            toc_check_page_num=opt.toc_check_page_num,
            adapter=adapter,
        )
    elif mode == "process_toc_no_page_numbers":
        toc_with_page_number = await process_toc_no_page_numbers(
            toc_content, toc_page_list, page_list,
            adapter=adapter,
        )
    else:
        toc_with_page_number = await process_no_toc(
            page_list, start_index=start_index, adapter=adapter,
        )

    toc_with_page_number = [
        item for item in toc_with_page_number
        if item.get("physical_index") is not None
    ]
    toc_with_page_number = validate_and_truncate_physical_indices(
        toc_with_page_number, len(page_list), start_index=start_index
    )

    accuracy, incorrect_results = await verify_toc(
        page_list, toc_with_page_number, start_index=start_index, adapter=adapter
    )

    if accuracy == 1.0 and len(incorrect_results) == 0:
        return toc_with_page_number
    if accuracy > 0.6 and incorrect_results:
        toc_with_page_number, _ = await fix_incorrect_toc_with_retries(
            toc_with_page_number, page_list, incorrect_results,
            start_index=start_index, max_attempts=3, adapter=adapter,
        )
        return toc_with_page_number
    else:
        if mode == "process_toc_with_page_numbers":
            return await meta_processor(
                page_list, mode="process_toc_no_page_numbers",
                toc_content=toc_content, toc_page_list=toc_page_list,
                start_index=start_index, opt=opt, adapter=adapter,
            )
        elif mode == "process_toc_no_page_numbers":
            return await meta_processor(
                page_list, mode="process_no_toc",
                start_index=start_index, opt=opt, adapter=adapter,
            )
        else:
            raise RuntimeError("Processing failed")


async def process_large_node_recursively(
    node: dict,
    page_list: list[tuple[str, int]],
    opt: config,
    adapter: PageIndexLLMAdapter,
) -> dict:
    """Recursively split large nodes into sub-trees."""
    node_page_list = page_list[node["start_index"] - 1 : node["end_index"]]
    token_num = sum(page[1] for page in node_page_list)

    if (
        node["end_index"] - node["start_index"] > opt.max_page_num_each_node
        and token_num >= opt.max_token_num_each_node
    ):
        logger.info(
            "Large node: %s (%d-%d, %d tokens)",
            node["title"], node["start_index"], node["end_index"], token_num,
        )

        node_toc_tree = await meta_processor(
            node_page_list, mode="process_no_toc",
            start_index=node["start_index"], opt=opt, adapter=adapter,
        )
        node_toc_tree = await check_title_appearance_in_start_concurrent(
            node_toc_tree, page_list, adapter
        )

        valid_items = [
            item for item in node_toc_tree if item.get("physical_index") is not None
        ]

        if valid_items and node["title"].strip() == valid_items[0]["title"].strip():
            node["nodes"] = post_processing(valid_items[1:], node["end_index"])
            node["end_index"] = (
                valid_items[1]["start_index"] if len(valid_items) > 1 else node["end_index"]
            )
        else:
            node["nodes"] = post_processing(valid_items, node["end_index"])
            node["end_index"] = (
                valid_items[0]["start_index"] if valid_items else node["end_index"]
            )

    if "nodes" in node and node["nodes"]:
        tasks = [
            process_large_node_recursively(child, page_list, opt, adapter)
            for child in node["nodes"]
        ]
        await asyncio.gather(*tasks)

    return node


async def tree_parser(
    page_list: list[tuple[str, int]],
    opt: config,
    adapter: PageIndexLLMAdapter,
) -> list[dict]:
    """Parse page list into a hierarchical tree."""
    check_toc_result = await check_toc(page_list, opt, adapter)

    if (
        check_toc_result.get("toc_content")
        and check_toc_result["toc_content"].strip()
        and check_toc_result["page_index_given_in_toc"] == "yes"
    ):
        toc_with_page_number = await meta_processor(
            page_list,
            mode="process_toc_with_page_numbers",
            start_index=1,
            toc_content=check_toc_result["toc_content"],
            toc_page_list=check_toc_result["toc_page_list"],
            opt=opt,
            adapter=adapter,
        )
    else:
        toc_with_page_number = await meta_processor(
            page_list, mode="process_no_toc",
            start_index=1, opt=opt, adapter=adapter,
        )

    toc_with_page_number = add_preface_if_needed(toc_with_page_number)
    toc_with_page_number = await check_title_appearance_in_start_concurrent(
        toc_with_page_number, page_list, adapter
    )

    valid_toc_items = [
        item for item in toc_with_page_number if item.get("physical_index") is not None
    ]

    toc_tree = post_processing(valid_toc_items, len(page_list))
    tasks = [
        process_large_node_recursively(node, page_list, opt, adapter)
        for node in toc_tree
    ]
    await asyncio.gather(*tasks)

    return toc_tree


# ======================== Summary Generation ========================

async def generate_node_summary(
    node: dict,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Generate a summary for a single node."""
    prompt = f"""You are given a part of a document, your task is to generate a description of the partial document about what are main points covered in the partial document.

    Partial Document Text: {node['text']}

    Directly return the description, do not include any other text."""

    return await adapter.ask(prompt)


async def generate_summaries_for_structure(
    structure: Any,
    adapter: PageIndexLLMAdapter,
) -> Any:
    """Generate summaries for all nodes in a tree structure."""
    from .utils import structure_to_list

    nodes = structure_to_list(structure)
    tasks = [generate_node_summary(node, adapter) for node in nodes]
    summaries = await asyncio.gather(*tasks)

    for node, summary in zip(nodes, summaries):
        node["summary"] = summary
    return structure


async def generate_doc_description(
    structure: Any,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Generate a one-sentence document description."""
    prompt = f"""Your are an expert in generating descriptions for a document.
    You are given a structure of a document. Your task is to generate a one-sentence description for the document, which makes it easy to distinguish the document from other documents.

    Document Structure: {json.dumps(structure) if not isinstance(structure, str) else structure}

    Directly return the description, do not include any other text."""

    return await adapter.ask(prompt)


# ======================== Public API ========================

async def build_page_index(
    doc: str | BytesIO,
    adapter: PageIndexLLMAdapter,
    options: dict | config | None = None,
) -> dict:
    """Build a PageIndex tree from a PDF document.

    Args:
        doc: Path to a PDF file or BytesIO stream.
        adapter: LLM adapter wrapping any AbstractClient.
        options: Configuration dict or SimpleNamespace with keys like
            model, toc_check_page_num, max_page_num_each_node, etc.

    Returns:
        Dictionary with doc_name and structure (the tree).
    """
    opt = ConfigLoader().load(options)
    page_list = get_page_tokens(doc)

    logger.info("Total pages: %d, Total tokens: %d", len(page_list), sum(p[1] for p in page_list))

    structure = await tree_parser(page_list, opt, adapter)

    if opt.if_add_node_id == "yes":
        write_node_id(structure)
    if opt.if_add_node_text == "yes":
        add_node_text(structure, page_list)
    if opt.if_add_node_summary == "yes":
        if opt.if_add_node_text == "no":
            add_node_text(structure, page_list)
        await generate_summaries_for_structure(structure, adapter)
        if opt.if_add_node_text == "no":
            remove_structure_text(structure)
        if opt.if_add_doc_description == "yes":
            clean_struct = create_clean_structure_for_description(structure)
            doc_description = await generate_doc_description(clean_struct, adapter)
            return {
                "doc_name": get_pdf_name(doc),
                "doc_description": doc_description,
                "structure": structure,
            }

    return {
        "doc_name": get_pdf_name(doc),
        "structure": structure,
    }
