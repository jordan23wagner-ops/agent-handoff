import stripe
import os
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

def record_billing(handoff_id: str):
    """
    Record a billable handoff.
    Requires:
    1. Stripe account
    2. A Billing Meter created in Stripe Dashboard (event name = agent_handoff)
    3. Customer ID mapped to API key (we'll improve this later)
    """
    try:
        key = os.getenv("STRIPE_SECRET_KEY")
        
        if not key or "sk_test" not in key:
            print(f"[BILLING] Demo mode → handoff: {handoff_id}")
            return True

        # Record metered usage
        stripe.billing.MeterEvent.create(
            event_name=os.getenv("STRIPE_METER_EVENT", "agent_handoff"),
            payload={
                "value": "1",
                # TODO: Replace with real customer mapping
                "stripe_customer_id": "cus_placeholder"  
            }
        )
        print(f"[BILLING] ✓ Charged for handoff: {handoff_id}")
        return True

    except Exception as e:
        print(f"[BILLING ERROR] {str(e)}")
        return False
