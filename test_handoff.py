from sdk.agent_handoff import handoff

# Test with fake API key (we'll improve auth later)
result = handoff(
    message={"task": "research quantum computing", "data": "some raw output here"},
    next_agent="writer",
    api_key="test-key-12345"
)

print("✅ Handoff successful!")
print(result)
