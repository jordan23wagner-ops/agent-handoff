"""MCP (Model Context Protocol) server for agent-handoff.

This is the endpoint AI agents talk to once this server is listed in the
official MCP registry (registry.modelcontextprotocol.io). It speaks JSON-RPC
2.0 over HTTP at POST /mcp.

DESIGN NOTES
------------
1. Billing parity. The `handoff` tool runs the SAME auth -> usage -> billing
   sequence as the REST /handoff endpoint. Without that, /mcp would be a free,
   unmetered side door around the paid endpoint: agents would discover it via
   the registry and never generate a cent of revenue. Every billable action
   here goes through record_billing() exactly like its REST twin.

2. A handoff must never fail because billing failed. Same contract as
   main.py -- billing problems are logged loudly and reported in the response
   metadata, but they never turn a successful handoff into an error.

3. Self-contained on purpose. This module deliberately does NOT import from
   app.main (that would be a circular import, since main.py includes this
   router). The API-key map loader below mirrors main.py's. That duplication is
   a conscious trade: it keeps the change to a working production service down
   to a single include_router() line. Worth consolidating into a shared
   app/auth.py later, once this has proven itself in production.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter
from slowapi.util import get_remote_address

try:
    from app.services.handoff import process_handoff
except ImportError:  # pragma: no cover - supports both import styles
    from services.handoff import process_handoff

try:
    from app.usage import record_usage
except ImportError:  # pragma: no cover
    try:
        from usage import record_usage
    except Exception:
        def record_usage(handoff_id, next_agent, success):
            return None

try:
    from app.billing import record_billing
except ImportError:  # pragma: no cover
    try:
        from billing import record_billing
    except Exception as _e:
        def record_billing(handoff_id, customer_id=None):
            return {"billed": False, "status": "module_unavailable", "error": str(_e)}


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "agent-handoff"
SERVER_VERSION = "1.0.0"

router = APIRouter()

# Own limiter instance (see design note 3). Keyed on remote address, same as
# main.py's, so /mcp gets its own 30/min budget rather than sharing one.
mcp_limiter = Limiter(key_func=get_remote_address)


# --- Auth -------------------------------------------------------------------
def _load_key_map() -> Dict[str, str]:
    """API key -> Stripe customer id. Mirrors main.py's loader."""
    raw = os.getenv("API_KEYS")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data:
                return {str(k): str(v) for k, v in data.items()}
            logging.error("[MCP] API_KEYS must be a non-empty JSON object; ignoring.")
        except Exception as e:
            logging.error(f"[MCP] API_KEYS is not valid JSON, ignoring: {e}")
    legacy = os.getenv("API_KEY")
    if legacy:
        return {legacy: os.getenv("STRIPE_CUSTOMER_ID", "")}
    return {}


def _resolve_customer(api_key: Optional[str]) -> Optional[str]:
    """Return the Stripe customer id for a key, or None if the key is invalid.

    Uses a constant-time compare so this endpoint doesn't leak key material
    through response timing.
    """
    import hmac

    if not api_key:
        return None
    for key, customer in _load_key_map().items():
        if hmac.compare_digest(str(api_key), str(key)):
            return customer
    return None


# --- Tool definitions -------------------------------------------------------
TOOLS = [
    {
        "name": "handoff",
        "description": (
            "Hand a message off to another agent. Cleans and normalizes the payload, "
            "stamps it with handoff metadata (id, timestamp, estimated tokens, target "
            "agent), and records the handoff. Use this when passing work or context "
            "from one agent to the next in a multi-agent pipeline. This is a metered, "
            "billable operation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "description": (
                        "The payload to hand off. Accepts a plain string or a JSON object. "
                        "Max 256 KB."
                    ),
                    "type": ["string", "object", "array", "number", "boolean"],
                },
                "next_agent": {
                    "type": "string",
                    "description": "Name/identifier of the agent receiving this handoff.",
                    "maxLength": 128,
                },
            },
            "required": ["message", "next_agent"],
        },
    },
    {
        "name": "get_usage_stats",
        "description": (
            "Return this account's total handoff count and the most recent handoffs. "
            "Read-only and not billed."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

MAX_MESSAGE_BYTES = 256 * 1024


# --- JSON-RPC helpers -------------------------------------------------------
def _result(req_id: Any, payload: Dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": payload})


def _error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _tool_text(req_id: Any, text: str, is_error: bool = False) -> JSONResponse:
    """A tool outcome. Failures ride inside a successful JSON-RPC response with
    isError set, so the calling model can see and react to them."""
    payload: Dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        payload["isError"] = True
    return _result(req_id, payload)


class _HandoffRequest:
    """Minimal duck-type of main.py's HandoffRequest for process_handoff()."""

    def __init__(self, message: Any, next_agent: str):
        self.message = message
        self.next_agent = next_agent


@router.post("/mcp")
@mcp_limiter.limit("30/minute")
async def mcp_endpoint(request: Request, x_api_key: Optional[str] = Header(default=None)):
    try:
        body = await request.json()
    except Exception:
        return _error(None, -32700, "Parse error: body is not valid JSON")

    if not isinstance(body, dict):
        return _error(None, -32600, "Invalid Request: body must be a JSON object")

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}

    if not isinstance(method, str) or not method:
        return _error(req_id, -32600, "Invalid Request: missing 'method'")

    # Notifications carry no id and must not receive a response body.
    if method.startswith("notifications/"):
        return Response(status_code=202)

    # --- Handshake + discovery stay open ------------------------------------
    # Agents have to be able to see what this server offers before they can
    # decide to pay for it. Only actual tool execution is gated.
    if method == "initialize":
        requested = params.get("protocolVersion")
        return _result(
            req_id,
            {
                "protocolVersion": requested if isinstance(requested, str) else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "agent-handoff passes messages between AI agents with cleaning, "
                    "enrichment, and metered billing. Every tools/call requires a valid "
                    "x-api-key header."
                ),
            },
        )

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        customer_id = _resolve_customer(x_api_key)
        if customer_id is None:
            return _error(
                req_id,
                -32001,
                "Unauthorized: send a valid x-api-key header with every tools/call request.",
            )

        name = params.get("name")
        args = params.get("arguments") or {}

        if name == "get_usage_stats":
            try:
                if os.path.exists("usage_log.json"):
                    with open("usage_log.json") as f:
                        logs = json.load(f)
                    stats = {"total_handoffs": len(logs), "recent": logs[-5:]}
                else:
                    stats = {"total_handoffs": 0, "recent": []}
                return _tool_text(req_id, json.dumps(stats, indent=2))
            except Exception as e:
                logging.error(f"[MCP] get_usage_stats failed: {e}")
                return _tool_text(req_id, f"Could not read usage stats: {e}", is_error=True)

        if name == "handoff":
            message = args.get("message")
            next_agent = args.get("next_agent")

            # --- validation (mirrors HandoffRequest's validators) ------------
            if message is None or (isinstance(message, str) and not message.strip()):
                return _tool_text(req_id, "'message' must not be empty.", is_error=True)
            if not isinstance(next_agent, str) or not next_agent.strip():
                return _tool_text(req_id, "'next_agent' must be a non-empty string.", is_error=True)
            next_agent = next_agent.strip()
            if len(next_agent) > 128:
                return _tool_text(req_id, "'next_agent' too long (max 128 chars).", is_error=True)
            try:
                if len(json.dumps(message, default=str)) > MAX_MESSAGE_BYTES:
                    return _tool_text(req_id, "'message' exceeds the 256 KB limit.", is_error=True)
            except Exception:
                return _tool_text(req_id, "'message' is not JSON-serializable.", is_error=True)

            try:
                result = await process_handoff(_HandoffRequest(message, next_agent))
            except ValueError as e:
                return _tool_text(req_id, str(e), is_error=True)
            except Exception as e:
                logging.error(f"[MCP] handoff failed: {e}")
                return _tool_text(req_id, "Internal error processing handoff.", is_error=True)

            handoff_id = result["handoff_id"]

            # Usage logging must never break a handoff.
            total = 1
            try:
                count = record_usage(handoff_id, next_agent, True)
                if isinstance(count, int):
                    total = count
            except Exception as e:
                logging.warning(f"[MCP] usage logging failed (non-fatal): {e}")

            # --- Billing (same contract as REST /handoff) --------------------
            billing_result = {"billed": False, "status": "not_billable", "error": None}
            try:
                billing_result = record_billing(handoff_id, customer_id or None)
                if not isinstance(billing_result, dict):
                    billing_result = {
                        "billed": bool(billing_result),
                        "status": "billed" if billing_result else "failed",
                        "error": None,
                    }
            except Exception as e:
                logging.error(f"[MCP] record_billing() raised unexpectedly: {e}")
                billing_result = {"billed": False, "status": "failed", "error": str(e)}

            if billing_result.get("status") == "failed":
                logging.error(
                    f"[BILLING] MCP handoff {handoff_id} served but NOT billed "
                    f"(customer={customer_id}): {billing_result.get('error')}"
                )

            payload = {
                "success": True,
                "cleaned_message": result["cleaned_message"],
                "enriched_metadata": {
                    **result["enriched_metadata"],
                    "billing_status": billing_result.get("status"),
                },
                "next_agent": result["next_agent"],
                "handoff_id": handoff_id,
                "timestamp": result["timestamp"].isoformat(),
                "total_handoffs": total,
            }
            return _tool_text(req_id, json.dumps(payload, indent=2, default=str))

        return _error(req_id, -32602, f"Unknown tool: {name}")

    return _error(req_id, -32601, f"Method not found: {method}")
