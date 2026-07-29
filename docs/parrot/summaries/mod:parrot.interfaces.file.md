---
type: Wiki Summary
title: parrot.interfaces.file
id: mod:parrot.interfaces.file
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: File manager interfaces — re-exported from navigator.utils.file.
---

# `parrot.interfaces.file`

File manager interfaces — re-exported from navigator.utils.file.

This module is a backward-compat shim. The single source of truth
is navigator.utils.file (navigator-api >= 3.0.3). New code SHOULD
import directly from navigator.utils.file; existing code that
uses parrot.interfaces.file continues to work via this shim.

Eager re-exports: FileManagerInterface, FileMetadata,
                  LocalFileManager, TempFileManager.
Lazy re-exports:  S3FileManager, GCSFileManager — loaded on first
                  access via __getattr__ so importing this package
                  does not pull in aioboto3 or
                  google-cloud-storage.
