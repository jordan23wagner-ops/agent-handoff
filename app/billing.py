import stripe
import os
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

def record_billing(handoff_id: str):
    try:
        if not stripe.api_key or "sk_test" not in stripe.api_key:
            print(f"[BILLING] Demo mode - handoff: {handoff_id}")
            return True

        customer_id = os.getenv("STRIPE_CUSTOMER_ID", "cus_placeholder")

        stripe.billing.MeterEvent.create(
            event_name=os.getenv("STRIPE_METER_EVENT", "agent_handoff"),
            payload={
                "value": "1",
                "stripe_customer_id": customer_id
            }
        )
        print(f"[BILLING] ✓ Recorded handoff for customer {customer_id}: {handoff_id}")
        return True

    except Exception as e:
        print(f"[BILLING ERROR] {e}")
        return False
