import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uuid
import time

from starlette.staticfiles import StaticFiles

from models import RequestModel, ResponseModel
from database import supabase_client

from rate_limiter import rate_limiter
from queue_manager import process_openai_request_ordered, sequence_counter
from monitoring import monitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting High Load System with Adaptive Rate Limiting")
    logger.info(f"📊 System configuration:")
    logger.info(f"   - Max input: 1000 RPS (adaptive)")
    logger.info(f"   - Output: 60 RPS (fixed)")
    logger.info(f"   - Max queue: 3600 requests")
    yield
    logger.info("👋 Shutting down High Load System")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="ui"), name="static")


@app.get("/")
async def root():
    return {
        "message": "High Load System API",
        "docs": "/docs",
        "system_stats": rate_limiter.get_stats()
    }


@app.post("/api/process", response_model=ResponseModel)
async def process_request(request: RequestModel):
    request_id = str(uuid.uuid4())

    monitor.increment_requests()
    allowed, reason, stats = rate_limiter.allow_input_request()

    if not allowed:
        monitor.increment_rate_limited()
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Rate limit exceeded",
                "reason": reason,
                "stats": stats,
                "retry_after_seconds": 1,
                "system_state": stats.get("system_state", "unknown")
            }
        )

    sequence_number = sequence_counter.get_next_sequence()

    try:
        supabase_client.table("requests").insert({
            "id": request_id,
            "payload": request.model_dump(),
            "status": "pending",
            "sequence_number": sequence_number,
            "created_at": time.time()
        })
        logger.info(f"Created request {request_id} with sequence {sequence_number}")
    except Exception as e:
        logger.error(f"Database error: {e}")

    process_openai_request_ordered.send(request_id, request.model_dump(), sequence_number)

    system_stats = rate_limiter.get_stats()

    return ResponseModel(
        request_id=request_id,
        status="queued",
        message=f"Request queued (sequence: {sequence_number}, estimated wait: {system_stats.get('estimated_wait_minutes', 0)} min)"
    )


@app.get("/api/status/{request_id}")
async def get_status(request_id: str):
    try:
        result = supabase_client.table("requests").select("*").eq("id", request_id)

        if hasattr(result, 'data') and result.data:
            return result.data[0]
        else:
            raise HTTPException(status_code=404, detail="Request not found")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/api/monitoring")
async def get_monitoring():
    basic_stats = monitor.get_stats()
    adaptive_stats = rate_limiter.get_stats()

    return {
        **basic_stats,
        "adaptive": adaptive_stats,
        "recommendations": get_system_recommendations(adaptive_stats)
    }


@app.get("/api/system-status")
async def get_system_status():
    stats = rate_limiter.get_stats()
    return {
        "status": "healthy" if stats.get("system_state") in ["normal", "busy"] else "warning",
        "details": stats,
        "queue_management": {
            "is_queue_growing": stats.get("queue_size", 0) > 100,
            "should_reduce_input": stats.get("system_state") in ["overloaded", "critical"],
            "estimated_catchup_time": stats.get("estimated_wait_minutes", 0)
        }
    }


def get_system_recommendations(stats: dict) -> list[str]:
    recommendations = []

    state = stats.get("system_state", "normal")
    queue_size = stats.get("queue_size", 0)
    wait_minutes = stats.get("estimated_wait_minutes", 0)

    if state == "normal":
        recommendations.append("✅ System operating normally")
    elif state == "busy":
        recommendations.append("⚠️ System is busy, input rate reduced to 200 RPS")
    elif state == "overloaded":
        recommendations.append("🚨 System overloaded, input rate reduced to 80 RPS")
        recommendations.append(f"📊 Current wait time: {wait_minutes} minutes")
    elif state == "critical":
        recommendations.append("🔥 System critical, input rate limited to 60 RPS")
        recommendations.append(f"⏰ Long wait times expected: {wait_minutes} minutes")
        recommendations.append("💡 Consider scaling or reducing load")

    if queue_size > 1000:
        recommendations.append("📈 Large queue detected, monitor for memory usage")

    return recommendations


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
