import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ---------------------------------------------------------------------------
# Config (all secrets come from the environment, never hardcoded)
# ---------------------------------------------------------------------------
API_KEY = os.getenv("API_KEY")
PRO_KEY = os.getenv("PRO_KEY")
MAX_MESSAGE_BYTES = 256 * 1024  # 256 KB hard cap on inbound payloads

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Models + validation
# ---------------------------------------------------------------------------
class HandoffRequest(BaseModel):
    message: Any
    next_agent: str

    @field_validator("next_agent")
    @classmethod
    def _next_agent_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("next_agent must be a non-empty string")
        if len(v) > 128:
            raise ValueError("next_agent too long (max 128 chars)")
        return v

    @field_validator("message")
    @classmethod
    def _message_present_and_bounded(cls, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("message must not be empty")
        if len(json.dumps(v, default=str)) > MAX_MESSAGE_BYTES:
            raise ValueError("message exceeds 256 KB limit")
        return v


class HandoffResponse(BaseModel):
    success: bool
    cleaned_message: Any
    enriched_metadata: Dict
    next_agent: str
    handoff_id: str
    timestamp: datetime
    total_handoffs: int


# ---------------------------------------------------------------------------
# Auth helpers (timing-safe, fail closed)
# ---------------------------------------------------------------------------
def _safe_eq(a: Any, b: Any) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(str(a), str(b))


def require_api_key(x_api_key: str = Header(...)) -> str:
    # Fails closed: if API_KEY is unset on the server, every request is rejected.
    if not _safe_eq(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


def _clean(message: Any) -> Any:
    if isinstance(message, dict):
        return {
            k: (v.strip() if isinstance(v, str) else v)
            for k, v in message.items()
            if v is not None
        }
    if isinstance(message, str):
        return message.strip()
    return message


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    raise HTTPException(status_code=429, detail="Too many requests. Try again later.")


@app.get("/health")
async def health():
    return {"status": "ok-v2", "version": "latest"}


@app.get("/stats")
async def get_stats(api_key: str = Depends(require_api_key)):
    if os.path.exists("usage_log.json"):
        with open("usage_log.json") as f:
            logs = json.load(f)
        return {"total_handoffs": len(logs), "recent": logs[-5:]}
    return {"total_handoffs": 0, "recent": []}


@app.post("/handoff", response_model=HandoffResponse)
@limiter.limit("30/minute")
async def create_handoff(
    request: Request,
    handoff_request: HandoffRequest,
    api_key: str = Depends(require_api_key),
):
    is_pro = _safe_eq(request.headers.get("x-pro-key"), PRO_KEY)
    try:
        handoff_id = str(uuid.uuid4())
        cleaned = _clean(handoff_request.message)
        return {
            "success": True,
            "cleaned_message": cleaned,
            "enriched_metadata": {
                "handoff_id": handoff_id,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "next_agent": handoff_request.next_agent,
                "original_type": type(handoff_request.message).__name__,
                "estimated_tokens": len(str(cleaned)) // 4,
                "is_pro": is_pro,
            },
            "next_agent": handoff_request.next_agent,
            "handoff_id": handoff_id,
            "timestamp": datetime.now(timezone.utc),
            "total_handoffs": 1,
        }
    except Exception as e:
        logging.error(f"Handoff error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)