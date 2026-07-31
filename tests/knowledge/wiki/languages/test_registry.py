"""Tests for the language-scanner suffix registry."""

from parrot.knowledge.wiki.languages import (
    all_scanners,
    scanned_suffixes,
    scanner_for,
)


def test_scanner_for_unknown_suffix_returns_none():
    assert scanner_for(".cfg") is None


def test_scanner_for_unregistered_language_suffix_returns_none():
    # No scanner is registered for these suffixes at the framework stage
    # (TASK-2010) — plugins land in later tasks.
    assert scanner_for(".xyz") is None


def test_scanned_suffixes_is_frozenset():
    assert isinstance(scanned_suffixes(), frozenset)


def test_all_scanners_returns_dict():
    scanners = all_scanners()
    assert isinstance(scanners, dict)
