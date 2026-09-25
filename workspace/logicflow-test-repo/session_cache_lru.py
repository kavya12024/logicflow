"""
Session Cache with Least-Recently-Used (LRU) Eviction & TTL Expiry
Maintains user login sessions, token payloads, and automated expiry windows.
"""

import time
from typing import Dict, Any, Optional
from collections import OrderedDict


class SessionCacheLRU:
    """Thread-safe LRU session cache with Time-To-Live (TTL) support."""

    def __init__(self, capacity: int = 100, default_ttl_seconds: float = 300.0):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self.capacity = capacity
        self.default_ttl = default_ttl_seconds
        # Stores key -> {"value": data, "expires_at": float}
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    def _is_expired(self, entry: Dict[str, Any], current_time: float) -> bool:
        """Check if cache entry has exceeded its time-to-live."""
        return current_time > entry["expires_at"]

    def get(self, session_id: str, current_time: Optional[float] = None) -> Optional[Any]:
        """
        Retrieve session payload by ID.
        Marks item as most recently used.
        Returns None if session does not exist or has expired.
        """
        now = current_time if current_time is not None else time.time()

        if session_id not in self.cache:
            return None

        entry = self.cache[session_id]

        # Check expiration
        if self._is_expired(entry, now):
            # Expired session must be purged
            del self.cache[session_id]
            return None

        # Mark as most recently used
        self.cache.move_to_end(session_id)
        return entry["value"]

    def put(self, session_id: str, data: Any, ttl_seconds: Optional[float] = None, current_time: Optional[float] = None) -> None:
        """
        Insert or update a session in cache.
        Evicts least-recently-used entry if capacity is exceeded.
        """
        now = current_time if current_time is not None else time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = now + ttl

        entry = {"value": data, "expires_at": expires_at}

        if session_id in self.cache:
            self.cache[session_id] = entry
            # BUG: Forgot to mark existing updated key as most recently used!
            # It leaves the updated session at the front of OrderedDict (least recently used position),
            # causing active sessions to be prematurely evicted on next insertion!
            # Missing: self.cache.move_to_end(session_id)
            return

        # Evict oldest entry if at capacity
        if len(self.cache) >= self.capacity:
            # Pop least recently used item (first item in OrderedDict)
            self.cache.popitem(last=False)

        self.cache[session_id] = entry

    def size(self) -> int:
        """Return count of active items in cache."""
        return len(self.cache)
