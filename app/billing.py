import stripe
import os

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

key_status = "loaded" if stripe.api_key else "MISSING"
key_preview = f"{stripe.api_key[:12]}..." if stripe.api_key else "None"
print(f"[BILLING] Stripe key: {key_status} ({key_preview})")
print(f"[BILLING] Meter event: {os.getenv('STRIPE_METER_EVENT', 'agent_handoff')}")
print(f"[BILLING] Customer ID: {os.getenv('STRIPE_CUSTOMER_ID', 'NOT SET')}")

def record_billing(handoff_id: str):
    try:
        key = os.getenv("STRIPE_SECRET_KEY")
        if not key:
            print(f"[BILLING] Demo mode - STRIPE_SECRET_KEY not set. handoff: {handoff_id}")
            return True

        stripe.api_key = key
        customer_id = os.getenv("STRIPE_CUSTOMER_ID")
        if not customer_id:
            print(f"[BILLING] Demo mode - STRIPE_CUSTOMER_ID not set. handoff: {handoff_id}")
            return True

        event_name = os.getenv("STRIPE_METER_EVENT", "agent_handoff")

        stripe.billing.MeterEvent.create(
            event_name=event_name,
            payload={
                "value": "1",
                "stripe_customer_id": customer_id,
            },
        )
        print(f"[BILLING] Recorded meter event '{event_name}' for {customer_id}: {handoff_id}")
        return True

    except Exception as e:
        print(f"[BILLING ERROR] {type(e).__name__}: {e}")
        return False
