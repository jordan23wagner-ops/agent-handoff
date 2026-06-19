from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Any, Dict, Optional
from datetime import datetime
from app.services.handoff import process_handoff
from app.usage import record_usage
from app.billing import record_billing

app = FastAPI(title="Agent Handoff", version="0.1.0")

class HandoffRequest(BaseModel):
    message: Any
    next_agent: str
    context: Optional[Dict] = None

class HandoffResponse(BaseModel):
    success: bool
    cleaned_message: Any
    enriched_metadata: Dict
    next_agent: str
    handoff_id: str
    timestamp: datetime
    total_handoffs: int

async def get_api_key(x_api_key: str = Header(...)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    return x_api_key

@app.post("/handoff", response_model=HandoffResponse)
async def create_handoff(request: HandoffRequest, api_key: str = Depends(get_api_key)):
    result = await process_handoff(request)

    total = record_usage(result["handoff_id"], request.next_agent, True)
    record_billing(result["handoff_id"])

    return HandoffResponse(
        **result,
        total_handoffs=total
    )

@app.get("/health")
async def health():
    return {"status": "ok-v2", "version": "latest"}

@app.get("/stats")
async def get_stats():
    import json, os
    if os.path.exists("usage_log.json"):
        with open("usage_log.json") as f:
            logs = json.load(f)
        return {"total_handoffs": len(logs), "recent": logs[-5:]}
    return {"total_handoffs": 0, "recent": []}
