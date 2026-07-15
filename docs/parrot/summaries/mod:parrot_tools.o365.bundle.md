---
type: Wiki Summary
title: parrot_tools.o365.bundle
id: mod:parrot_tools.o365.bundle
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SharePoint and OneDrive Toolkits for AI-Parrot
relates_to:
- concept: class:parrot_tools.o365.bundle.Office365FileManagementToolkit
  rel: defines
- concept: class:parrot_tools.o365.bundle.OneDriveToolkit
  rel: defines
- concept: class:parrot_tools.o365.bundle.SharePointToolkit
  rel: defines
- concept: func:parrot_tools.o365.bundle.create_file_management_toolkit
  rel: defines
- concept: func:parrot_tools.o365.bundle.create_onedrive_toolkit
  rel: defines
- concept: func:parrot_tools.o365.bundle.create_sharepoint_toolkit
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot_tools.o365.base
  rel: references
- concept: mod:parrot_tools.o365.onedrive
  rel: references
- concept: mod:parrot_tools.o365.sharepoint
  rel: references
---

# `parrot_tools.o365.bundle`

SharePoint and OneDrive Toolkits for AI-Parrot

Toolkit wrappers for SharePoint and OneDrive file management tools.

## Classes

- **`SharePointToolkit`** — SharePoint file management toolkit for AI-Parrot agents.
- **`OneDriveToolkit`** — OneDrive file management toolkit for AI-Parrot agents.
- **`Office365FileManagementToolkit`** — Complete Office365 file management toolkit (SharePoint + OneDrive).

## Functions

- `def create_sharepoint_toolkit(client_id: str, client_secret: str, tenant_id: str, **kwargs) -> SharePointToolkit` — Factory function to create a SharePoint toolkit.
- `def create_onedrive_toolkit(client_id: str, client_secret: str, tenant_id: str, **kwargs) -> OneDriveToolkit` — Factory function to create a OneDrive toolkit.
- `def create_file_management_toolkit(client_id: str, client_secret: str, tenant_id: str, **kwargs) -> Office365FileManagementToolkit` — Factory function to create a complete file management toolkit.
