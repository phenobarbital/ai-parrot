"""Core type definitions for the formdesigner package.

This module defines the fundamental type aliases and enumerations
used throughout the forms abstraction layer.
"""

from enum import Enum


# LocalizedString supports both simple and i18n usage:
# Simple: "Enter your name"
# i18n:   {"en": "Enter your name", "es": "Ingrese su nombre"}
LocalizedString = str | dict[str, str]


class FieldType(str, Enum):
    """Supported form field types."""

    TEXT = "text"
    TEXT_AREA = "text_area"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    FILE = "file"
    IMAGE = "image"
    COLOR = "color"
    URL = "url"
    EMAIL = "email"
    PHONE = "phone"
    PASSWORD = "password"
    HIDDEN = "hidden"
    GROUP = "group"
    ARRAY = "array"
    # Phase 2 — new field types (FEAT-167)
    SIGNATURE = "signature"
    DYNAMIC_SELECT = "dynamic_select"
    TRANSFER_LIST = "transfer_list"
    REMOTE_RESPONSE = "remote_response"
    AVAILABILITY = "availability"
    LOCATION = "location"
    TAGS = "tags"
    NPS = "nps"
    LIKERT = "likert"
    RANKING = "ranking"
    # Phase 3 — new field type (FEAT-170)
    REST = "rest"
    # Phase 4 — audio form renderer (FEAT-224)
    AUDIO = "audio"
    # FEAT-300 — formula fields (inert stub; evaluator in FEAT-301)
    FORMULA = "formula"
