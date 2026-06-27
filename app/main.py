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
API_KEY = os.getenv("API_KEY")            # legacy single-key fallback
PRO_KEY = os.getenv("PRO_KEY")
MAX_MESSAGE_BYTES = 256 * 1024            # 256 KB hard cap on inbound payloads

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Optional billing/usage wiring — must NEVER break a handoff.
# ---------------------------------------------------------------------------
try:
    try:
        from app.usage import record_usage
    except ImportError:
        from usage import record_usage
except Exception as _e:  # pragma: no cover
    logging.warning(f"usage module unavailable, disabling usage logging: {_e}")

    def record_usage(handoff_id, next_agent, success):
        return None

try:
    try:
        from app.billing import record_billing
    except ImportError:
        from billing import record_billing
except Exception as _e:  # pragma: no cover
    logging.warning(f"billing module unavailable, disabling billing: {_e}")

    def record_billing(handoff_id, customer_id=None):
        return False


# ---------------------------------------------------------------------------
# API key -> Stripe customer map
#   API_KEYS env (JSON): {"<api_key>": "<stripe_customer_id>", ...}
#   Falls back to single API_KEY -> STRIPE_CUSTOMER_ID for backward compat.
# ---------------------------------------------------------------------------
def _load_key_map() -> Dict[str, str]:
    raw = os.getenv("API_KEYS")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                return {str(k): str(v) for k, v in data.items()}
            logging.error("API_KEYS must be a non-empty JSON object; ignoring.")
        except Exception as e:
            logging.error(f"API_KEYS is not valid JSON, ignoring: {e}")
    if API_KEY:
        return {API_KEY: os.getenv("STRIPE_CUSTOMER_ID", "")}
    return {}


KEY_MAP = _load_key_map()
logging.info(f"Loaded {len(KEY_MAP)} API key(s).")


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
# Auth (timing-safe, fail closed) -> returns the caller's Stripe customer id
# ---------------------------------------------------------------------------
def require_api_key(x_api_key: str = Header(...)) -> str:
    matched = None
    for key, customer in KEY_MAP.items():
        if hmac.compare_digest(str(x_api_key), key):
            matched = customer
            break
    if matched is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return matched  # Stripe customer id (may be "" if not yet mapped)


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


def _safe_pro(value: Any) -> bool:
    if not value or not PRO_KEY:
        return False
    return hmac.compare_digest(str(value), str(PRO_KEY))


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
async def get_stats(customer_id: str = Depends(require_api_key)):
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
    customer_id: str = Depends(require_api_key),
):
    is_pro = _safe_pro(request.headers.get("x-pro-key"))
    try:
        handoff_id = str(uuid.uuid4())
        cleaned = _clean(handoff_request.message)

        total_handoffs = 1
        try:
            count = record_usage(handoff_id, handoff_request.next_agent, True)
            if isinstance(count, int):
                total_handoffs = count
        except Exception as e:
            logging.warning(f"usage logging failed (non-fatal): {e}")

        if not is_pro:
            try:
                record_billing(handoff_id, customer_id or None)
            except Exception as e:
                logging.warning(f"billing failed (non-fatal): {e}")

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
                "billable": not is_pro,
                "customer_mapped": bool(customer_id),
            },
            "next_agent": handoff_request.next_agent,
            "handoff_id": handoff_id,
            "timestamp": datetime.now(timezone.utc),
            "total_handoffs": total_handoffs,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Handoff error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)