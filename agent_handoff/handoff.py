import uuid
from datetime import datetime
from typing import Any, Dict, Optional
import httpx

def handoff(
    message: Any,
    next_agent: str,
    api_key: str,
    base_url: str = "https://agent-handoff-production-573c.up.railway.app"
) -> Dict:
    \"\"\"
    Send a message to the next agent via the Handoff Middleware.

    Args:
        message: The data/payload to send
        next_agent: Name of the next agent in the pipeline
        api_key: Your API key for authentication
        base_url: Base URL of the deployed service

    Returns:
        Response from the handoff service
    \"\"\"
    payload = {
        \"message\": message,
        \"next_agent\": next_agent
    }
    
    headers = {
        \"x-api-key\": api_key,
        \"Content-Type\": \"application/json\"
    }
    
    response = httpx.post(f\"{base_url}/handoff\", json=payload, headers=headers)
    response.raise_for_status()
    return response.json()
