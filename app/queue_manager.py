import logging

import dramatiq
import time
import redis
from typing import Dict, Any
from dramatiq.brokers.redis import RedisBroker
from datetime import datetime

from database import supabase_client
from openai_mock import mock_openai_api
from rate_limiter import rate_limiter, output_rate_limiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_broker = RedisBroker(url="redis://redis:6379")
dramatiq.set_broker(redis_broker)

redis_client = redis.from_url("redis://redis:6379")


@dramatiq.actor(
    max_retries=3,
    priority=0,
    queue_name="openai_requests"
)
def process_openai_request_ordered(request_id: str, payload: Dict[Any, Any], sequence_number: int):
    logger.info(f"🔄 Processing request {request_id} (sequence: {sequence_number})")

    update_request_status(request_id, "processing")

    try:
        output_rate_limiter.wait_for_rate_limit()

        result = mock_openai_api.generate_response(payload)

        save_request_result(request_id, result, "completed")

        logger.info(f"✅ Successfully processed request {request_id} (sequence: {sequence_number})")

    except Exception as e:
        logger.error(f"❌ Error processing request {request_id}: {e}")
        save_request_result(request_id, {"error": str(e)}, "failed")

    finally:
        rate_limiter.process_request_completed()
        if sequence_number % 100 == 0:
            rate_limiter.cleanup_old_counters()


def update_request_status(request_id: str, status: str):
    try:
        result = supabase_client.table("requests").update({
            "status": status,
            "updated_at": datetime.now().isoformat()
        }).eq("id", request_id).execute()
        return result
    except Exception as e:
        logger.error(f"Error updating request status: {e}")
        return None


def save_request_result(request_id: str, result: Dict[Any, Any], status: str):
    try:
        db_result = supabase_client.table("requests").update({
            "result": result,
            "status": status,
            "completed_at": datetime.now().isoformat()
        }).eq("id", request_id).execute()
        return db_result
    except Exception as e:
        logger.error(f"Error saving request result: {e}")
        return None


class SequenceCounter:
    def __init__(self):
        self.counter_key = "request_sequence_counter"

    def get_next_sequence(self) -> int:
        try:
            return redis_client.incr(self.counter_key)
        except:
            return int(time.time() * 1000) % 1000000


sequence_counter = SequenceCounter()