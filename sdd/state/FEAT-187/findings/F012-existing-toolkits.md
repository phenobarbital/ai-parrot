---
id: F012
query: Q016
type: glob+grep
target: packages/ai-parrot-tools/
---

# F012 — Existing Toolkits in ai-parrot-tools

**Status**: Confirmed

## Location
`packages/ai-parrot-tools/` — import as `parrot_tools`

## Pattern
- Extend `AbstractToolkit` from `parrot.tools.toolkit`
- Methods decorated with `@tool_schema(PydanticInputModel)`
- Re-exported via `parrot_tools.toolkit`

## 40+ existing toolkits (sample)
AWS: S3, IAM, EC2, ECR, ECS, EKS, Lambda, CloudWatch, Route53, RDS, DocumentDB
Security: CloudSploit, CloudPosture, ComplianceReport, ContainerSecurity, SecretsIaC
Integrations: Jira, Git, Docker, Odoo, Office365, MSTeams, ZoomUs, Backstage, Pulumi
Data: Query, Flowtask, Quant, TechnicalAnalysis, IBKR, CompositeScore
Other: Reddit, DuckDuckGo, Code, WebScraping, Zipcode, Massive, Navigator, TROCOps

## Implication for GraphIndex
`GraphIndexToolkit` should live at `packages/ai-parrot-tools/src/parrot_tools/graphindex/`
following the same pattern: extend `AbstractToolkit`, expose async methods as tools.
