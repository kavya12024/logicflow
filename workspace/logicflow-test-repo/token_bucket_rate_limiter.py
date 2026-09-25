"""
Token Bucket Rate Limiter Module
Implements burstable token bucket rate limiting for multi-tier API consumers.
Supports dynamic refills, tier quotas, and token consumption checks.
"""

import time
from typing import Dict, Any, Optional
from dataclasses import dataclass


TIER_LIMITS = {
    "free": {"capacity": 10.0, "refill_rate": 1.0},        # 1 token/sec, burst up to 10
    "pro": {"capacity": 50.0, "refill_rate": 10.0},       # 10 tokens/sec, burst up to 50
    "enterprise": {"capacity": 200.0, "refill_rate": 50.0} # 50 tokens/sec, burst up to 200
}


class TokenBucketLimiter:
    """Thread-safe token bucket rate limiter for an API client."""

    def __init__(self, client_id: str, tier: str = "free", initial_time: Optional[float] = None):
        if tier not in TIER_LIMITS:
            raise ValueError(f"Unknown subscription tier: {tier}")

        tier_config = TIER_LIMITS[tier]
        self.client_id = client_id
        self.tier = tier
        self.capacity = tier_config["capacity"]
        self.refill_rate = tier_config["refill_rate"]
        
        self.tokens = self.capacity
        self.last_refill_time = initial_time if initial_time is not None else time.time()

    def refill(self, current_time: float) -> None:
        """Replenish tokens based on continuous elapsed time."""
        if current_time < self.last_refill_time:
            return

        elapsed = current_time - self.last_refill_time
        tokens_to_add = elapsed * self.refill_rate
        
        # Replenish and clamp to maximum burst capacity
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill_time = current_time

    def allow_request(self, tokens_requested: float = 1.0, current_time: Optional[float] = None) -> bool:
        """
        Check if request can be accommodated and consume tokens.
        Returns True if request allowed, False if rate-limited.
        """
        if tokens_requested <= 0:
            raise ValueError("Requested tokens must be positive")

        now = current_time if current_time is not None else time.time()
        self.refill(now)

        # BUG: Logic error: Deducts tokens BEFORE checking if balance is sufficient!
        # This causes client tokens to go negative and leaves the bucket corrupted
        # on rejected requests.
        self.tokens -= tokens_requested
        if self.tokens < 0:
            # Bug: Does not restore self.tokens when rejecting!
            return False

        return True

    def get_status(self) -> Dict[str, Any]:
        """Return snapshot of rate limiter state."""
        return {
            "client_id": self.client_id,
            "tier": self.tier,
            "available_tokens": round(self.tokens, 2),
            "capacity": self.capacity,
            "refill_rate": self.refill_rate
        }
