"""SSE event bus for real-time dashboard updates."""

import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class EventBus:
    """Simple pub/sub event bus backed by asyncio.Queue for each subscriber."""

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    def publish(self, event_type: str, data: dict):
        """Publish an event to all subscribers."""
        message = {"event": event_type, "data": data}
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # Drop events for slow consumers

    async def subscribe(self) -> AsyncGenerator[str, None]:
        """Subscribe to events. Yields SSE-formatted strings."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        try:
            while True:
                message = await queue.get()
                yield json.dumps(message, default=str)
        finally:
            self._subscribers.remove(queue)


# Global event bus
event_bus = EventBus()
