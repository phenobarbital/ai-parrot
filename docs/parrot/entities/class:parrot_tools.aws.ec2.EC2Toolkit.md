---
type: Wiki Entity
title: EC2Toolkit
id: class:parrot_tools.aws.ec2.EC2Toolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for inspecting AWS EC2 instances, security groups, and networking.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# EC2Toolkit

Defined in [`parrot_tools.aws.ec2`](../summaries/mod:parrot_tools.aws.ec2.md).

```python
class EC2Toolkit(AbstractToolkit)
```

Toolkit for inspecting AWS EC2 instances, security groups, and networking.

Available Operations:
- aws_ec2_list_instances: List instances with filters
- aws_ec2_describe_instances: Describe specific instances
- aws_ec2_list_security_groups: List security groups
- aws_ec2_find_public_security_groups: Find SGs with 0.0.0.0/0 rules
- aws_ec2_list_vpcs: List VPCs
- aws_ec2_list_subnets: List subnets
- aws_ec2_list_route_tables: List route tables
- aws_ec2_find_resource_by_ip: Find resources by IP

## Methods

- `async def aws_ec2_list_instances(self, state: str='running', limit: int=100, next_token: Optional[str]=None) -> Dict[str, Any]` — List EC2 instances with optional state filter.
- `async def aws_ec2_describe_instances(self, instance_ids: List[str]) -> Dict[str, Any]` — Describe specific EC2 instances by ID.
- `async def aws_ec2_list_security_groups(self, limit: int=100, vpc_id: Optional[str]=None, next_token: Optional[str]=None) -> Dict[str, Any]` — List EC2 security groups.
- `async def aws_ec2_find_public_security_groups(self, port: Optional[int]=None) -> Dict[str, Any]` — Find security groups with public internet access (0.0.0.0/0).
- `async def aws_ec2_list_vpcs(self, limit: int=50) -> Dict[str, Any]` — List VPCs in the account.
- `async def aws_ec2_list_subnets(self, vpc_id: Optional[str]=None, limit: int=100) -> Dict[str, Any]` — List subnets, optionally filtered by VPC.
- `async def aws_ec2_list_route_tables(self, vpc_id: Optional[str]=None, limit: int=100) -> Dict[str, Any]` — List route tables, optionally filtered by VPC.
- `async def aws_ec2_find_resource_by_ip(self, ip_address: str) -> Dict[str, Any]` — Find AWS resources associated with a specific IP address.
