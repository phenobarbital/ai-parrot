---
type: Wiki Overview
title: 3. Toolkits for third-party services and Cloud-Security composition
id: doc:docs-architecture-03-toolkits-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This chapter is a curated catalogue of toolkits in
relates_to:
- concept: mod:parrot.mcp.server
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# 3. Toolkits for third-party services and Cloud-Security composition

> Part of the [Exposure, Interoperability & Hardening](README.md) set.
> Previous: [A2A](02-a2a.md) · Next: [Interaction surface](04-interaction-surface.md)

This chapter is a curated catalogue of toolkits in
`packages/ai-parrot-tools/src/parrot_tools/` that are most useful as
**building blocks for vendor-specific MCP servers** or for composing
domain agents (e.g. cloud-security audit, ERP integration, finance
research). Every toolkit inherits from `AbstractToolkit`
(`parrot_tools/toolkit.py`); each public async method automatically
becomes an agent tool through introspection — meaning a single
`MCPServer(toolkit=...)` line yields a fully functional MCP service.

## 3.1 Composition map

```mermaid
graph LR
    subgraph Base["Base abstractions"]
        Abs["AbstractTool · ToolResult<br/>parrot_tools/abstract.py"]
        Tk["AbstractToolkit<br/>parrot_tools/toolkit.py"]
    end

    subgraph Enterprise["Enterprise SaaS"]
        Jira["JiraToolkit"]
        Odoo["OdooToolkit"]
        Workday["WorkdayToolkit"]
        Backstage["BackstageCatalogToolkit"]
        O365["SharePoint · OneDrive · Mail"]
        Teams["MSTeamsToolkit"]
        Google["Google Suite tools"]
    end

    subgraph Cloud["AWS"]
        S3["S3Toolkit"]
        IAM["IAMToolkit"]
        EC2["EC2Toolkit"]
        ECS["ECSToolkit"]
        EKS["EKSToolkit"]
        CW["CloudWatchToolkit"]
        Lambda["LambdaToolkit"]
        ECR["ECRToolkit"]
        Route53["Route53Toolkit"]
        RDS["RDSToolkit"]
        DDB["DocumentDBToolkit"]
        GD["GuardDutyToolkit"]
        SH["SecurityHubToolkit"]
    end

    subgraph Sec["Cloud-Security composition"]
        CloudSploit["CloudSploitToolkit"]
        Posture["CloudPostureToolkit<br/>(Prowler)"]
        Container["ContainerSecurityToolkit<br/>(Trivy)"]
        IaC["SecretsIaCToolkit<br/>(Checkov)"]
        Compliance["ComplianceReportToolkit<br/>multi-scanner aggregator"]
    end

    subgraph Data["Data & DBs"]
        DBQ["DatabaseQueryTool"]
        Multi["MultiTierSchemaCaching"]
        ES["ElasticsearchTool"]
        Arango["ArangoDBSearchTool"]
        DM["DatasetManager"]
    end

    subgraph Code["Code execution"]
        CI["CodeInterpreterTool"]
        Shell["ShellTool"]
        Sandbox["SandboxTool (gVisor)"]
        Docker["DockerToolkit"]
        Pulumi["PulumiToolkit"]
    end

    subgraph Web["Web & search"]
        Scrape["WebScrapingToolkit"]
        Site["SiteSearchToolkit"]
        Serp["SerpApiSearchTool"]
        Bing["BingSearchTool"]
        DDG["DuckDuckGoSearchTool"]
    end

    subgraph Finance["Finance / quant"]
        Quant["QuantToolkit"]
        Bloom["BloombergTool"]
        IBKR["IBKR toolkit"]
        YF["YFinanceTool"]
        FRED["FredApiTool"]
        Massive["MassiveToolkit"]
    end

    subgraph Docs["Documents"]
        PDF["PDFPrintTool"]
        Word["MSWordTool"]
        Excel["ExcelTool"]
        PPT["PowerPointTool"]
        FR["FileReaderTool"]
    end

    subgraph Output["Exposure"]
        MCP["MCP Server<br/>(any transport)"]
        A2A["A2A Server"]
        Agent["Agent / Crew"]
    end

    Abs --> Tk
    Tk --> Enterprise
    Tk --> Cloud
    Tk --> Sec
    Tk --> Data
    Tk --> Code
    Tk --> Web
    Tk --> Finance
    Tk --> Docs

    Cloud -. feeds .-> Sec
    Sec --> Compliance

    Enterprise --> MCP
    Enterprise --> A2A
    Enterprise --> Agent
    Cloud --> MCP
    Sec --> MCP
    Data --> Agent
    Code --> Agent
    Web --> Agent
    Finance --> Agent
    Docs --> Agent

    classDef base fill:#fff3e0,stroke:#ef6c00;
    classDef sec  fill:#fce4ec,stroke:#c2185b;
    classDef cld  fill:#e3f2fd,stroke:#1976d2;
    classDef out  fill:#e8f5e9,stroke:#2e7d32;
    class Abs,Tk base;
    class CloudSploit,Posture,Container,IaC,Compliance sec;
    class S3,IAM,EC2,ECS,EKS,CW,Lambda,ECR,Route53,RDS,DDB,GD,SH cld;
    class MCP,A2A,Agent out;
```

## 3.2 Atlassian / Jira

- `jiratoolkit.py` → **`JiraToolkit`** — issues, projects, transitions
  over basic / token / OAuth1 auth.
- `parrot/auth/jira_oauth.py:86` → **`JiraOAuthManager`** — Atlassian
  3LO with CSRF nonce, distributed token-refresh lock, cloud-id
  discovery, Redis-backed per-user token storage.

Recommended composition: `MCPServer(transport="sse", auth="oauth2_external")`
+ `JiraToolkit` → drop-in Atlassian MCP server.

## 3.3 Odoo ERP

- `odoo/toolkit.py` → **`OdooToolkit`** — Odoo 14–19+, JSON-2 / XML-RPC
  auto-detection, bulk CRUD, external-id upsert via `import_records`,
  binary upload helper.

## 3.4 AWS — service-by-service

| Toolkit                      | Class                  | Surface                                                  |
|------------------------------|------------------------|----------------------------------------------------------|
| `aws/s3.py`                  | `S3Toolkit`            | Buckets, ACL/policy, encryption, public-access analysis. |
| `aws/iam.py`                 | `IAMToolkit`           | Roles, users, policies, key audit, priv-esc detection.   |
| `aws/ec2.py`                 | `EC2Toolkit`           | Instance lifecycle, SGs, ENIs.                           |
| `aws/ecs.py`                 | `ECSToolkit`           | Clusters, services, tasks.                               |
| `aws/eks.py`                 | `EKSToolkit`           | EKS provisioning + management.                           |
| `aws/cloudwatch.py`          | `CloudWatchToolkit`    | Logs, metrics, alarms.                                   |
| `aws/route53.py`             | `Route53Toolkit`       | DNS records, health checks.                              |
| `aws/rds.py`                 | `RDSToolkit`           | Instances, snapshots, backups.                           |
| `aws/documentdb.py`          | `DocumentDBToolkit`    | DocumentDB management.                                   |
| `aws/lambda_func.py`         | `LambdaToolkit`        | Functions, versions, aliases.                            |
| `aws/ecr.py`                 | `ECRToolkit`           | Image registry + lifecycle.                              |
| `aws/guardduty.py`           | `GuardDutyToolkit`     | Threat findings + remediation.                           |
| `aws/securityhub.py`         | `SecurityHubToolkit`   | Aggregated findings + posture.                           |

## 3.5 Cloud Security composition

The Cloud-Security pattern is the strongest illustration of toolkit
composition. The five toolkits below cover scanning, IaC linting,
container image analysis, and unified compliance reporting:

| Toolkit                                         | Class                       | Engines                                  |
|-------------------------------------------------|-----------------------------|------------------------------------------|
| `cloudsploit/toolkit.py`                        | `CloudSploitToolkit`        | CloudSploit scanner orchestration.       |
| `security/cloud_posture_toolkit.py`             | `CloudPostureToolkit`       | Prowler (AWS / Azure / GCP / K8s).       |
| `security/container_security_toolkit.py`        | `ContainerSecurityToolkit`  | Trivy (images, FS, git, K8s, IaC).       |
| `security/secrets_iac_toolkit.py`               | `SecretsIaCToolkit`         | Checkov (Terraform, CFN, K8s, Helm…).    |
| `security/compliance_report_toolkit.py`         | `ComplianceReportToolkit`   | Multi-scanner aggregation + framework mapping. |

A cloud-security agent is built by registering all five plus the
relevant `aws/*` toolkits, exposing the composite as an MCP server, and
gating the destructive actions through PBAC
([chapter 5](05-hardening.md#54-tool-and-resource-access-control)).

## 3.6 Microsoft 365 and Google

- **MS Teams**: `msteams.py` → `MSTeamsToolkit` (messages, adaptive
  cards, meetings via Graph API).
- **O365 / SharePoint / OneDrive**: `o365/bundle.py` → `SharePointToolkit`,
  `OneDriveToolkit`, `o365/mail.py`.
- **Google**: `googlesearch.py`, `googlelocation.py`, `googleroutes.py`,
  `googlesitesearch.py`, `googlevoice.py`, all sharing
  `google/base.py:GoogleToolArgsSchema` + `GoogleAuthMode` (service
  account / user / cached).

## 3.7 Database & data

- `database/` + `databasequery.py` → `DatabaseQueryTool` (multi-DB SQL).
- `multidb.py` → `MultiTierSchemaCaching` (in-memory → vector → live).
- `elasticsearch.py`, `arangodbsearch.py`, `querytoolkit.py`.
- `dataset_manager/` → multi-source dataset loading.

## 3.8 Code execution and sandboxing

- `codeinterpreter/tool.py` → `CodeInterpreterTool` (analysis, doc-gen,
  test generation).
- `shell_tool/tool.py` → `ShellTool` — interactive PTY shell with
  plan-mode DAG + parallel command orchestration.
- `sandboxtool.py` → `SandboxTool` — gVisor (`runsc`) kernel-level
  isolation for LLM-generated code.
- `docker/toolkit.py` → `DockerToolkit` (container lifecycle + Compose).
- `pulumi/toolkit.py` → `PulumiToolkit` (IaC plan / apply / destroy).

## 3.9 Web & scraping

- `scraping/toolkit.py` → `WebScrapingToolkit` (Playwright/Selenium with
  AI-driven extraction).
- `sitesearch/toolkit.py`, `webapp_tool.py`, `serpapi.py`,
  `bingsearch.py`, `googlesearch.py`, `ddgsearch.py`.

## 3.10 Messaging, finance, HR and documents

| Domain         | Toolkits                                                                                                    |
|----------------|-------------------------------------------------------------------------------------------------------------|
| Messaging      | `messaging/whatsapp.py`, `notification.py`, `zoomtoolkit.py`.                                               |
| HR / ERP       | `workday/tool.py` (`WorkdayToolkit`, OAuth2 + Redis cache, multi-WSDL).                                     |
| Finance        | `quant/toolkit.py` (`QuantToolkit`), `bloomberg.py`, `ibkr/`, `yfinance.py`, `fred_api.py`, `massive/`.      |
| Documents      | `pdfprint.py`, `msword.py`, `excel.py`, `powerpoint.py`, `doc_converter.py`, `file/`, `file_reader.py`.     |
| DevTools       | `gittoolkit.py` (`GitToolkit`), `backstage/toolkit.py` (`BackstageCatalogToolkit`), `flowtask/tool.py`.     |
| Navigator      | `navigator/toolkit.py` → `NavigatorToolkit` (Programs, Modules, Dashboards, Widgets — extends Postgres).     |

## 3.11 Recipe — composing a vendor MCP server

```python
from parrot.mcp.server import MCPServer
from parrot_tools.jiratoolkit import JiraToolkit

toolkit = JiraToolkit(host=..., username=..., api_token=...)

server = MCPServer(
    name="atlassian-mcp",
    transport="sse",                     # ChatGPT-compatible
    auth="oauth2_external",              # delegate to corporate IdP
    allowed_tools=["jira_search_issues", "jira_get_issue",
                   "jira_create_issue", "jira_transition"],
)
server.register_tools(toolkit.get_tools())
await server.serve(host="0.0.0.0", port=8765)
```

The exact same shape works for Odoo, AWS, CloudSploit, Workday or any
combination thereof.
