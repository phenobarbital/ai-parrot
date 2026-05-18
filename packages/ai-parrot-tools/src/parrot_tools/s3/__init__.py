"""parrot_tools.s3 — Agnostic S3 report reader toolkit and utilities.

Public exports:
- ``GenericReportComparator`` — structural diff engine for S3-stored reports.
- ``S3ReportReaderToolkit`` — LLM-facing toolkit (8 tools, ``s3_`` prefix).

Module implements Spec §3 Modules 1–3 (FEAT-184).
"""
from .comparator import GenericReportComparator

__all__ = ("GenericReportComparator",)
