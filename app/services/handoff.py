import uuid
from datetime import datetime
from typing import Any, Dict

def clean_message(message: Any) -> Any:
    if isinstance(message, dict):
        cleaned = {}
        for k, v in message.items():
            if v is not None:
                if isinstance(v, str):
                    v = v.strip()
                cleaned[k] = v
        return cleaned
    elif isinstance(message, str):
        return message.strip()
    return message

def enrich_metadata(message: Any, next_agent: str, handoff_id: str) -> Dict:
    return {
        "handoff_id": handoff_id,
        "processed_at": datetime.utcnow().isoformat(),
        "next_agent": next_agent,
        "original_type": type(message).__name__,
        "estimated_tokens": len(str(message)) // 4 if message else 0
    }

async def process_handoff(request) -> Dict:
    handoff_id = str(uuid.uuid4())

    cleaned_message = clean_message(request.message)

    if not cleaned_message:
        raise ValueError("Message is empty after cleaning")

    enriched = enrich_metadata(cleaned_message, request.next_agent, handoff_id)

    return {
        "success": True,
        "cleaned_message": cleaned_message,
        "enriched_metadata": enriched,
        "next_agent": request.next_agent,
        "handoff_id": handoff_id,
        "timestamp": datetime.utcnow()
    }
