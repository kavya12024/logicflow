"""
Unit tests for session_cache_lru module.
Verifies basic get/put, TTL expiration, and correct LRU eviction behavior on update.
"""

import unittest
from session_cache_lru import SessionCacheLRU


class TestSessionCacheLRU(unittest.TestCase):
    """Test suite for LRU cache with TTL."""

    def test_basic_put_and_get(self):
        """Test retrieving valid unexpired key."""
        cache = SessionCacheLRU(capacity=3)
        cache.put("user_1", {"role": "admin"}, current_time=100.0)
        self.assertEqual(cache.get("user_1", current_time=105.0), {"role": "admin"})

    def test_ttl_expiration_purges_entry(self):
        """Expired session returns None and is deleted."""
        cache = SessionCacheLRU(capacity=3, default_ttl_seconds=10.0)
        cache.put("user_1", {"name": "Alice"}, current_time=100.0)
        # 15 seconds later -> expired
        self.assertIsNone(cache.get("user_1", current_time=115.0))
        self.assertEqual(cache.size(), 0)

    def test_lru_eviction_order_after_update(self):
        """
        Verify that updating an existing key refreshes its LRU priority:
        - Insert key1, key2 (capacity = 2)
        - Update key1 (key1 is now MRU; key2 is LRU)
        - Insert key3 -> key2 should be evicted! key1 must remain!
        """
        cache = SessionCacheLRU(capacity=2)
        cache.put("key1", "val1", current_time=100.0)
        cache.put("key2", "val2", current_time=100.0)

        # Update key1 -> should refresh key1 as most-recently-used
        cache.put("key1", "val1_updated", current_time=101.0)

        # Insert key3 -> should evict key2 (the least recently used)
        cache.put("key3", "val3", current_time=102.0)

        # key1 must still be present!
        self.assertEqual(cache.get("key1", current_time=103.0), "val1_updated")
        # key2 must have been evicted!
        self.assertIsNone(cache.get("key2", current_time=103.0))


if __name__ == "__main__":
    unittest.main()
