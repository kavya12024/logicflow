"""
Unit tests for token_bucket_rate_limiter module.
Verifies capacity initialization, token refills, burst limits, and non-corrupting rejections.
"""

import unittest
from token_bucket_rate_limiter import TokenBucketLimiter


class TestTokenBucketLimiter(unittest.TestCase):
    """Test suite for token bucket rate limiter."""

    def test_initial_capacity(self):
        """Free tier should initialize with 10 tokens."""
        limiter = TokenBucketLimiter("client-1", tier="free", initial_time=100.0)
        self.assertEqual(limiter.tokens, 10.0)
        self.assertEqual(limiter.capacity, 10.0)

    def test_consume_within_capacity(self):
        """Consuming 4 tokens should leave 6 tokens remaining."""
        limiter = TokenBucketLimiter("client-1", tier="free", initial_time=100.0)
        allowed = limiter.allow_request(tokens_requested=4.0, current_time=100.0)
        self.assertTrue(allowed)
        self.assertEqual(limiter.tokens, 6.0)

    def test_rejection_does_not_corrupt_balance(self):
        """
        When a request exceeds available tokens:
        - Must return False (rejected)
        - Available tokens MUST NOT be decremented below 0 or corrupted!
        """
        limiter = TokenBucketLimiter("client-1", tier="free", initial_time=100.0)
        # Bucket has 10 tokens. Request 15 tokens:
        allowed = limiter.allow_request(tokens_requested=15.0, current_time=100.0)
        self.assertFalse(allowed)
        # Bucket should still have all 10 tokens intact, NOT -5!
        self.assertEqual(limiter.tokens, 10.0)

        # A subsequent valid request of 5 tokens should succeed!
        subsequent = limiter.allow_request(tokens_requested=5.0, current_time=100.0)
        self.assertTrue(subsequent)
        self.assertEqual(limiter.tokens, 5.0)

    def test_token_refill_over_time(self):
        """Tokens should replenish continuously at refill_rate."""
        limiter = TokenBucketLimiter("client-2", tier="free", initial_time=100.0)
        limiter.allow_request(tokens_requested=10.0, current_time=100.0)
        self.assertEqual(limiter.tokens, 0.0)

        # 3 seconds later, 3 tokens should be refilled
        limiter.refill(current_time=103.0)
        self.assertEqual(limiter.tokens, 3.0)


if __name__ == "__main__":
    unittest.main()
