"""TASK-2141: Custom-report JSON parsing path (_parse_json_to_entries)."""
from __future__ import annotations

import json
import logging

import pandas as pd
from parrot_tools.interfaces.workday.handlers.custom_report import CustomReportType


class _FakeService:
    """Minimal stand-in providing the attributes CustomReportType reads via getattr."""

    def __init__(self):
        self._logger = logging.getLogger("test.workday.custom_report")
        self.tenant = "testtenant"
        self.report_owner = "owner@example.com"
        self.workday_url = "https://example.com"
        self.report_username = "user"
        self.report_password = "pass"


class _FakeHTTPClient:
    """Stand-in for HTTPService — records calls, returns a canned response."""

    def __init__(self, response, error=None):
        self.response = response
        self.error = error
        self.calls: list = []

    async def async_request(self, url, method="GET", accept=None):
        self.calls.append({"url": url, "method": method, "accept": accept})
        return self.response, self.error


class TestJsonParsing:
    def test_parses_json_body_to_entries(self):
        """A RaaS JSON body yields the same entry shape as the XML path."""
        handler = CustomReportType(_FakeService())
        body = {"Report_Entry": [{"a": 1}, {"a": 2}]}
        assert handler._parse_json_to_entries(body) == [{"a": 1}, {"a": 2}]

    def test_parses_json_string_body(self):
        handler = CustomReportType(_FakeService())
        body = json.dumps({"Report_Entry": [{"a": 1}]})
        assert handler._parse_json_to_entries(body) == [{"a": 1}]

    def test_parses_bytes_body(self):
        handler = CustomReportType(_FakeService())
        body = json.dumps([{"a": 1}]).encode("utf-8")
        assert handler._parse_json_to_entries(body) == [{"a": 1}]

    def test_bare_list_body(self):
        handler = CustomReportType(_FakeService())
        assert handler._parse_json_to_entries([{"a": 1}]) == [{"a": 1}]

    def test_single_report_entry_dict_wrapped_in_list(self):
        handler = CustomReportType(_FakeService())
        body = {"Report_Entry": {"a": 1}}
        assert handler._parse_json_to_entries(body) == [{"a": 1}]

    def test_same_entry_shape_as_xml_parser(self):
        handler = CustomReportType(_FakeService())
        json_entries = handler._parse_json_to_entries({"Report_Entry": [{"Employee_ID": "E1"}]})
        xml_entries = handler._parse_xml_to_entries(
            b"<Report_Data><Report_Entry><Employee_ID>E1</Employee_ID></Report_Entry></Report_Data>"
        )
        assert json_entries == xml_entries

    def test_empty_body_returns_empty_list(self):
        handler = CustomReportType(_FakeService())
        assert handler._parse_json_to_entries(None) == []
        assert handler._parse_json_to_entries({}) == []
        assert handler._parse_json_to_entries("[]") == []
        assert handler._parse_json_to_entries([]) == []

    def test_nested_list_dict_columns_expand(self):
        """Entries feed _expand_list_dict_columns without change."""
        handler = CustomReportType(_FakeService())
        entries = handler._parse_json_to_entries(
            {
                "Report_Entry": [
                    {
                        "Employee_ID": "E1",
                        "Roles": [{"type": "Role", "_value": "Manager"}],
                    }
                ]
            }
        )
        df = pd.json_normalize(entries, sep="_", max_level=None)
        expanded = handler._expand_list_dict_columns(df, drop_original=True)
        assert "Roles_Role" in expanded.columns
        assert expanded.iloc[0]["Roles_Role"] == "Manager"


class TestFormatRouting:
    async def test_json_response_routed_to_json_parser(self):
        handler = CustomReportType(_FakeService())
        json_body = json.dumps({"Report_Entry": [{"Employee_ID": "E1", "Name": "Alice"}]})
        handler._http_client = _FakeHTTPClient(response=json_body)

        df = await handler.execute(report_name="My_Report", output_format="json")

        assert list(df["Employee_ID"]) == ["E1"]
        call = handler._http_client.calls[0]
        assert call["accept"] == "application/json"
        assert "format=json" in call["url"]

    async def test_xml_response_still_routed_to_xml_parser(self):
        """Regression: existing XML behaviour unchanged."""
        handler = CustomReportType(_FakeService())
        xml_body = (
            b"<Report_Data><Report_Entry><Employee_ID>E1</Employee_ID>"
            b"</Report_Entry></Report_Data>"
        )
        handler._http_client = _FakeHTTPClient(response=xml_body)

        df = await handler.execute(report_name="My_Report")

        assert list(df["Employee_ID"]) == ["E1"]
        call = handler._http_client.calls[0]
        assert call["accept"] == "application/xml"
        assert "format=json" not in call["url"]

    async def test_json_format_param_not_duplicated_when_explicit(self):
        handler = CustomReportType(_FakeService())
        json_body = json.dumps({"Report_Entry": [{"Employee_ID": "E1"}]})
        handler._http_client = _FakeHTTPClient(response=json_body)

        await handler.execute(report_name="My_Report", output_format="json", format="json")

        url = handler._http_client.calls[0]["url"]
        assert url.count("format=json") == 1

    async def test_unknown_output_format_falls_back_to_xml(self):
        handler = CustomReportType(_FakeService())
        xml_body = (
            b"<Report_Data><Report_Entry><Employee_ID>E1</Employee_ID>"
            b"</Report_Entry></Report_Data>"
        )
        handler._http_client = _FakeHTTPClient(response=xml_body)

        df = await handler.execute(report_name="My_Report", output_format="yaml")

        assert list(df["Employee_ID"]) == ["E1"]
        assert handler._http_client.calls[0]["accept"] == "application/xml"

    async def test_empty_json_response_returns_empty_dataframe(self):
        handler = CustomReportType(_FakeService())
        handler._http_client = _FakeHTTPClient(response=json.dumps({"Report_Entry": []}))

        df = await handler.execute(report_name="My_Report", output_format="json")

        assert isinstance(df, pd.DataFrame)
        assert df.empty
