# Agent Handoff

pip install -e .

from agent_handoff import handoff

result = handoff(
    message=your_agent_output,
    next_agent="next_agent_name",
    api_key="your-key"
)

## Pricing

- **.001 per handoff** (1 cent per 10 handoffs)
- High-volume friendly
- Billed via Stripe usage-based metering

Free tier available for testing (limited handoffs).


## Pricing

**Usage-based**: .001 per handoff

- High-volume friendly
- Billed via Stripe
- 1 cent per 10 handoffs

**Subscription Tier** (coming soon): Higher limits + priority support

