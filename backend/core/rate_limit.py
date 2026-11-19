"""Tiny in-process rate limiter for the authentication endpoints.

A pilot deployment runs on a single process, so a locked dictionary of
sliding-window buckets is enough to stop password spraying and signup floods
without adding Redis or another service.  If the app is ever scaled to several
workers, move this to a shared store; the call sites do not need to change.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple


class RateLimiter:
    """Allow at most ``limit`` hits per ``window_seconds`` for one key."""

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> Tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)`` and record an allowed hit."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            if len(self._hits) > 5000:
                self._prune(cutoff)
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def _prune(self, cutoff: float) -> None:
        for key in list(self._hits):
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if not bucket:
                del self._hits[key]
