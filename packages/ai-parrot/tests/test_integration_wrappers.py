"""
Tests for Integration Wrappers Response Parsing.

Tests the ParsedResponse dataclass and parse_response function,
as well as integration-specific methods.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass
from typing import List, Optional, Any

# Test the parser module
from parrot.integrations.parser import (
    ParsedResponse,
    parse_response,
    _dataframe_to_markdown,
    _classify_file
)


class TestParsedResponse:
    """Tests for ParsedResponse dataclass."""
    
    def test_has_attachments_empty(self):
        """ParsedResponse with no files should return False."""
        parsed = ParsedResponse()
        assert parsed.has_attachments is False
    
    def test_has_attachments_with_images(self):
        """ParsedResponse with images should return True."""
        parsed = ParsedResponse(images=[Path("/tmp/test.png")])
        assert parsed.has_attachments is True
    
    def test_has_attachments_with_documents(self):
        """ParsedResponse with documents should return True."""
        parsed = ParsedResponse(documents=[Path("/tmp/test.pdf")])
        assert parsed.has_attachments is True
    
    def test_has_table_false(self):
        """ParsedResponse without table data should return False."""
        parsed = ParsedResponse()
        assert parsed.has_table is False
    
    def test_has_table_with_markdown(self):
        """ParsedResponse with table_markdown should return True."""
        parsed = ParsedResponse(table_markdown="| A | B |\n|---|---|\n| 1 | 2 |")
        assert parsed.has_table is True
    
    def test_has_code_false(self):
        """ParsedResponse without code should return False."""
        parsed = ParsedResponse()
        assert parsed.has_code is False
    
    def test_has_code_true(self):
        """ParsedResponse with code should return True."""
        parsed = ParsedResponse(code="print('hello')")
        assert parsed.has_code is True


class TestParseResponse:
    """Tests for parse_response function."""
    
    def test_parse_none(self):
        """Parsing None should return default text."""
        parsed = parse_response(None)
        assert parsed.text == "I don't have a response for that."
    
    def test_parse_string(self):
        """Parsing a string should return it as text."""
        parsed = parse_response("Hello, world!")
        assert parsed.text == "Hello, world!"
    
    def test_parse_response_attribute(self):
        """Parsing object with 'response' attribute should extract text."""
        mock = MagicMock()
        mock.response = "Agent response text"
        mock.content = None
        mock.output = None
        
        parsed = parse_response(mock)
        assert parsed.text == "Agent response text"
    
    def test_parse_content_string(self):
        """Parsing object with string 'content' should extract it."""
        mock = MagicMock()
        mock.response = None
        mock.content = "Content text"
        
        parsed = parse_response(mock)
        assert parsed.text == "Content text"
    
    def test_parse_code_attribute(self):
        """Parsing object with 'code' should extract it."""
        mock = MagicMock()
        mock.response = "Response text"
        mock.code = "def hello(): pass"
        mock.images = []
        mock.files = []
        mock.documents = []
        mock.media = []
        mock.data = None
        mock.structured_output = None
        
        parsed = parse_response(mock)
        assert parsed.code == "def hello(): pass"
        assert parsed.code_language == "python"
    
    def test_parse_json_code(self):
        """Parsing JSON code should detect language."""
        mock = MagicMock()
        mock.response = "JSON output"
        mock.code = '{"key": "value"}'
        mock.images = []
        mock.files = []
        mock.documents = []
        mock.media = []
        mock.data = None
        mock.structured_output = None
        
        parsed = parse_response(mock)
        assert parsed.code_language == "json"


class TestDataframeToMarkdown:
    """Tests for DataFrame to markdown conversion."""
    
    def test_without_pandas(self):
        """When pandas not available, should return str()."""
        # This test just ensures it doesn't crash for non-DataFrames
        result = _dataframe_to_markdown("not a dataframe")
        assert result == "not a dataframe"
    
    @pytest.mark.skipif(True, reason="Requires pandas")
    def test_with_dataframe(self):
        """Test markdown table generation from DataFrame."""
        import pandas as pd
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        result = _dataframe_to_markdown(df)
        assert "| A | B |" in result
        assert "| 1 | 3 |" in result


class TestClassifyFile:
    """Tests for file type classification."""
    
    def test_classify_image_jpg(self, tmp_path):
        """JPG files should be classified as image."""
        file = tmp_path / "test.jpg"
        file.touch()
        assert _classify_file(file) == "image"
    
    def test_classify_image_png(self, tmp_path):
        """PNG files should be classified as image."""
        file = tmp_path / "test.png"
        file.touch()
        assert _classify_file(file) == "image"
    
    def test_classify_video_mp4(self, tmp_path):
        """MP4 files should be classified as video."""
        file = tmp_path / "test.mp4"
        file.touch()
        assert _classify_file(file) == "video"
    
    def test_classify_audio_mp3(self, tmp_path):
        """MP3 files should be classified as audio."""
        file = tmp_path / "test.mp3"
        file.touch()
        assert _classify_file(file) == "audio"
    
    def test_classify_document_pdf(self, tmp_path):
        """PDF files should be classified as document."""
        file = tmp_path / "test.pdf"
        file.touch()
        assert _classify_file(file) == "document"
    
    def test_classify_nonexistent(self):
        """Non-existent files should be classified as unknown."""
        assert _classify_file(Path("/nonexistent/file.xyz")) == "unknown"


class TestMSTeamsAdaptiveCard:
    """Tests for MS Teams Adaptive Card building."""
    
    def test_build_card_text_only(self):
        """Card with only text should have TextBlock."""
        from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
        
        # We need to test the method directly without full setup
        # Create minimal mock
        parsed = ParsedResponse(text="Hello from agent!")
        
        # Import and call the method directly
        wrapper = object.__new__(MSTeamsAgentWrapper)
        card = wrapper._build_adaptive_card(parsed)
        
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.4"
        assert len(card["body"]) == 1
        assert card["body"][0]["type"] == "TextBlock"
        assert card["body"][0]["text"] == "Hello from agent!"
    
    def test_build_card_with_code(self):
        """Card with code should have monospace TextBlock."""
        from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
        
        parsed = ParsedResponse(
            text="Here is some code:",
            code="print('hello')",
            code_language="python"
        )
        
        wrapper = object.__new__(MSTeamsAgentWrapper)
        card = wrapper._build_adaptive_card(parsed)
        
        # Should have text + code label + code block
        assert len(card["body"]) >= 2
        # Find the monospace block
        monospace_blocks = [b for b in card["body"] if b.get("fontType") == "Monospace"]
        assert len(monospace_blocks) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
