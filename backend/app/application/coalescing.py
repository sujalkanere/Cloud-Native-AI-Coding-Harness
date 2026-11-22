"""
Terminal Output Coalescer and Capping for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.3, §3.6, and PROJECT.md:
- Flush terminal output every 100ms or 4KB (whichever comes first).
- Keep stdout and stderr streams strictly separate.
- Strictly enforce MAX_OUTPUT_BYTES_PER_RUN (5,242,880 bytes / 5 MB) per run.
- Emit explicit truncation_marker event when output limit is exceeded.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class TerminalCoalescer:
    """
    Coalesces rapid terminal stdout and stderr chunks into batch events.

    Flushes when:
    1. Size threshold reached: buffer has >= 4096 bytes (4KB)
    2. Time threshold reached: 100ms elapsed since first buffered byte
    3. Explicit flush() called (e.g., at end of command or run)

    Also enforces MAX_OUTPUT_BYTES_PER_RUN hard limit (default 5MB).
    """

    def __init__(
        self,
        run_id: str,
        emit_callback: Callable[[str, dict[str, Any]], Awaitable[Any]],
        max_bytes: int = 5242880,
        flush_interval_ms: float = 100.0,
        flush_size_bytes: int = 4096,
    ) -> None:
        self.run_id = run_id
        self._emit_callback = emit_callback
        self.max_bytes = max_bytes
        self.flush_interval = max(0.001, flush_interval_ms / 1000.0)
        self.flush_size_bytes = flush_size_bytes

        self._stdout_chunks: list[str] = []
        self._stderr_chunks: list[str] = []
        self._stdout_bytes: int = 0
        self._stderr_bytes: int = 0

        self._total_bytes_emitted: int = 0
        self._truncation_emitted: bool = False

        self._timer_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def total_bytes_emitted(self) -> int:
        return self._total_bytes_emitted

    @property
    def is_truncated(self) -> bool:
        return self._truncation_emitted

    async def feed(self, stream: str, data: str) -> None:
        """
        Feed a chunk of stdout or stderr data into the coalescer.
        """
        if not data or (self._truncation_emitted and self._total_bytes_emitted >= self.max_bytes):
            return

        if stream not in ("stdout", "stderr"):
            return

        async with self._lock:
            if self._truncation_emitted and self._total_bytes_emitted >= self.max_bytes:
                return

            encoded_len = len(data.encode("utf-8", errors="replace"))

            if stream == "stdout":
                self._stdout_chunks.append(data)
                self._stdout_bytes += encoded_len
                if self._stdout_bytes >= self.flush_size_bytes:
                    await self._flush_stream_locked("stdout", force=False)
            elif stream == "stderr":
                self._stderr_chunks.append(data)
                self._stderr_bytes += encoded_len
                if self._stderr_bytes >= self.flush_size_bytes:
                    await self._flush_stream_locked("stderr", force=False)

            # Check if buffers still hold un-flushed data
            has_buffered_data = (self._stdout_bytes > 0) or (self._stderr_bytes > 0)
            if has_buffered_data and self._timer_task is None:
                self._timer_task = asyncio.create_task(self._timer_loop())
            elif not has_buffered_data and self._timer_task is not None:
                self._timer_task.cancel()
                self._timer_task = None

    async def _timer_loop(self) -> None:
        """Background task that wakes up after flush_interval to flush buffers."""
        try:
            await asyncio.sleep(self.flush_interval)
            async with self._lock:
                await self._flush_all_locked(force=True)
        except asyncio.CancelledError:
            pass
        except (OSError, RuntimeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("Error in terminal coalescer timer loop: %s", exc)
        finally:
            self._timer_task = None

    async def _flush_stream_locked(self, stream: str, force: bool = True) -> None:
        """Flushes buffered data for a single stream while holding self._lock."""
        chunks = self._stdout_chunks if stream == "stdout" else self._stderr_chunks
        byte_count = self._stdout_bytes if stream == "stdout" else self._stderr_bytes
        if not chunks or byte_count == 0:
            return

        data = "".join(chunks)
        raw_bytes = data.encode("utf-8", errors="replace")
        total_len = len(raw_bytes)

        if not force:
            num_blocks = total_len // self.flush_size_bytes
            if num_blocks == 0:
                return
            emit_len = num_blocks * self.flush_size_bytes
            to_emit_bytes = raw_bytes[:emit_len]
            remainder_bytes = raw_bytes[emit_len:]

            chunks.clear()
            if remainder_bytes:
                chunks.append(remainder_bytes.decode("utf-8", errors="replace"))

            if stream == "stdout":
                self._stdout_bytes = len(remainder_bytes)
            else:
                self._stderr_bytes = len(remainder_bytes)

            raw_bytes = to_emit_bytes
            total_len = emit_len
        else:
            chunks.clear()
            if stream == "stdout":
                self._stdout_bytes = 0
            else:
                self._stderr_bytes = 0

        if self._truncation_emitted and self._total_bytes_emitted >= self.max_bytes:
            return

        # Break into chunks of at most flush_size_bytes if size exceeds flush_size_bytes
        # but emit all available chunks during flush
        offset = 0

        while offset < total_len:
            if self._truncation_emitted and self._total_bytes_emitted >= self.max_bytes:
                break

            chunk_bytes = raw_bytes[offset : offset + self.flush_size_bytes]
            chunk_len = len(chunk_bytes)
            offset += chunk_len

            if self._total_bytes_emitted + chunk_len <= self.max_bytes:
                self._total_bytes_emitted += chunk_len
                chunk_str = chunk_bytes.decode("utf-8", errors="replace")
                await self._emit_callback(
                    self.run_id,
                    {
                        "type": "terminal_output",
                        "payload": {"stream": stream, "data": chunk_str},
                    },
                )
            else:
                remaining = max(0, self.max_bytes - self._total_bytes_emitted)
                if remaining > 0:
                    allowed_bytes = chunk_bytes[:remaining]
                    self._total_bytes_emitted += remaining
                    allowed_str = allowed_bytes.decode("utf-8", errors="replace")
                    await self._emit_callback(
                        self.run_id,
                        {
                            "type": "terminal_output",
                            "payload": {"stream": stream, "data": allowed_str},
                        },
                    )

                self._truncation_emitted = True
                await self._emit_callback(
                    self.run_id,
                    {
                        "type": "truncation_marker",
                        "payload": {
                            "message": (
                                f"Run output exceeded limit of {self.max_bytes} bytes; "
                                "terminal output truncated."
                            ),
                            "limit": self.max_bytes,
                        },
                    },
                )
                break

    async def _flush_all_locked(self, force: bool = True) -> None:
        """Flushes both stdout and stderr buffers."""
        await self._flush_stream_locked("stdout", force=force)
        await self._flush_stream_locked("stderr", force=force)

    async def flush(self) -> None:
        """Forces immediate flush of all buffered terminal output."""
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None
        async with self._lock:
            await self._flush_all_locked(force=True)

    async def close(self) -> None:
        """Closes the coalescer and flushes any pending output."""
        await self.flush()
