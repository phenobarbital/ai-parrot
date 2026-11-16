import os
import json
import logging
from typing import Iterator, Literal
from parrot.knowledge.wiki.ledger.events import LedgerEvent

logger = logging.getLogger(__name__)


class LedgerLog:
    """Durable, append-only, single-line JSONL event log."""

    def __init__(self, path: str) -> None:
        """Initialize the LedgerLog with a file path.

        Args:
            path: Path to the events.jsonl file.
        """
        self.path = path

    def append(self, event: LedgerEvent) -> tuple[str, int]:
        """Append a single event to the log atomically and durably.

        The write itself is atomic and race-free across processes (a single
        ``os.write()`` under ``O_APPEND``, capped at 4 KiB — within the
        kernel's atomic-append guarantee). The *reported* ``byte_offset``
        is not: it is read via a separate ``lseek`` before the write, so a
        concurrent process's own append can land in the gap between that
        `lseek` and this `write`, making the returned offset earlier than
        this line's true file position. Treat it as informational/
        best-effort only — never as a precise cursor position under
        concurrent writers. (``LedgerIndex.claim_issue`` deliberately does
        not use it for exactly this reason; it re-derives the cursor by
        scanning the log itself instead.)

        The write is followed by ``os.fsync()`` before the fd is closed —
        this is the "durable source of truth" plane (spec §2), so a caller
        that already reported an event to a user/actor must survive not
        just this process crashing, but the OS crashing or losing power
        before the page cache would otherwise have flushed it.

        Args:
            event: The LedgerEvent to append.

        Returns:
            A tuple of (event_id, byte_offset) — see the offset caveat above.

        Raises:
            ValueError: If the serialized line exceeds 4 KiB (4096 bytes).
        """
        # Serialize to single-line JSON with a trailing newline
        serialized = event.model_dump_json() + "\n"
        encoded = serialized.encode("utf-8")

        # Enforce the 4 KiB line limit before opening/writing the file
        if len(encoded) > 4096:
            raise ValueError(f"Serialized event size ({len(encoded)} bytes) exceeds the 4 KiB limit.")

        # Open with O_APPEND | O_WRONLY | O_CREAT
        fd = os.open(self.path, os.O_APPEND | os.O_WRONLY | os.O_CREAT)
        try:
            # To get the start offset of the append, we can seek to the end or use fstat.
            # Since we opened with O_APPEND, writes always go to the end, but we want to know
            # the exact byte offset where this write starts.
            # Let's use os.lseek(fd, 0, os.SEEK_END) to find the current end of file (start of our write).
            start_offset = os.lseek(fd, 0, os.SEEK_END)

            # Write exactly once
            written = os.write(fd, encoded)
            if written != len(encoded):
                # In case of partial write (extremely rare for < 4KB on local filesystems, but good practice)
                raise OSError("Failed to write the complete event line atomically.")

            # Force the write to durable storage before returning — a
            # crash-only-safe (page-cache-only) append is not enough for
            # the log this feature bills as its durable source of truth.
            os.fsync(fd)
        finally:
            os.close(fd)

        return event.event_id, start_offset

    def append_line(self, line: str) -> int:
        """Append one already-serialized event line verbatim.

        Args:
            line: One JSON event line, with or without its trailing newline.

        Returns:
            The informational start byte offset of the append.

        Raises:
            ValueError: If the encoded line exceeds 4 KiB (4096 bytes).
        """
        encoded = (line if line.endswith("\n") else line + "\n").encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError(f"Serialized event size ({len(encoded)} bytes) exceeds the 4 KiB limit.")

        fd = os.open(self.path, os.O_APPEND | os.O_WRONLY | os.O_CREAT)
        try:
            start_offset = os.lseek(fd, 0, os.SEEK_END)
            written = os.write(fd, encoded)
            if written != len(encoded):
                raise OSError("Failed to write the complete event line atomically.")
            os.fsync(fd)
        finally:
            os.close(fd)

        return start_offset

    def probe_cursor(self, offset: int, last_event_id: str | None) -> Literal["current", "replay", "uncertain"]:
        """Validate the exact cursor anchor and EOF with bounded read-only I/O.

        The result is only an observation for ``LedgerIndex.sync``.  It never
        grants ownership of the log: a caller must still re-read its cursor
        before treating ``"current"`` as a no-op.

        Args:
            offset: Byte offset of the last applied event's line.
            last_event_id: Identifier of the event at ``offset``, or ``None``
                for an empty cursor.

        Returns:
            ``"current"`` for a stable exact anchor at EOF, ``"replay"``
            when a stable suffix exists, or ``"uncertain"`` when the cursor
            or file identity cannot be safely validated.

        Raises:
            OSError: For real file I/O failures other than a missing log race.
        """
        if last_event_id is None:
            if offset != 0:
                return "uncertain"
            try:
                before_path = os.stat(self.path)
            except FileNotFoundError:
                try:
                    os.stat(self.path)
                except FileNotFoundError:
                    return "current"
                return "uncertain"
            if before_path.st_size != 0:
                return "replay"

        try:
            fd = os.open(self.path, os.O_RDONLY)
        except FileNotFoundError:
            return "uncertain"

        try:
            before = os.fstat(fd)
            before_metadata = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )

            if last_event_id is None:
                result: Literal["current", "replay", "uncertain"] = "current"
            else:
                if offset < 0:
                    return "uncertain"
                os.lseek(fd, offset, os.SEEK_SET)
                anchor_bytes = os.read(fd, 4097)
                newline = anchor_bytes.find(b"\n")
                if newline < 0 or newline >= 4096:
                    return "uncertain"
                try:
                    anchor = LedgerEvent(**json.loads(anchor_bytes[: newline + 1].decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
                    return "uncertain"
                if anchor.event_id != last_event_id:
                    return "uncertain"
                os.lseek(fd, offset + newline + 1, os.SEEK_SET)
                result = "current" if os.read(fd, 1) == b"" else "replay"

            after = os.fstat(fd)
            after_metadata = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            try:
                pathname = os.stat(self.path)
            except FileNotFoundError:
                return "uncertain"
            pathname_metadata = (
                pathname.st_dev,
                pathname.st_ino,
                pathname.st_size,
                pathname.st_mtime_ns,
                pathname.st_ctime_ns,
            )
            if before_metadata != after_metadata or pathname_metadata != after_metadata:
                return "uncertain"
            return result
        finally:
            os.close(fd)

    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:
        """Stream events from the log starting at a given byte offset.

        Args:
            from_offset: Byte offset to start reading from.

        Yields:
            Tuples of (LedgerEvent, byte_offset) where byte_offset is the start position
            of the yielded event.
        """
        if not os.path.exists(self.path):
            return

        with open(self.path, "rb") as f:
            f.seek(from_offset)
            current_offset = from_offset

            while True:
                line_start = current_offset
                line = f.readline()
                if not line:
                    break
                current_offset += len(line)

                # Strip trailing newline/carriage return for parsing
                stripped = line.rstrip(b"\r\n")
                if not stripped:
                    continue

                try:
                    data = json.loads(stripped.decode("utf-8"))
                    event = LedgerEvent(**data)
                    yield event, line_start
                except Exception as e:
                    logger.warning(
                        "Malformed or partial-tail event line encountered at offset %d: %s",
                        line_start,
                        e,
                    )
