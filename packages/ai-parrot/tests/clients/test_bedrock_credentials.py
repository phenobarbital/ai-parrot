"""Unit tests for the ``aws_id`` credential resolution fix (FEAT-315, TASK-1806).

Regression coverage for the ``BedrockConverseBase.__init__`` credential
branch: reading the correct ``AWS_CREDENTIALS`` profile keys
(``aws_key``/``aws_secret``/``region_name``), falling back to the
``'default'`` profile when the named profile is missing, and always
binding the resolved credential attributes.
"""
import pytest

from parrot.clients.bedrock import BedrockConverseBase, BedrockConverseClient


@pytest.fixture
def patched_profiles(monkeypatch):
    profiles = {
        "default": {"aws_key": "DEF-K", "aws_secret": "DEF-S", "region_name": "us-east-1"},
        "monitoring": {"aws_key": "MON-K", "aws_secret": "MON-S", "region_name": "eu-west-1"},
    }
    monkeypatch.setattr("parrot.clients.bedrock.AWS_CREDENTIALS", profiles)
    return profiles


class TestAwsIdResolution:
    def test_named_profile_correct_keys(self, patched_profiles):
        c = BedrockConverseClient(aws_id="monitoring")
        assert c._aws_access_key == "MON-K"
        assert c._aws_secret_key == "MON-S"
        assert c._region == "eu-west-1"

    def test_missing_profile_falls_back_to_default(self, patched_profiles):
        c = BedrockConverseClient(aws_id="nope")
        assert c._aws_access_key == "DEF-K"

    def test_attributes_always_bound(self, patched_profiles):
        c = BedrockConverseClient(aws_id="nope")
        for attr in ("_aws_access_key", "_aws_secret_key", "_aws_session_token", "_region"):
            assert hasattr(c, attr)

    def test_subclass_surface_unchanged(self):
        assert issubclass(BedrockConverseClient, BedrockConverseBase)
        assert BedrockConverseClient.client_type == "bedrock-converse"

    def test_explicit_kwargs_take_priority_over_profile(self, patched_profiles):
        """Spec §1 Goals: explicit kwargs win over the aws_id profile."""
        c = BedrockConverseClient(
            aws_id="monitoring", aws_access_key="EXPLICIT-K", aws_secret_key="EXPLICIT-S",
        )
        assert c._aws_access_key == "EXPLICIT-K"
        assert c._aws_secret_key == "EXPLICIT-S"

    def test_alternate_key_names_tolerated(self, monkeypatch):
        """Tolerate aws_access_key_id/aws_secret_access_key, like interfaces/aws.py."""
        monkeypatch.setattr(
            "parrot.clients.bedrock.AWS_CREDENTIALS",
            {"alt": {"aws_access_key_id": "ALT-K", "aws_secret_access_key": "ALT-S"}},
        )
        c = BedrockConverseClient(aws_id="alt")
        assert c._aws_access_key == "ALT-K"
        assert c._aws_secret_key == "ALT-S"
