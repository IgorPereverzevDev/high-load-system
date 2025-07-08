import time
from typing import Dict, Any


class Monitoring:
    def __init__(self):
        self.stats = {
            "total_requests": 0,
            "rate_limited_requests": 0,
            "start_time": time.time(),
            "current_rps": 0
        }
        self.request_times = []

    def increment_requests(self):
        self.stats["total_requests"] += 1
        current_time = time.time()
        self.request_times.append(current_time)

        self.request_times = [t for t in self.request_times if current_time - t <= 1]
        self.stats["current_rps"] = len(self.request_times)

    def increment_rate_limited(self):
        self.stats["rate_limited_requests"] += 1

    def get_stats(self) -> Dict[str, Any]:
        uptime = time.time() - self.stats["start_time"]
        return {
            **self.stats,
            "uptime_seconds": uptime,
            "average_rps": self.stats["total_requests"] / uptime if uptime > 0 else 0
        }


monitor = Monitoring()
