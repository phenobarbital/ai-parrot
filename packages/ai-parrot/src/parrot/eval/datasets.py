"""Dataset loaders for the Generic Agent Evaluation Harness.

FEAT-217 — Module 8.

A distinct ``DatasetLoader`` ABC is used instead of ``AbstractLoader``
(which produces ``List[Document]`` — wrong contract for eval tasks; see
spec §1 Non-Goals).

Provided implementations:
- ``JSONLDatasetLoader`` — one JSON object per line → ``EvalTask``.
- ``YAMLDatasetLoader`` — YAML doc with ``name`` + ``tasks: [...]``.
- ``HFDatasetLoader`` — stub; raises ``NotImplementedError`` (HF ingest
  is out of scope for this feature).
"""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import yaml

from parrot.eval.models import EvalDataset, EvalTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DatasetLoader ABC
# ---------------------------------------------------------------------------


class DatasetLoader(ABC):
    """Abstract loader that reads a benchmark file into an ``EvalDataset``.

    The real ``AbstractLoader`` (``parrot.loaders``) is not reused because
    it returns ``List[Document]`` — a contract that does not fit eval tasks
    (spec §1 Non-Goals).
    """

    @abstractmethod
    async def load(self, source: str) -> EvalDataset:
        """Load *source* into an ``EvalDataset``.

        Args:
            source: File path or URL for the dataset.

        Returns:
            Validated ``EvalDataset`` with all tasks.

        Raises:
            FileNotFoundError: If *source* does not exist.
            pydantic.ValidationError: If a record cannot be validated as
                ``EvalTask``.
        """
        ...


# ---------------------------------------------------------------------------
# JSONLDatasetLoader
# ---------------------------------------------------------------------------


class JSONLDatasetLoader(DatasetLoader):
    """Load an ``EvalDataset`` from a JSONL file.

    Each non-empty line must be a JSON object that validates as an
    ``EvalTask``.  The dataset name defaults to the filename stem.

    Malformed records raise ``pydantic.ValidationError`` immediately —
    no silent skipping.
    """

    async def load(self, source: str) -> EvalDataset:
        """Load *source* (a JSONL file path) into an ``EvalDataset``.

        Args:
            source: Path to the ``.jsonl`` file.

        Returns:
            ``EvalDataset`` with all validated tasks.

        Raises:
            FileNotFoundError: If the file does not exist.
            pydantic.ValidationError: On a malformed record.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"JSONL dataset not found: {source}")

        text = await asyncio.to_thread(path.read_text, encoding="utf-8")

        tasks: list[EvalTask] = []
        name = path.stem

        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {lineno} of {source}: {exc}"
                ) from exc
            task = EvalTask.model_validate(obj)
            tasks.append(task)

        logger.debug("JSONLDatasetLoader: loaded %d tasks from %s", len(tasks), source)
        return EvalDataset(name=name, tasks=tasks)


# ---------------------------------------------------------------------------
# YAMLDatasetLoader
# ---------------------------------------------------------------------------


class YAMLDatasetLoader(DatasetLoader):
    """Load an ``EvalDataset`` from a YAML file.

    Expected structure::

        name: my-dataset
        tasks:
          - task_id: t1
            inputs:
              query: "Do X"
            expected:
              goal_state: {}

    The ``name`` field defaults to the filename stem if absent.
    Each entry under ``tasks`` is validated as an ``EvalTask``.
    """

    async def load(self, source: str) -> EvalDataset:
        """Load *source* (a YAML file path) into an ``EvalDataset``.

        Args:
            source: Path to the ``.yaml`` / ``.yml`` file.

        Returns:
            ``EvalDataset`` with all validated tasks.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the YAML does not have a ``tasks`` list.
            pydantic.ValidationError: On a malformed task record.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"YAML dataset not found: {source}")

        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        doc = yaml.safe_load(text)

        if not isinstance(doc, dict):
            raise ValueError(
                f"YAML dataset must be a mapping with 'tasks' key, got {type(doc)!r}"
            )

        name = doc.get("name") or path.stem
        raw_tasks = doc.get("tasks", [])

        if not isinstance(raw_tasks, list):
            raise ValueError(
                f"'tasks' in YAML dataset must be a list, got {type(raw_tasks)!r}"
            )

        tasks: list[EvalTask] = []
        for idx, raw_task in enumerate(raw_tasks):
            if not isinstance(raw_task, dict):
                raise ValueError(
                    f"Task #{idx + 1} in {source} must be a mapping, got {type(raw_task)!r}"
                )
            task = EvalTask.model_validate(raw_task)
            tasks.append(task)

        logger.debug("YAMLDatasetLoader: loaded %d tasks from %s", len(tasks), source)
        return EvalDataset(name=name, tasks=tasks)


# ---------------------------------------------------------------------------
# HFDatasetLoader (reserved stub)
# ---------------------------------------------------------------------------


class HFDatasetLoader(DatasetLoader):
    """Reserved stub for Hugging Face dataset ingest.

    Full HF ingest (SWE-bench, τ-bench) is out of scope for this feature
    (spec §1 Non-Goals, §7 deps table).  Install ``datasets`` from HF and
    implement a subclass when needed.
    """

    async def load(self, source: str) -> EvalDataset:
        """Not implemented — raises ``NotImplementedError``.

        Args:
            source: Ignored.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "HFDatasetLoader is not implemented in this release. "
            "Install the 'datasets' package from Hugging Face and "
            "implement a subclass of DatasetLoader to load HF datasets."
        )
