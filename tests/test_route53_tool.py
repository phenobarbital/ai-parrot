"""Test suite for Route53Toolkit."""
import pytest
from unittest.mock import AsyncMock, patch
from contextlib import asynccontextmanager

from parrot.tools.aws.route53 import (
    Route53Toolkit,
    ListHostedZonesInput,
    GetHostedZoneDetailsInput,
    ListResourceRecordSetsInput,
    ListHealthChecksInput,
    ListTrafficPoliciesInput,
    CreateHostedZoneInput,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_r53_client(**method_responses):
    """Build an AsyncMock that behaves like an aioboto3 Route53 client."""
    mock_client = AsyncMock()
    for method_name, response in method_responses.items():
        getattr(mock_client, method_name).return_value = response
    return mock_client


@asynccontextmanager
async def _mock_client_ctx(mock_client):
    """Async context-manager that yields the mock client."""
    yield mock_client


@pytest.fixture
def route53_toolkit():
    """Create a Route53Toolkit with a mocked AWSInterface."""
    with patch("parrot.tools.aws.route53.AWSInterface"):
        toolkit = Route53Toolkit()
    return toolkit


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestRoute53Schemas:
    """Validate Pydantic input schemas."""

    def test_list_hosted_zones_defaults(self):
        schema = ListHostedZonesInput()
        assert schema.limit == 100
        assert schema.next_token is None

    def test_get_hosted_zone_details_required(self):
        with pytest.raises(ValueError):
            GetHostedZoneDetailsInput()

    def test_list_resource_record_sets_with_filters(self):
        schema = ListResourceRecordSetsInput(
            zone_id="Z111", record_type="A", record_name="api.example.com"
        )
        assert schema.zone_id == "Z111"
        assert schema.record_type == "A"

    def test_create_hosted_zone_required(self):
        with pytest.raises(ValueError):
            CreateHostedZoneInput()

    def test_create_hosted_zone_defaults(self):
        schema = CreateHostedZoneInput(domain_name="example.com")
        assert schema.domain_name == "example.com"
        assert schema.is_private is False
        assert schema.vpc_id is None


# ---------------------------------------------------------------------------
# Toolkit tests
# ---------------------------------------------------------------------------


class TestRoute53Toolkit:
    """Test Route53Toolkit functionality."""

    def test_toolkit_initialization(self, route53_toolkit):
        assert isinstance(route53_toolkit, Route53Toolkit)

    def test_get_tools(self, route53_toolkit):
        tools = route53_toolkit.get_tools()
        tool_names = [t.name for t in tools]

        assert "aws_route53_list_hosted_zones" in tool_names
        assert "aws_route53_get_hosted_zone_details" in tool_names
        assert "aws_route53_list_resource_record_sets" in tool_names
        assert "aws_route53_list_health_checks" in tool_names
        assert "aws_route53_list_traffic_policies" in tool_names
        assert "aws_route53_create_hosted_zone" in tool_names

    def test_tools_have_schema(self, route53_toolkit):
        """Verify that tools pick up the @tool_schema decorator."""
        tools = route53_toolkit.get_tools()
        schemas = {t.name: t.args_schema for t in tools}

        assert schemas["aws_route53_list_hosted_zones"] is ListHostedZonesInput
        assert schemas["aws_route53_get_hosted_zone_details"] is GetHostedZoneDetailsInput
        assert schemas["aws_route53_create_hosted_zone"] is CreateHostedZoneInput

    # ------------------------------------------------------------------
    # aws_route53_list_hosted_zones
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_hosted_zones(self, route53_toolkit):
        mock_response = {
            "HostedZones": [
                {
                    "Id": "/hostedzone/Z111",
                    "Name": "example.com.",
                    "CallerReference": "ref1",
                    "Config": {"PrivateZone": False},
                    "ResourceRecordSetCount": 5,
                },
            ],
            "IsTruncated": False,
        }
        mock_client = _make_mock_r53_client(list_hosted_zones=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_hosted_zones()

        assert result["count"] == 1
        assert result["zones"][0]["Name"] == "example.com."
        assert result["is_truncated"] is False

    @pytest.mark.asyncio
    async def test_list_hosted_zones_with_pagination(self, route53_toolkit):
        mock_response = {
            "HostedZones": [{"Id": "/hostedzone/Z111", "Name": "a.com."}],
            "IsTruncated": True,
            "NextMarker": "Z222",
        }
        mock_client = _make_mock_r53_client(list_hosted_zones=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_hosted_zones(
            next_token="Z000"
        )

        assert result["is_truncated"] is True
        assert result["next_token"] == "Z222"
        mock_client.list_hosted_zones.assert_awaited_once_with(
            MaxItems="100", Marker="Z000"
        )

    # ------------------------------------------------------------------
    # aws_route53_get_hosted_zone_details
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_hosted_zone_details(self, route53_toolkit):
        mock_response = {
            "HostedZone": {
                "Id": "/hostedzone/Z111",
                "Name": "example.com.",
                "Config": {"PrivateZone": False},
                "ResourceRecordSetCount": 8,
            },
            "DelegationSet": {
                "NameServers": [
                    "ns-1.awsdns-01.com",
                    "ns-2.awsdns-02.net",
                ],
            },
            "VPCs": [],
        }
        mock_client = _make_mock_r53_client(get_hosted_zone=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_get_hosted_zone_details(
            zone_id="Z111"
        )

        assert result["record_count"] == 8
        assert result["is_private"] is False
        assert len(result["delegation_set"]["NameServers"]) == 2

    # ------------------------------------------------------------------
    # aws_route53_list_resource_record_sets
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_resource_record_sets(self, route53_toolkit):
        mock_response = {
            "ResourceRecordSets": [
                {
                    "Name": "example.com.",
                    "Type": "A",
                    "TTL": 300,
                    "ResourceRecords": [{"Value": "1.2.3.4"}],
                },
                {
                    "Name": "example.com.",
                    "Type": "NS",
                    "TTL": 172800,
                    "ResourceRecords": [{"Value": "ns-1.awsdns-01.com."}],
                },
            ],
            "IsTruncated": False,
        }
        mock_client = _make_mock_r53_client(
            list_resource_record_sets=mock_response
        )
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_resource_record_sets(
            zone_id="Z111"
        )

        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_list_resource_record_sets_filter_type(self, route53_toolkit):
        mock_response = {
            "ResourceRecordSets": [
                {"Name": "example.com.", "Type": "A", "TTL": 300,
                 "ResourceRecords": [{"Value": "1.2.3.4"}]},
                {"Name": "example.com.", "Type": "NS", "TTL": 172800,
                 "ResourceRecords": [{"Value": "ns-1.awsdns-01.com."}]},
                {"Name": "mail.example.com.", "Type": "A", "TTL": 300,
                 "ResourceRecords": [{"Value": "5.6.7.8"}]},
            ],
            "IsTruncated": False,
        }
        mock_client = _make_mock_r53_client(
            list_resource_record_sets=mock_response
        )
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_resource_record_sets(
            zone_id="Z111", record_type="A"
        )

        assert result["count"] == 2
        assert all(r["Type"] == "A" for r in result["records"])

    @pytest.mark.asyncio
    async def test_list_resource_record_sets_filter_name(self, route53_toolkit):
        mock_response = {
            "ResourceRecordSets": [
                {"Name": "example.com.", "Type": "A", "TTL": 300,
                 "ResourceRecords": [{"Value": "1.2.3.4"}]},
                {"Name": "api.example.com.", "Type": "A", "TTL": 300,
                 "ResourceRecords": [{"Value": "5.6.7.8"}]},
            ],
            "IsTruncated": False,
        }
        mock_client = _make_mock_r53_client(
            list_resource_record_sets=mock_response
        )
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_resource_record_sets(
            zone_id="Z111", record_name="api.example.com"
        )

        assert result["count"] == 1
        assert result["records"][0]["Name"] == "api.example.com."

    @pytest.mark.asyncio
    async def test_list_resource_record_sets_pagination(self, route53_toolkit):
        mock_response = {
            "ResourceRecordSets": [
                {"Name": "a.example.com.", "Type": "A", "TTL": 300,
                 "ResourceRecords": [{"Value": "1.2.3.4"}]},
            ],
            "IsTruncated": True,
            "NextRecordName": "b.example.com.",
            "NextRecordType": "A",
        }
        mock_client = _make_mock_r53_client(
            list_resource_record_sets=mock_response
        )
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_resource_record_sets(
            zone_id="Z111"
        )

        assert result["is_truncated"] is True
        assert result["next_token"] == "b.example.com.|A"

    # ------------------------------------------------------------------
    # aws_route53_list_health_checks
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_health_checks(self, route53_toolkit):
        mock_response = {
            "HealthChecks": [
                {
                    "Id": "hc-111",
                    "HealthCheckConfig": {
                        "IPAddress": "1.2.3.4",
                        "Port": 443,
                        "Type": "HTTPS",
                    },
                },
            ],
            "IsTruncated": False,
        }
        mock_client = _make_mock_r53_client(list_health_checks=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_health_checks()

        assert result["count"] == 1
        assert result["health_checks"][0]["Id"] == "hc-111"

    # ------------------------------------------------------------------
    # aws_route53_list_traffic_policies
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_traffic_policies(self, route53_toolkit):
        mock_response = {
            "TrafficPolicySummaries": [
                {
                    "Id": "tp-111",
                    "Name": "my-policy",
                    "Type": "A",
                    "LatestVersion": 1,
                    "TrafficPolicyCount": 1,
                },
            ],
            "IsTruncated": False,
        }
        mock_client = _make_mock_r53_client(list_traffic_policies=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_traffic_policies()

        assert result["count"] == 1
        assert result["policies"][0]["Name"] == "my-policy"

    @pytest.mark.asyncio
    async def test_list_traffic_policies_pagination(self, route53_toolkit):
        mock_response = {
            "TrafficPolicySummaries": [
                {"Id": "tp-111", "Name": "p1", "Type": "A",
                 "LatestVersion": 1, "TrafficPolicyCount": 1},
            ],
            "IsTruncated": True,
            "TrafficPolicyIdMarker": "tp-222",
        }
        mock_client = _make_mock_r53_client(list_traffic_policies=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_list_traffic_policies(
            next_token="tp-000"
        )

        assert result["is_truncated"] is True
        assert result["next_token"] == "tp-222"
        mock_client.list_traffic_policies.assert_awaited_once_with(
            MaxItems="100", TrafficPolicyIdMarker="tp-000"
        )

    # ------------------------------------------------------------------
    # aws_route53_create_hosted_zone
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_hosted_zone(self, route53_toolkit):
        mock_response = {
            "HostedZone": {
                "Id": "/hostedzone/Z999",
                "Name": "newdomain.com.",
                "CallerReference": "some-uuid",
                "Config": {"PrivateZone": False},
                "ResourceRecordSetCount": 2,
            },
            "DelegationSet": {
                "NameServers": [
                    "ns-1.awsdns-01.com",
                    "ns-2.awsdns-02.net",
                ],
            },
            "ChangeInfo": {
                "Id": "/change/C111",
                "Status": "PENDING",
            },
        }
        mock_client = _make_mock_r53_client(create_hosted_zone=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_create_hosted_zone(
            domain_name="newdomain.com", comment="Test zone"
        )

        assert result["zone_id"] == "/hostedzone/Z999"
        assert len(result["name_servers"]) == 2
        assert result["change_info"]["Status"] == "PENDING"

        # Verify the call params
        call_kwargs = mock_client.create_hosted_zone.call_args[1]
        assert call_kwargs["Name"] == "newdomain.com"
        assert call_kwargs["HostedZoneConfig"]["Comment"] == "Test zone"
        assert call_kwargs["HostedZoneConfig"]["PrivateZone"] is False

    @pytest.mark.asyncio
    async def test_create_private_hosted_zone_requires_vpc(self, route53_toolkit):
        mock_client = _make_mock_r53_client()
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        with pytest.raises(ValueError, match="vpc_id is required"):
            await route53_toolkit.aws_route53_create_hosted_zone(
                domain_name="private.example.com", is_private=True
            )

    @pytest.mark.asyncio
    async def test_create_private_hosted_zone(self, route53_toolkit):
        mock_response = {
            "HostedZone": {
                "Id": "/hostedzone/Z888",
                "Name": "private.example.com.",
                "Config": {"PrivateZone": True},
                "ResourceRecordSetCount": 2,
            },
            "DelegationSet": {"NameServers": []},
            "ChangeInfo": {"Id": "/change/C222", "Status": "PENDING"},
        }
        mock_client = _make_mock_r53_client(create_hosted_zone=mock_response)
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(mock_client)

        result = await route53_toolkit.aws_route53_create_hosted_zone(
            domain_name="private.example.com",
            is_private=True,
            vpc_id="vpc-123",
            vpc_region="us-east-1",
        )

        assert result["zone_id"] == "/hostedzone/Z888"
        call_kwargs = mock_client.create_hosted_zone.call_args[1]
        assert call_kwargs["VPC"]["VPCId"] == "vpc-123"
        assert call_kwargs["VPC"]["VPCRegion"] == "us-east-1"
        assert call_kwargs["HostedZoneConfig"]["PrivateZone"] is True

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_client_error_handling(self, route53_toolkit):
        from botocore.exceptions import ClientError

        error_response = {
            "Error": {"Code": "AccessDenied", "Message": "forbidden"}
        }
        mock_client = AsyncMock()
        mock_client.list_hosted_zones.side_effect = ClientError(
            error_response, "ListHostedZones"
        )
        route53_toolkit.aws.client = lambda svc, **kw: _mock_client_ctx(
            mock_client
        )

        with pytest.raises(RuntimeError) as exc_info:
            await route53_toolkit.aws_route53_list_hosted_zones()

        assert "AccessDenied" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
