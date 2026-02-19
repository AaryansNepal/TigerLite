import asyncio
import logging
from datetime import datetime, timezone

from .config import FLUSH_BATCH_SIZE, FLUSH_INTERVAL_SECONDS
from .schema import TelemetryEvent

logger = logging.getLogger(__name__)


class EventBuffer:
    """In-memory buffer that flushes events to Iceberg on size or time threshold."""

    def __init__(self):
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()
        self._table = None
        self._total_ingested = 0

    def set_table(self, table):
        self._table = table

    @property
    def total_ingested(self) -> int:
        return self._total_ingested

    async def add(self, event: TelemetryEvent):
        async with self._lock:
            event_dict = event.model_dump()
            # Ensure timestamp is timezone-aware for Iceberg
            ts = event_dict["timestamp"]
            if ts.tzinfo is None:
                event_dict["timestamp"] = ts.replace(tzinfo=timezone.utc)
            self._buffer.append(event_dict)
            self._total_ingested += 1

            if len(self._buffer) >= FLUSH_BATCH_SIZE:
                await self._flush()

    async def flush(self):
        async with self._lock:
            await self._flush()

    async def _flush(self):
        if not self._buffer or self._table is None:
            return

        batch = self._buffer.copy()
        self._buffer.clear()

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: _sync_append(self._table, batch)
            )
            logger.info(f"Flushed {len(batch)} events")
        except Exception as e:
            logger.error(f"Failed to flush events: {e}")
            # Put events back for retry
            self._buffer = batch + self._buffer


def _sync_append(table, events: list[dict]):
    from .iceberg_writer import append_events
    append_events(table, events)


async def periodic_flush(buffer: EventBuffer):
    """Background task to flush the buffer periodically."""
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        try:
            await buffer.flush()
        except Exception as e:
            logger.error(f"Periodic flush error: {e}")


# Global buffer instance
event_buffer = EventBuffer()
