from fastapi import FastAPI, Depends, HTTPException, Request, Header
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from typing import Any, Dict
import uuid
from datetime import datetime
import json
import os
import logging

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter

# Logging
logging.basicConfig(level=logging.INFO)

class HandoffRequest(BaseModel):
    message: Any
    next_agent: str

class HandoffResponse(BaseModel):
    success: bool
    cleaned_message: Any
    enriched_metadata: Dict
    next_agent: str
    handoff_id: str
    timestamp: datetime
    total_handoffs: int

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

def get_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

@app.get("/health")
async def health():
    return {"status": "ok-v2", "version": "latest"}

@app.get("/stats")
async def get_stats():
    if os.path.exists("usage_log.json"):
        with open("usage_log.json") as f:
            logs = json.load(f)
        return {"total_handoffs": len(logs), "recent": logs[-5:]}
    return {"total_handoffs": 0, "recent": []}

@app.post("/handoff", response_model=HandoffResponse)
@limiter.limit("30/minute")
async def create_handoff(request: Request, handoff_request: HandoffRequest, api_key: str = Depends(get_api_key)):
    is_pro = request.headers.get('x-pro-key') == 'pro-secret-123'

    try:
        handoff_id = str(uuid.uuid4())
        return {
            "success": True,
            "cleaned_message": handoff_request.message,
            "enriched_metadata": {
                "handoff_id": handoff_id,
                "processed_at": datetime.utcnow().isoformat(),
                "next_agent": handoff_request.next_agent,
                "is_pro": is_pro
            },
            "next_agent": handoff_request.next_agent,
            "handoff_id": handoff_id,
            "timestamp": datetime.utcnow(),
            "total_handoffs": 1
        }
    except Exception as e:
        logging.error(f"Handoff error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)