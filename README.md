# Agent Handoff

pip install -e .

from agent_handoff import handoff

result = handoff(
    message=your_agent_output,
    next_agent="next_agent_name",
    api_key="your-key"
)
