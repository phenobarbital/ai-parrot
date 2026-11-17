"""Compatibility exports for the core job primitives."""

from parrot.jobs.manager import JobManager
from parrot.jobs.models import Job, JobStatus

__all__ = ("JobManager", "Job", "JobStatus")
