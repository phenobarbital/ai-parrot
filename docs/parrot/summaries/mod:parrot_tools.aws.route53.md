---
type: Wiki Summary
title: parrot_tools.aws.route53
id: mod:parrot_tools.aws.route53
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS Route53 Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.route53.CreateHostedZoneInput
  rel: defines
- concept: class:parrot_tools.aws.route53.GetHostedZoneDetailsInput
  rel: defines
- concept: class:parrot_tools.aws.route53.ListHealthChecksInput
  rel: defines
- concept: class:parrot_tools.aws.route53.ListHostedZonesInput
  rel: defines
- concept: class:parrot_tools.aws.route53.ListResourceRecordSetsInput
  rel: defines
- concept: class:parrot_tools.aws.route53.ListTrafficPoliciesInput
  rel: defines
- concept: class:parrot_tools.aws.route53.Route53Toolkit
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.route53`

AWS Route53 Toolkit for AI-Parrot.

Provides inspection and management of Route53 hosted zones, DNS records,
health checks and traffic policies.

## Classes

- **`ListHostedZonesInput(BaseModel)`** — Input for listing Route53 hosted zones.
- **`GetHostedZoneDetailsInput(BaseModel)`** — Input for getting hosted zone details.
- **`ListResourceRecordSetsInput(BaseModel)`** — Input for listing DNS records in a hosted zone.
- **`ListHealthChecksInput(BaseModel)`** — Input for listing Route53 health checks.
- **`ListTrafficPoliciesInput(BaseModel)`** — Input for listing Route53 traffic policies.
- **`CreateHostedZoneInput(BaseModel)`** — Input for creating a new hosted zone.
- **`Route53Toolkit(AbstractToolkit)`** — Toolkit for managing AWS Route53 hosted zones, DNS records and health checks.
