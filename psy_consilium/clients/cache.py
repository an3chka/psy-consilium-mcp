"""Small bounded TTL cache used only for public external MCP calls."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int = 900, max_size: int = 128) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        created_at, value = item
        if time.monotonic() - created_at > self.ttl_seconds:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._items[key] = (time.monotonic(), value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

