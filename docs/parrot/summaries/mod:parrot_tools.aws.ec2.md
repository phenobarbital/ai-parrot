---
type: Wiki Summary
title: parrot_tools.aws.ec2
id: mod:parrot_tools.aws.ec2
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AWS EC2 Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.ec2.DescribeInstancesInput
  rel: defines
- concept: class:parrot_tools.aws.ec2.EC2Toolkit
  rel: defines
- concept: class:parrot_tools.aws.ec2.FindPublicSecurityGroupsInput
  rel: defines
- concept: class:parrot_tools.aws.ec2.FindResourceByIPInput
  rel: defines
- concept: class:parrot_tools.aws.ec2.ListInstancesInput
  rel: defines
- concept: class:parrot_tools.aws.ec2.ListRouteTablesInput
  rel: defines
- concept: class:parrot_tools.aws.ec2.ListSecurityGroupsInput
  rel: defines
- concept: class:parrot_tools.aws.ec2.ListSubnetsInput
  rel: defines
- concept: class:parrot_tools.aws.ec2.ListVPCsInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.ec2`

AWS EC2 Toolkit for AI-Parrot.

Provides inspection of EC2 instances, security groups, VPCs, subnets,
and route tables for operations and security analysis.

## Classes

- **`ListInstancesInput(BaseModel)`** — Input for listing EC2 instances.
- **`DescribeInstancesInput(BaseModel)`** — Input for describing specific EC2 instances.
- **`ListSecurityGroupsInput(BaseModel)`** — Input for listing EC2 security groups.
- **`FindPublicSecurityGroupsInput(BaseModel)`** — Input for finding security groups with public access.
- **`ListVPCsInput(BaseModel)`** — Input for listing VPCs.
- **`ListSubnetsInput(BaseModel)`** — Input for listing subnets.
- **`ListRouteTablesInput(BaseModel)`** — Input for listing route tables.
- **`FindResourceByIPInput(BaseModel)`** — Input for finding AWS resources by IP address.
- **`EC2Toolkit(AbstractToolkit)`** — Toolkit for inspecting AWS EC2 instances, security groups, and networking.
