# From ppt2desc (MIT, (c) 2025 Adam Łucek) - src/processor.py ThreadSafeRateLimiter, unchanged.
import threading
import time


class ThreadSafeRateLimiter:
    """
    Thread-safe rate limiter that enforces API rate limits across multiple threads.
    Uses a token bucket algorithm to ensure requests are evenly distributed.
    """

    def __init__(self, rate_limit: int):
        self.rate_limit = rate_limit
        self.min_interval = 60.0 / rate_limit if rate_limit > 0 else 0
        self.last_call_time = 0.0
        self.lock = threading.Lock()

    def acquire(self):
        if self.rate_limit <= 0:
            return
        while True:
            with self.lock:
                current_time = time.time()
                time_since_last = current_time - self.last_call_time
                if time_since_last >= self.min_interval:
                    self.last_call_time = current_time
                    return
                sleep_time = self.min_interval - time_since_last
            time.sleep(sleep_time)
