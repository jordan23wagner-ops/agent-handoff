import httpx
from typing import Any, Optional, Dict

class AgentHandoff:
    def __init__(self, api_key: str, base_url: str = "http://127.0.0.1:8000"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30)

    def normalize_and_route(self, message: Any, next_agent: str, context: Optional[Dict] = None):
        payload = {
            "message": message,
            "next_agent": next_agent,
            "context": context
        }
        response = self.client.post(
            f"{self.base_url}/handoff",
            json=payload,
            headers={"X-API-Key": self.api_key}
        )
        response.raise_for_status()
        return response.json()

# Easy function
def handoff(message, next_agent, api_key, base_url="http://127.0.0.1:8000"):
    client = AgentHandoff(api_key, base_url)
    return client.normalize_and_route(message, next_agent)
