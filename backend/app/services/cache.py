from datetime import datetime, timedelta, timezone
from typing import Any


class MemoryCache:
    """进程内 TTL 缓存。"""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Any, datetime]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None

        value, expires_at = entry
        if datetime.now(timezone.utc) >= expires_at:
            del self._entries[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        self._entries[key] = (value, expires_at)
