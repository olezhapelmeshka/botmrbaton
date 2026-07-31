"""
Per-user rate limiting with different policies per access level.

Implementation uses a simple token bucket per user.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict

from bot.group.config import GroupGateConfig, RateLimitConfig
from bot.group.types import UserLevel


@dataclass
class _UserBucket:
    tokens: float
    last_update: float


class RateLimiter:
    """
    Rate limiter that respects different limits based on UserLevel.
    """

    def __init__(self, config: GroupGateConfig):
        self.config = config
        self._buckets: Dict[int, _UserBucket] = {}

    def _get_limit(self, level: UserLevel) -> RateLimitConfig:
        return self.config.rate_limits.get(level, self.config.rate_limits[UserLevel.REGULAR])

    def _get_bucket(self, user_id: int, level: UserLevel) -> _UserBucket:
        """New users start with a full burst so the first message is never blocked."""
        if user_id not in self._buckets:
            limit = self._get_limit(level)
            self._buckets[user_id] = _UserBucket(
                tokens=float(limit.burst),
                last_update=time.time(),
            )
        return self._buckets[user_id]

    def is_allowed(self, user_id: int, level: UserLevel) -> bool:
        """
        Check if the user is allowed to send a message right now.
        If allowed, consumes one token.
        """
        limit = self._get_limit(level)
        bucket = self._get_bucket(user_id, level)
        now = time.time()

        # Refill tokens
        elapsed = now - bucket.last_update
        refill_rate = limit.messages_per_minute / 60.0
        bucket.tokens = min(limit.burst, bucket.tokens + elapsed * refill_rate)
        bucket.last_update = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True

        return False

    def reset_user(self, user_id: int) -> None:
        """Reset rate limit state for a user (useful for testing or admin commands)."""
        if user_id in self._buckets:
            del self._buckets[user_id]
