"""Shared fixtures for tests/forms/.

Houses fixtures used by both test_networkninja_form_service.py and
test_database_form.py (the dispatcher smoke suite).
"""

from __future__ import annotations

import json
from typing import Any

import pytest


@pytest.fixture
def sample_db_row() -> dict[str, Any]:
    """Minimal form DB result: 1 block, 3 fields (TEXT, YES_NO, FLOAT2) + 1 conditional."""
    return {
        "formid": 4,
        "form_name": "Assembly Checklist",
        "description": "Daily assembly report",
        "client_id": 1,
        "client_name": "TestClient",
        "orgid": 71,
        "question_blocks": json.dumps([
            {
                "question_block_id": 1,
                "question_block_type": "simple",
                "questions": [
                    {
                        "question_id": 84,
                        "question_column_name": 8550,
                        "question_description": "Manager name",
                        "logic_groups": [],
                        "validations": [{"validation_type": "responseRequired"}],
                    },
                    {
                        "question_id": 85,
                        "question_column_name": 8551,
                        "question_description": "Area ready?",
                        "logic_groups": [],
                        "validations": [{"validation_type": "responseRequired"}],
                    },
                    {
                        "question_id": 86,
                        "question_column_name": 8552,
                        "question_description": "Time to get ready",
                        "logic_groups": [
                            {
                                "logic_group_id": 1,
                                "conditions": [
                                    {
                                        "condition_logic": "EQUALS",
                                        "condition_comparison_value": "0",
                                        "condition_question_reference_id": 85,
                                        "condition_option_id": None,
                                    }
                                ],
                            }
                        ],
                        "validations": [{"validation_type": "responseRequired"}],
                    },
                ],
            }
        ]),
        "metadata": [
            {
                "column_id": 84,
                "column_name": "8550",
                "data_type": "FIELD_TEXT",
                "description": "Manager name",
            },
            {
                "column_id": 85,
                "column_name": "8551",
                "data_type": "FIELD_YES_NO",
                "description": "Area ready?",
            },
            {
                "column_id": 86,
                "column_name": "8552",
                "data_type": "FIELD_FLOAT2",
                "description": "Time to get ready",
            },
        ],
    }


@pytest.fixture
def sample_metadata_with_unsupported() -> list[dict[str, Any]]:
    """Metadata including an unsupported type (FIELD_SIGNATURE_CAPTURE)."""
    return [
        {
            "column_id": 272,
            "column_name": "8740",
            "data_type": "FIELD_SIGNATURE_CAPTURE",
            "description": "Signature",
        },
        {
            "column_id": 84,
            "column_name": "8550",
            "data_type": "FIELD_TEXT",
            "description": "Name",
        },
    ]
