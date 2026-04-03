"""Unit tests for parrot-formdesigner tools."""
import pytest
from parrot.formdesigner.tools import CreateFormTool, DatabaseFormTool, RequestFormTool


class TestCreateFormTool:
    def test_has_docstring(self):
        assert CreateFormTool.__doc__ is not None
        assert len(CreateFormTool.__doc__) > 10

    def test_class_exists(self):
        assert CreateFormTool is not None


class TestDatabaseFormTool:
    def test_has_docstring(self):
        assert DatabaseFormTool.__doc__ is not None

    def test_class_exists(self):
        assert DatabaseFormTool is not None


class TestRequestFormTool:
    def test_has_docstring(self):
        assert RequestFormTool.__doc__ is not None

    def test_class_exists(self):
        assert RequestFormTool is not None
