import redis
import time
import logging
import os
from typing import Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class SystemState(Enum):
    NORMAL = "normal"  # < 100 
    BUSY = "busy"  # 100-500
    OVERLOADED = "overloaded"  # 500-1000
    CRITICAL = "critical"  # > 1000


class AdaptiveRateLimiter:
    def __init__(self, redis_url: str = None):
        if redis_url is None:
            redis_url = os.getenv("REDIS_URL", "redis://redis:6379")

        try:
            self.redis_client = redis.from_url(redis_url)
            self.redis_client.ping()
            logger.info(f"✅ Redis connected successfully to {redis_url}")
        except Exception as e:
            logger.error(f"❌ Redis connection failed to {redis_url}: {e}")
            self.redis_client = None

        self.MAX_INPUT_RPS = 1000
        self.OUTPUT_RPS = 60
        self.MAX_QUEUE_SIZE = 3600
        self.CRITICAL_QUEUE_SIZE = 1800

        self.queue_size_key = "queue_size"
        self.input_rate_key = "input_rate"
        self.last_cleanup_key = "last_cleanup"

    def get_system_state(self) -> SystemState:
        if self.redis_client is None:
            return SystemState.NORMAL

        try:
            queue_size = int(self.redis_client.get(self.queue_size_key) or 0)

            if queue_size < 100:
                return SystemState.NORMAL
            elif queue_size < 500:
                return SystemState.BUSY
            elif queue_size < 1000:
                return SystemState.OVERLOADED
            else:
                return SystemState.CRITICAL

        except Exception as e:
            logger.error(f"Error getting system state: {e}")
            return SystemState.NORMAL

    def calculate_input_rate_limit(self) -> int:
        state = self.get_system_state()

        limits = {
            SystemState.NORMAL: 1000,
            SystemState.BUSY: 200,
            SystemState.OVERLOADED: 80,
            SystemState.CRITICAL: 60
        }

        return limits[state]

    def allow_input_request(self) -> tuple[bool, str, Dict[str, Any]]:
        if self.redis_client is None:
            logger.warning("Redis not connected, allowing request (fallback)")
            return True, "redis_unavailable_fallback", {
                "redis_status": "disconnected",
                "system_state": "unknown"
            }

        try:
            current_time = int(time.time())
            input_key = f"input_limit:{current_time}"

            current_limit = self.calculate_input_rate_limit()

            current_count = self.redis_client.incr(input_key)
            if current_count == 1:
                self.redis_client.expire(input_key, 1)

            stats = {
                "current_input_rps": current_count,
                "input_limit": current_limit,
                "system_state": self.get_system_state().value,
                "queue_size": int(self.redis_client.get(self.queue_size_key) or 0),
                "redis_status": "connected"
            }

            if current_count <= current_limit:
                self.redis_client.incr(self.queue_size_key)
                return True, "accepted", stats
            else:
                return False, f"Input rate limit exceeded: {current_count}/{current_limit} RPS", stats

        except Exception as e:
            logger.error(f"Error in input rate limiter: {e}")
            return True, "fallback_allow", {"redis_status": "error", "error": str(e)}

    def process_request_completed(self):
        if self.redis_client is None:
            return

        try:
            current_size = self.redis_client.decr(self.queue_size_key)
            if current_size < 0:
                self.redis_client.set(self.queue_size_key, 0)
        except Exception as e:
            logger.error(f"Error updating queue size: {e}")

    def get_stats(self) -> Dict[str, Any]:
        if self.redis_client is None:
            return {
                "redis_status": "disconnected",
                "queue_size": 0,
                "system_state": "unknown",
                "error": "Redis connection not available"
            }

        try:
            queue_size = int(self.redis_client.get(self.queue_size_key) or 0)
            state = self.get_system_state()
            current_limit = self.calculate_input_rate_limit()

            estimated_wait_time = queue_size / self.OUTPUT_RPS if queue_size > 0 else 0

            return {
                "redis_status": "connected",
                "queue_size": queue_size,
                "system_state": state.value,
                "current_input_limit": current_limit,
                "output_rps": self.OUTPUT_RPS,
                "estimated_wait_seconds": round(estimated_wait_time, 1),
                "estimated_wait_minutes": round(estimated_wait_time / 60, 1),
                "max_queue_size": self.MAX_QUEUE_SIZE,
                "queue_utilization_percent": round((queue_size / self.MAX_QUEUE_SIZE) * 100, 1)
            }

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "redis_status": "error",
                "error": str(e),
                "queue_size": 0,
                "system_state": "unknown"
            }

    def cleanup_old_counters(self):
        if self.redis_client is None:
            return

        try:
            current_time = time.time()
            last_cleanup = float(self.redis_client.get(self.last_cleanup_key) or 0)
            if current_time - last_cleanup > 300:
                keys_pattern = "input_limit:*"
                old_keys = self.redis_client.keys(keys_pattern)

                current_time_int = int(current_time)
                for key in old_keys:
                    key_time = int(key.decode().split(':')[1])
                    if current_time_int - key_time > 60:
                        self.redis_client.delete(key)

                self.redis_client.set(self.last_cleanup_key, current_time)
                logger.info(f"Cleaned up {len(old_keys)} old rate limiting keys")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


rate_limiter = AdaptiveRateLimiter()


class OutputRateLimiter:
    def __init__(self, redis_url: str = None, max_rps: int = 60):
        if redis_url is None:
            redis_url = os.getenv("REDIS_URL", "redis://redis:6379")

        try:
            self.redis_client = redis.from_url(redis_url)
            self.redis_client.ping()
            logger.info(f"✅ Output rate limiter connected to Redis at {redis_url}")
        except Exception as e:
            logger.error(f"❌ Output rate limiter Redis connection failed: {e}")
            self.redis_client = None

        self.max_rps = max_rps
        self.min_interval = 1.0 / max_rps
        self.last_request_time_key = "last_openai_request_time"

    def wait_for_rate_limit(self):
        if self.redis_client is None:
            time.sleep(self.min_interval)
            return

        try:
            last_time = self.redis_client.get(self.last_request_time_key)
            current_time = time.time()

            if last_time:
                last_time = float(last_time)
                elapsed = current_time - last_time

                if elapsed < self.min_interval:
                    sleep_time = self.min_interval - elapsed
                    time.sleep(sleep_time)
                    current_time = time.time()

            self.redis_client.set(self.last_request_time_key, current_time)

        except Exception as e:
            logger.error(f"Output rate limiter error: {e}")
            time.sleep(self.min_interval)


output_rate_limiter = OutputRateLimiter()