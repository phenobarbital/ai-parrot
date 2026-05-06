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
