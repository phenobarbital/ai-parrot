"""wd_get_position / wd_get_job_profile — request shape, parsing and WSDL routing."""
import json

import pytest
from zeep.exceptions import Fault

from parrot.conf import WORKDAY_WSDL_HUMAN_RESOURCES, WORKDAY_WSDL_STAFFING
from parrot_tools.interfaces.workday.config import get_wsdl_path
from parrot_tools.workday.tool import WorkdayToolkit


def _ref(**ids):
    return {"ID": [{"type": t, "_value_1": v} for t, v in ids.items()], "Descriptor": None}


POSITION_RESPONSE = {
    "Response_Data": [
        {
            "Position": [
                {
                    "Position_Reference": _ref(WID="pos-wid", Position_ID="P105294"),
                    "Position_Data": {
                        "Supervisory_Organization_Reference": _ref(WID="org-wid", Organization_Reference_ID="SO100074"),
                        "Effective_Date": "2026-10-12",
                        "Position_Definition_Data": {
                            "Position_ID": "P105294",
                            "Job_Posting_Title": "Territory Field Lead",
                            "Job_Description": "<p>Senior</p>",
                            "Available_For_Hire": False,
                            "Available_for_Recruiting": False,
                            "Hiring_Freeze": False,
                            "Critical_Job": False,
                        },
                        "Position_Restrictions_Data": {
                            "Availability_Date": "2026-09-02",
                            "Earliest_Hire_Date": "2026-09-21",
                            "Job_Family_Reference": [_ref(WID="f", Job_Family_ID="JOB_FAMILY-3-63")],
                            "Job_Profile_Restriction_Summary_Data": [
                                {
                                    "Job_Profile_Reference": _ref(WID="jp", Job_Profile_ID="STFLV"),
                                    "Job_Profile_Name": "Senior Territory Field Lead",
                                    "Management_Level_Reference": _ref(Management_Level_ID="Individual_Contributor"),
                                    "Job_Family_Reference": [_ref(Job_Family_ID="Brand_Division")],
                                }
                            ],
                        },
                        "Default_Position_Organization_Assignments_Data": {
                            "Company_Assignments_Reference": [_ref(Company_Reference_ID="BBE")],
                            "Cost_Center_Assignments_Reference": [_ref(Cost_Center_Reference_ID="COST_CENTER-3-924")],
                        },
                        "Worker_For_Filled_Position": {
                            "Worker_Reference": _ref(WID="w-wid", Employee_ID="T0000005001147"),
                        },
                        "Qualification_Data": {
                            "Competency_Data": [
                                {
                                    "Competency_Profile_Data": {
                                        "Competency_Reference": _ref(Competency_ID="Integrity"),
                                        "Required": False,
                                    }
                                }
                            ]
                        },
                        "Closed": False,
                    },
                }
            ]
        }
    ]
}

JOB_PROFILE_RESPONSE = {
    "Response_Data": {
        "Job_Profile": [
            {
                "Job_Profile_Reference": _ref(WID="jp-wid", Job_Profile_ID="TFLV"),
                "Job_Profile_Data": {
                    "Job_Profile_Reference": "TFLV",
                    "Job_Profile_Request_Data": {
                        "Job_Code": "TFLV",
                        "Effective_Date": "2026-10-16",
                        "Job_Profile_Basic_Data": [
                            {
                                "Job_Title": "Territory Field Lead",
                                "Job_Description": "<p>TFL</p>",
                                "Inactive": False,
                                "Public_Job": False,
                                "Management_Level_Reference": _ref(Management_Level_ID="Individual_Contributor"),
                                "Job_Family_Data": [{"Job_Family_Reference": _ref(Job_Family_ID="Brand_Division")}],
                            }
                        ],
                        "Job_Classification_Data": [
                            {"Job_Classifications_Reference": _ref(Job_Classification_Reference_ID="Laptop")}
                        ],
                        "Job_Profile_Pay_Rate_Data": [
                            {
                                "Country_Reference": _ref(**{"ISO_3166-1_Alpha-2_Code": "CA"}),
                                "Pay_Rate_Type_Reference": _ref(Pay_Rate_Type_ID="Salary"),
                            }
                        ],
                        "Job_Profile_Exempt_Data": [
                            {
                                "Location_Context_Reference": _ref(**{"ISO_3166-1_Alpha-2_Code": "US"}),
                                "Job_Exempt": True,
                            }
                        ],
                        "Workers_Compensation_Code_Replacement_Data": [
                            {"Workers_Compensation_Code_Reference": _ref(Workers_Compensation_ID="USA_8742")}
                        ],
                        "Qualification_Replacement_Data": {
                            "Skill_Qualification_Replacement": {
                                "Skill_Qualification_Replacement_Data": [
                                    {
                                        "Skill_Reference": _ref(Remote_Skill_ID="REMOTE_SKILL-1-77522"),
                                        "Name": "Sales Support",
                                        "Required": False,
                                    }
                                ]
                            }
                        },
                        "Job_Profile_Compensation_Data": [
                            {
                                "Compensation_Grade_Reference": _ref(Compensation_Grade_ID="E80"),
                                "Compensation_Grade_Profile_Reference": [_ref(Compensation_Grade_Profile_ID="E80_GEO3")],
                            }
                        ],
                    },
                },
            }
        ]
    }
}


class _FakeComposable:
    def __init__(self, response=None, fault=None):
        self.response = response
        self.fault = fault
        self.calls = []
        self.requested_ops = []

    async def call_operation(self, operation, **request):
        self.calls.append((operation, request))
        if self.fault:
            raise Fault(self.fault)
        return self.response

    def serialize_object(self, obj):
        return obj


def _toolkit(monkeypatch, fake):
    tk = WorkdayToolkit()
    tk._initialized = True

    async def fake_get_composable(self, operation_type):
        fake.requested_ops.append(operation_type)
        return fake

    monkeypatch.setattr(WorkdayToolkit, "_get_composable", fake_get_composable)
    return tk


def test_wsdl_routing():
    assert get_wsdl_path("get_positions") == WORKDAY_WSDL_STAFFING
    assert get_wsdl_path("get_job_profiles") == WORKDAY_WSDL_HUMAN_RESOURCES


def test_tools_are_exposed():
    names = {t.name for t in WorkdayToolkit().get_tools()}
    assert {"wd_get_position", "wd_get_job_profile"} <= names


@pytest.mark.asyncio
async def test_get_position_request_and_parse(monkeypatch):
    fake = _FakeComposable(POSITION_RESPONSE)
    tk = _toolkit(monkeypatch, fake)

    res = await tk.wd_get_position("P105294")

    assert fake.requested_ops == ["get_positions"]
    op, request = fake.calls[0]
    assert op == "Get_Positions"
    assert request["Request_References"]["Positions_Reference"][0]["ID"][0] == {
        "type": "Position_ID",
        "_value_1": "P105294",
    }
    assert request["Request_Criteria"] == {"Include_Closed_Positions": True}

    assert res["position_id"] == "P105294"
    assert res["position_wid"] == "pos-wid"
    assert res["job_posting_title"] == "Territory Field Lead"
    assert res["closed"] is False
    assert res["supervisory_organization_id"] == "SO100074"
    assert res["job_profiles"] == [
        {
            "job_profile_id": "STFLV",
            "job_profile_name": "Senior Territory Field Lead",
            "management_level": "Individual_Contributor",
            "job_families": ["Brand_Division"],
        }
    ]
    assert res["job_family_ids"] == ["JOB_FAMILY-3-63"]
    assert res["company_ids"] == ["BBE"]
    assert res["cost_center_ids"] == ["COST_CENTER-3-924"]
    assert res["worker_id"] == "T0000005001147"
    assert res["worker_wid"] == "w-wid"
    assert res["competencies"] == [{"competency": "Integrity", "required": False}]
    json.dumps(res)


@pytest.mark.asyncio
async def test_get_position_exclude_closed(monkeypatch):
    fake = _FakeComposable({"Response_Data": []})
    tk = _toolkit(monkeypatch, fake)

    assert await tk.wd_get_position("P104596", include_closed=False) == {}
    assert fake.calls[0][1]["Request_Criteria"] == {"Include_Closed_Positions": False}


@pytest.mark.asyncio
async def test_get_job_profile_request_and_parse(monkeypatch):
    fake = _FakeComposable(JOB_PROFILE_RESPONSE)
    tk = _toolkit(monkeypatch, fake)

    res = await tk.wd_get_job_profile("TFLV")

    assert fake.requested_ops == ["get_job_profiles"]
    op, request = fake.calls[0]
    assert op == "Get_Job_Profiles"
    assert request["Request_References"]["Job_Profile_Reference"][0]["ID"][0] == {
        "type": "Job_Profile_ID",
        "_value_1": "TFLV",
    }

    assert res["job_profile_id"] == "TFLV"
    assert res["job_profile_wid"] == "jp-wid"
    assert res["job_title"] == "Territory Field Lead"
    assert res["management_level"] == "Individual_Contributor"
    assert res["job_families"] == ["Brand_Division"]
    assert res["job_classifications"] == ["Laptop"]
    assert res["pay_rate_types"] == [{"country": "CA", "pay_rate_type": "Salary"}]
    assert res["exempt"] == [{"country": "US", "job_exempt": True}]
    assert res["compensation_grade"] == "E80"
    assert res["compensation_grade_profiles"] == ["E80_GEO3"]
    assert res["workers_compensation_codes"] == ["USA_8742"]
    assert res["skills"] == [{"skill_id": "REMOTE_SKILL-1-77522", "name": "Sales Support", "required": False}]
    json.dumps(res)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,arg", [("wd_get_position", "P000"), ("wd_get_job_profile", "NOPE")])
async def test_unknown_id_returns_empty(monkeypatch, method, arg):
    fake = _FakeComposable(fault="Validation error occurred. Invalid ID value.  'X' is not a valid ID value")
    tk = _toolkit(monkeypatch, fake)

    assert await getattr(tk, method)(arg) == {}


@pytest.mark.asyncio
async def test_other_faults_propagate(monkeypatch):
    fake = _FakeComposable(fault="Processing error occurred.")
    tk = _toolkit(monkeypatch, fake)

    with pytest.raises(Fault):
        await tk.wd_get_position("P105294")
