"""Best-effort feature completion receipts and host desktop delivery (stdlib only)."""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Mapping, Sequence
import uuid

logger = logging.getLogger(__name__)
DESKTOP_KEYS = (
    "PATH",
    "HOME",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
)
MAX_PAYLOAD_BYTES = 64 * 1024


def configure_notification(cache: Path, *, worktree: Path, env: Mapping[str, str]) -> str | None:
    """Write validated launch context; return a quoted Stop command or None."""
    try:
        # Validate feature metadata
        feature_id = env.get("PARROT_SDD_NOTIFY_FEATURE")
        slug = env.get("PARROT_SDD_NOTIFY_SLUG")
        desktop_json = env.get("PARROT_SDD_NOTIFY_DESKTOP")

        if not all([feature_id, slug, desktop_json]):
            logger.warning("Missing notification environment variables")
            return None

        # Parse desktop environment
        try:
            desktop_env = json.loads(desktop_json)
        except json.JSONDecodeError:
            logger.warning("Invalid desktop environment JSON")
            return None

        # Validate worktree
        if not worktree.is_dir():
            logger.warning("Invalid worktree path")
            return None

        # Load and validate index
        index_path = Path("sdd/tasks/index") / f"{slug}.json"
        full_index_path = worktree / index_path
        if not full_index_path.is_file():
            logger.warning("Index file not found")
            return None

        try:
            with open(full_index_path, "r") as f:
                index_data = json.load(f)
            if index_data.get("feature_id") != feature_id:
                logger.warning("Feature ID mismatch in index")
                return None
        except (json.JSONDecodeError, IOError):
            logger.warning("Failed to read or parse index file")
            return None

        # Write context file with 0600 permissions
        context_file = cache / "notify-context.json"
        context_data = {
            "schema_version": 1,
            "launch_id": cache.name,  # Use cache directory name as UUID
            "feature_id": feature_id,
            "slug": slug,
            "worktree": str(worktree.resolve()),
            "index": str(index_path),
            "desktop_env": {k: v for k, v in desktop_env.items() if k in DESKTOP_KEYS},
        }

        # Write with 0600 permissions
        with open(context_file, "w") as f:
            json.dump(context_data, f, indent=2)
        context_file.chmod(0o600)

        # Return quoted stop command
        script_path = Path(__file__).resolve()
        cmd = [sys.executable, "-S", str(script_path), "--hook", "--cache", str(cache.resolve())]
        return shlex.join(cmd)

    except Exception as e:
        logger.warning(f"Failed to configure notification: {e}")
        return None


def record_completion(env: Mapping[str, str]) -> bool:
    """Atomically record eligible feature completion in the existing session cache."""
    try:
        # Get cache directory
        cache_dir = env.get("PARROT_SDD_CACHE_DIR")
        if not cache_dir:
            logger.warning("Cache directory not found in environment")
            return False

        cache_path = Path(cache_dir)
        if not cache_path.is_dir():
            logger.warning("Invalid cache directory")
            return False

        # Read context file
        context_file = cache_path / "notify-context.json"
        if not context_file.is_file():
            logger.warning("Notification context not found")
            return False

        try:
            with open(context_file, "r") as f:
                context_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Failed to read notification context")
            return False

        # Validate feature ID
        feature_id = context_data.get("feature_id")
        if not feature_id:
            logger.warning("Invalid feature ID in context")
            return False

        # Validate worktree
        worktree_str = context_data.get("worktree")
        if not worktree_str:
            logger.warning("Invalid worktree in context")
            return False

        worktree = Path(worktree_str)
        if not worktree.is_dir():
            logger.warning("Worktree directory not found")
            return False

        # Validate index
        index_rel_path = context_data.get("index")
        if not index_rel_path:
            logger.warning("Invalid index path in context")
            return False

        index_path = worktree / index_rel_path
        if not index_path.is_file():
            logger.warning("Index file not found")
            return False

        # Check index contents
        try:
            with open(index_path, "r") as f:
                index_data = json.load(f)

            if index_data.get("feature_id") != feature_id:
                logger.warning("Feature ID mismatch in index")
                return False

            # Check that all tasks are done
            tasks = index_data.get("tasks", [])
            if not tasks:
                logger.warning("No tasks found in index")
                return False

            for task in tasks:
                if task.get("status") != "done":
                    logger.warning("Not all tasks are completed")
                    return False

        except (json.JSONDecodeError, IOError):
            logger.warning("Failed to read or parse index file")
            return False

        # Get current HEAD
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.warning("Failed to get Git HEAD")
                return False
            head = result.stdout.strip()
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            logger.warning("Failed to execute git command")
            return False

        # Create receipt data
        receipt_data = {
            "schema_version": 1,
            "launch_id": context_data.get("launch_id"),
            "feature_id": feature_id,
            "worktree": worktree_str,
            "head": head,
        }

        # Write receipt atomically with 0600 permissions
        receipt_file = cache_path / "notify-complete.json"
        temp_file = cache_path / f"notify-complete.json.tmp.{uuid.uuid4()}"

        try:
            with open(temp_file, "w") as f:
                json.dump(receipt_data, f, indent=2)
            temp_file.chmod(0o600)
            temp_file.replace(receipt_file)
        finally:
            if temp_file.exists():
                temp_file.unlink()

        return True

    except Exception as e:
        logger.warning(f"Failed to record completion: {e}")
        return False


def handle_stop(payload: Mapping[str, object], *, cache: Path) -> None:
    """Attempt one notification for a valid receipt without propagating operational errors."""
    try:
        # Validate payload
        if payload.get("hook_event_name") != "Stop":
            logger.debug("Not a Stop event")
            return

        # Check for background work
        background_tasks = payload.get("background_tasks")
        session_crons = payload.get("session_crons")
        if background_tasks or session_crons:
            logger.debug("Deferring notification due to background work")
            return

        # Read context file
        context_file = cache / "notify-context.json"
        if not context_file.is_file():
            logger.debug("Notification context not found")
            return

        try:
            with open(context_file, "r") as f:
                context_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Failed to read notification context")
            return

        # Read receipt file
        receipt_file = cache / "notify-complete.json"
        if not receipt_file.is_file():
            logger.debug("Completion receipt not found")
            return

        try:
            with open(receipt_file, "r") as f:
                receipt_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Failed to read completion receipt")
            return

        # Validate receipt data
        required_fields = ["launch_id", "feature_id", "worktree", "head"]
        for field in required_fields:
            if not receipt_data.get(field):
                logger.warning(f"Missing required field in receipt: {field}")
                return

        # Validate launch ID match
        if receipt_data.get("launch_id") != context_data.get("launch_id"):
            logger.warning("Launch ID mismatch")
            return

        # Validate feature ID match
        if receipt_data.get("feature_id") != context_data.get("feature_id"):
            logger.warning("Feature ID mismatch")
            return

        # Validate worktree match
        if receipt_data.get("worktree") != context_data.get("worktree"):
            logger.warning("Worktree mismatch")
            return

        # Validate worktree directory
        worktree = Path(receipt_data.get("worktree"))
        if not worktree.is_dir():
            logger.warning("Worktree directory not found")
            return

        # Validate current HEAD
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.warning("Failed to get current Git HEAD")
                return
            current_head = result.stdout.strip()

            if current_head != receipt_data.get("head"):
                logger.warning("Git HEAD mismatch")
                return
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            logger.warning("Failed to execute git command")
            return

        # Try to claim notification attempt
        attempt_file = cache / "notify-attempted"
        try:
            attempt_file.touch(exist_ok=False)
        except FileExistsError:
            logger.debug("Notification already attempted")
            return
        except IOError:
            logger.warning("Failed to create attempt claim file")
            return

        # Prepare notification
        feature_id = receipt_data.get("feature_id")
        slug = context_data.get("slug")
        worktree_str = receipt_data.get("worktree")

        title = f"SDD work completed: {feature_id}"
        body = f"{slug}\n{worktree_str}\nClaude Code remains open."

        # Escape HTML in body
        body = html.escape(body)

        # Get desktop environment
        desktop_env = context_data.get("desktop_env", {})

        # Find notify-send
        path_env = desktop_env.get("PATH", os.defpath)
        notify_send_path = shutil.which("notify-send", path=path_env)
        if not notify_send_path:
            # Try default locations
            for default_path in ["/usr/bin/notify-send", "/bin/notify-send"]:
                if os.path.isfile(default_path) and os.access(default_path, os.X_OK):
                    notify_send_path = default_path
                    break

        if not notify_send_path:
            logger.debug("notify-send not found")
            return

        # Prepare command
        cmd = [notify_send_path, "--urgency=normal", "--app-name=AI-Parrot SDD", "--expire-time=5000", title, body]

        # Execute with timeout
        try:
            subprocess.run(cmd, env={k: v for k, v in desktop_env.items() if k in DESKTOP_KEYS}, timeout=3, check=False)
        except subprocess.TimeoutExpired:
            logger.warning("Notification timed out")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    except Exception as e:
        logger.warning(f"Failed to handle stop event: {e}")


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch complete/hook mode; return zero for operational failures."""
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--complete", action="store_true", help="Record completion")
        parser.add_argument("--hook", action="store_true", help="Handle stop hook")
        parser.add_argument("--cache", type=Path, help="Cache directory path")

        args = parser.parse_args(argv)

        if args.complete:
            # Record completion
            if record_completion(os.environ):
                return 0
            else:
                logger.error("Failed to record completion")
                return 1

        elif args.hook:
            # Handle stop hook
            if not args.cache:
                logger.error("Cache directory required for hook mode")
                return 1

            if not args.cache.is_dir():
                logger.error("Invalid cache directory")
                return 1

            # Read bounded JSON from stdin
            try:
                raw_input = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
                if len(raw_input) > MAX_PAYLOAD_BYTES:
                    logger.error("Input too large")
                    return 1

                payload = json.loads(raw_input.decode("utf-8"))
                handle_stop(payload, cache=args.cache)
                return 0
            except json.JSONDecodeError:
                logger.error("Invalid JSON input")
                return 1
            except Exception as e:
                logger.error(f"Failed to process hook: {e}")
                return 1

        else:
            parser.print_help()
            return 1

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
