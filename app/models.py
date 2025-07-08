from pydantic import BaseModel
from typing import Optional


class RequestModel(BaseModel):
    prompt: str
    max_tokens: Optional[int] = 100
    temperature: Optional[float] = 0.7


class ResponseModel(BaseModel):
    request_id: str
    status: str
    message: str
