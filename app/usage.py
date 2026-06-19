import json
import os
from datetime import datetime

USAGE_LOG = "usage_log.json"

def record_usage(handoff_id: str, next_agent: str, success: bool):
    usage = {
        "timestamp": datetime.utcnow().isoformat(),
        "handoff_id": handoff_id,
        "next_agent": next_agent,
        "success": success
    }

    if os.path.exists(USAGE_LOG):
        with open(USAGE_LOG, "r") as f:
            logs = json.load(f)
    else:
        logs = []

    logs.append(usage)

    with open(USAGE_LOG, "w") as f:
        json.dump(logs, f, indent=2)

    return len(logs)
