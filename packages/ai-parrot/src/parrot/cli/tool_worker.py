"""Worker-side entrypoint for remote tool execution.

This module is what the ``parrot-tools`` Docker image invokes:
``python -m parrot.cli.tool_worker --envelope -`` reads a
:class:`~parrot.tools.executors.ToolExecutionEnvelope` (JSON) from
stdin (or from a file when ``--envelope`` is a path) and prints the
resulting :class:`~parrot.tools.abstract.ToolResult` (JSON) to stdout
between sentinel markers so the executor that owns the worker can
extract the payload from the surrounding logs.

The worker is intentionally minimal:

* Permission checks have already happened on the caller side. We do not
  re-enforce them here — the envelope is treated as authoritative.
* Lifecycle events fire on the caller, not in the worker.
* The exit code is ``0`` on a well-formed ToolResult (even one with
  ``status="error"``) and non-zero only when the worker itself fails
  (invalid envelope, import error, unhandled exception).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback
from typing import Any

# Sentinel markers around the JSON payload so the parent process can
# extract the result from pod logs even if the tool's _execute method
# wrote unrelated chatter to stdout. K8sToolExecutor scans for these.
RESULT_BEGIN_MARKER = "__PARROT_TOOL_RESULT_BEGIN__"
RESULT_END_MARKER = "__PARROT_TOOL_RESULT_END__"


def _emit_result(payload: dict) -> None:
    """Print *payload* between sentinel markers."""
    sys.stdout.write(RESULT_BEGIN_MARKER + "\n")
    sys.stdout.write(json.dumps(payload, default=str))
    sys.stdout.write("\n" + RESULT_END_MARKER + "\n")
    sys.stdout.flush()


def _load_envelope_text(arg: str) -> str:
    """Resolve the ``--envelope`` argument to raw JSON text.

    ``-`` means stdin. Anything else is treated as a file path so
    operators can debug by writing an envelope JSON to disk.
    """
    if arg == "-" or arg == "":
        return sys.stdin.read()
    with open(arg, "r", encoding="utf-8") as fh:
        return fh.read()


async def _run(envelope_text: str) -> dict:
    """Parse the envelope, execute the tool, return a ToolResult dict."""
    # Local imports so ``--help`` does not pay the cost of importing
    # the full parrot tools stack.
    from parrot.tools.abstract import ToolResult
    from parrot.tools.executors.abstract import ToolExecutionEnvelope
    from parrot.tools.executors.runner import run_envelope_inprocess

    envelope = ToolExecutionEnvelope.model_validate_json(envelope_text)

    try:
        raw_result = await run_envelope_inprocess(envelope)
    except Exception as exc:  # tool itself raised
        tr = ToolResult(
            success=False,
            status="error",
            result=None,
            error=f"{type(exc).__name__}: {exc}",
            metadata={
                "tool_import_path": envelope.tool_import_path,
                "method_name": envelope.method_name,
                "traceback": traceback.format_exc(limit=20),
            },
        )
        return tr.model_dump(mode="json")

    # Normalise the same way ``AbstractTool.execute`` does — the
    # remote tool may have returned a raw value, a dict, or a ToolResult.
    if isinstance(raw_result, ToolResult):
        return raw_result.model_dump(mode="json")
    if (
        isinstance(raw_result, dict)
        and "status" in raw_result
        and "result" in raw_result
    ):
        try:
            return ToolResult(**raw_result).model_dump(mode="json")
        except Exception as exc:
            return ToolResult(
                success=False,
                status="done_with_errors",
                result=raw_result.get("result"),
                error=f"Could not coerce dict to ToolResult: {exc}",
                metadata=raw_result.get("metadata") or {},
            ).model_dump(mode="json")
    if raw_result is None:
        return ToolResult(
            success=False,
            status="error",
            result=None,
            error="Tool returned None.",
            metadata={
                "tool_import_path": envelope.tool_import_path,
                "method_name": envelope.method_name,
            },
        ).model_dump(mode="json")
    return ToolResult(
        success=True,
        status="success",
        result=raw_result,
        metadata={
            "tool_import_path": envelope.tool_import_path,
            "method_name": envelope.method_name,
        },
    ).model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parrot-tool-worker",
        description="Execute one ToolExecutionEnvelope from stdin or a file.",
    )
    parser.add_argument(
        "--envelope",
        default="-",
        help="Path to the envelope JSON, or '-' for stdin (default: -).",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="Logging level for the worker process (default: WARNING).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))

    try:
        envelope_text = _load_envelope_text(args.envelope)
    except OSError as exc:
        _emit_result(
            {
                "success": False,
                "status": "error",
                "result": None,
                "error": f"Could not read envelope: {exc}",
                "metadata": {},
            }
        )
        return 2

    try:
        payload = asyncio.run(_run(envelope_text))
    except Exception as exc:
        _emit_result(
            {
                "success": False,
                "status": "error",
                "result": None,
                "error": f"Worker crashed: {type(exc).__name__}: {exc}",
                "metadata": {"traceback": traceback.format_exc(limit=20)},
            }
        )
        return 3

    _emit_result(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
