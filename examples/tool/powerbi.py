#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
from pprint import pprint
import requests
from azure.identity import DefaultAzureCredential
from navconfig import config
# Adjust import to your project layout:
# If your tool lives at parrot/tools/powerbi.py:
from parrot.tools.powerbi import PowerBIQueryTool

# scopes for Power BI
AZURE_TENANT_ID = config.get("AZURE_TENANT_ID")
AZURE_CLIENT_ID = config.get("AZURE_CLIENT_ID")
SCOPE = "https://analysis.windows.net/powerbi/api/.default"
BASE  = "https://api.powerbi.com/v1.0/myorg"
GROUP_ID   = os.environ.get("PBI_GROUP_ID",   "<YOUR_WORKSPACE_ID>")
DATASET_ID = os.environ.get("PBI_DATASET_ID", "62924035-2683-469f-9e33-8b89e7b0063f")

# Example DAX: top 5 rows from a table named 'Sales'
# (If your table has spaces, keep the single quotes)
DAX = "EVALUATE TOPN(5, 'Sales')"

async def main() -> None:
    # Get Credentials:
    cred = DefaultAzureCredential(
        interactive_browser_tenant_id=AZURE_TENANT_ID,
        interactive_browser_client_id=AZURE_CLIENT_ID,
        exclude_interactive_browser_credential=False
    )
    token = cred.get_token(SCOPE).token
    hdrs = {"Authorization": f"Bearer {token}"}

    # 1) List workspaces (My workspace will not appear here as a GUID; use 'me' for it)
    r = requests.get(f"{BASE}/groups", headers=hdrs, timeout=30)
    r.raise_for_status()
    groups = r.json().get("value", [])
    print("Workspaces:")
    for g in groups:
        print("-", g["name"], g["id"])
        GROUP_ID = g["id"]  # just pick the last one for demo

    # 2) List datasets in *My workspace*
    r = requests.get(f"{BASE}/groups/me/datasets", headers=hdrs, timeout=30)
    r.raise_for_status()
    print("\nDatasets in My workspace (groupId='me'):")
    for d in r.json().get("value", []):
        print("-", d["name"], d["id"])

    # 1) Build an Azure credential chain (env, managed identity, etc.)
    credential = DefaultAzureCredential(
        interactive_browser_tenant_id=AZURE_TENANT_ID,
        interactive_browser_client_id=AZURE_CLIENT_ID,
        exclude_interactive_browser_credential=False
    )

    # 2) Create the tool (you can also register it in your ToolRegistry if you prefer)
    tool = PowerBIQueryTool()

    # 3) Call the tool with your dataset/workspace and Azure credential
    # You can select output:
    #   rows/json (default), markdown, csv, dataframe, parquet, pyarrow.Table
    # Here we do default (rows + markdown), then a parquet example.
    print("=== Running DAX (rows + markdown) ===")
    res = await tool.execute(
        dataset_id=DATASET_ID,
        group_id=GROUP_ID,
        credential=credential,       # <-- key line: use DefaultAzureCredential
        command=DAX,
        timeout=60,
        max_attempts=5,              # retry on 429/5xx
        base_backoff=0.5,
        max_backoff=8.0,
        output_format="rows",        # try "markdown" | "csv" | "dataframe" | "parquet" | "pyarrow.Table"
    )

    if res.get("status") != "success":
        raise RuntimeError(f"Power BI query failed: {res}")

    result = res["result"]
    rows = result.get("rows", [])
    md = result.get("markdown", "")

    print(f"\nRows returned: {len(rows)}")
    pprint(rows[:2])  # show first 2 rows
    print("\nMarkdown preview:")
    print(md)

    # 4) Example: request Parquet file instead
    print("\n=== Running DAX (parquet) ===")
    res_parquet = await tool.execute(
        dataset_id=DATASET_ID,
        group_id=GROUP_ID,
        credential=credential,
        command=DAX,
        output_format="parquet",
        parquet_path="/tmp/powerbi_sample.parquet",
        timeout=60,
    )

    if res_parquet.get("status") != "success":
        raise RuntimeError(f"Power BI parquet export failed: {res_parquet}")

    print("Parquet written to:", res_parquet["result"]["parquet_path"])

    # 5) Example: CSV
    print("\n=== Running DAX (csv) ===")
    res_csv = await tool.execute(
        dataset_id=DATASET_ID,
        group_id=GROUP_ID,
        credential=credential,
        command=DAX,
        output_format="csv",
        export_csv_path="/tmp/powerbi_sample.csv",
        timeout=60,
    )
    print("CSV written to:", res_csv["result"]["csv_path"])

if __name__ == "__main__":
    asyncio.run(main())
