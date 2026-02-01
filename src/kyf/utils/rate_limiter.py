"""Rate limiter to respect Moltbook API limits."""

import asyncio
from datetime import datetime, timedelta


class RateLimiter:
    """Token-bucket rate limiter for API calls."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window = timedelta(seconds=window_seconds)
        self._timestamps: list[datetime] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        async with self._lock:
            now = datetime.utcnow()
            cutoff = now - self._window
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            if len(self._timestamps) >= self._max_requests:
                oldest = self._timestamps[0]
                wait_seconds = (oldest + self._window - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

            self._timestamps.append(datetime.utcnow())

    @property
    def remaining(self) -> int:
        """Number of requests available in the current window."""
        now = datetime.utcnow()
        cutoff = now - self._window
        active = [t for t in self._timestamps if t > cutoff]
        return max(0, self._max_requests - len(active))
