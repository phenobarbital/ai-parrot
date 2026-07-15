---
type: Wiki Entity
title: Route53Toolkit
id: class:parrot_tools.aws.route53.Route53Toolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for managing AWS Route53 hosted zones, DNS records and health checks.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# Route53Toolkit

Defined in [`parrot_tools.aws.route53`](../summaries/mod:parrot_tools.aws.route53.md).

```python
class Route53Toolkit(AbstractToolkit)
```

Toolkit for managing AWS Route53 hosted zones, DNS records and health checks.

Each public method is exposed as a separate tool with the `aws_route53_` prefix.

Available Operations:
- aws_route53_list_hosted_zones: List hosted zones with pagination
- aws_route53_get_hosted_zone_details: Get hosted zone details
- aws_route53_list_resource_record_sets: List DNS records for a zone
- aws_route53_list_health_checks: List health checks
- aws_route53_list_traffic_policies: List traffic policies
- aws_route53_create_hosted_zone: Create a new hosted zone

Example Usage:
    toolkit = Route53Toolkit()
    tools = toolkit.get_tools()

    result = await toolkit.aws_route53_list_hosted_zones(limit=50)

## Methods

- `async def aws_route53_list_hosted_zones(self, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List Route53 hosted zones with pagination.
- `async def aws_route53_get_hosted_zone_details(self, zone_id: str) -> Dict[str, Any]` — Get details for a specific hosted zone.
- `async def aws_route53_list_resource_record_sets(self, zone_id: str, record_type: Optional[str]=None, record_name: Optional[str]=None, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List DNS records in a hosted zone with optional filtering.
- `async def aws_route53_list_health_checks(self, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List Route53 health checks with pagination.
- `async def aws_route53_list_traffic_policies(self, limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List Route53 traffic policies with pagination.
- `async def aws_route53_create_hosted_zone(self, domain_name: str, comment: Optional[str]=None, is_private: bool=False, vpc_id: Optional[str]=None, vpc_region: Optional[str]=None) -> Dict[str, Any]` — Create a new Route53 hosted zone.
