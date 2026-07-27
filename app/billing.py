import json
import logging
import os
import threading
from datetime import datetime, timezone

import httpx
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Durable audit trail for billing events that did NOT succeed. A handoff must
# never fail because billing failed, but a failed charge must never vanish
# silently either -- this is the reconciliation record.
#
# Primary store: Supabase (public.billing_failures) -- survives redeploys,
# unlike Railway's ephemeral container disk. Falls back to a local JSONL
# file (same pattern as usage_log.json) if Supabase isn't configured or the
# write fails, so nothing is lost either way.
FAILURE_LOG_PATH = os.getenv("BILLING_FAILURE_LOG", "billing_failures.jsonl")
_failure_log_lock = threading.Lock()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
_supabase_configured = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)

key_status = "loaded" if stripe.api_key else "MISSING"
key_preview = f"{stripe.api_key[:12]}..." if stripe.api_key else "None"
logging.info(f"[BILLING] Stripe key: {key_status} ({key_preview})")
logging.info(f"[BILLING] Meter event: {os.getenv('STRIPE_METER_EVENT', 'agent_handoff')}")
logging.info(f"[BILLING] Supabase audit log: {'configured' if _supabase_configured else 'NOT configured (falling back to local file)'}")


def _record_failure(reason: str, handoff_id: str, customer_id: str = None, detail: str = ""):
    """Record a failed/skipped billing attempt so it can be reconciled
    later, even if nobody was watching stdout when it happened. Tries
    Supabase first (durable across redeploys); always also writes the local
    JSONL file as a belt-and-suspenders fallback. Never raises -- a broken
    audit log must not break billing.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "handoff_id": handoff_id,
        "customer_id": customer_id,
        "reason": reason,
        "detail": detail,
    }

    if _supabase_configured:
        try:
            resp = httpx.post(
                f"{SUPABASE_URL}/rest/v1/billing_failures",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json={
                    "handoff_id": handoff_id,
                    "customer_id": customer_id,
                    "reason": reason,
                    "detail": detail,
                },
                timeout=5.0,
            )
            if resp.status_code >= 300:
                logging.error(f"[BILLING] Supabase audit write failed ({resp.status_code}): {resp.text}")
            else:
                return  # Supabase write succeeded -- skip the local fallback.
        except Exception as sb_err:
            logging.error(f"[BILLING] Supabase audit write raised: {sb_err}")

    # Local fallback -- runs if Supabase isn't configured, or its write failed above.
    try:
        with _failure_log_lock:
            with open(FAILURE_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
    except Exception as log_err:
        logging.error(f"[BILLING] Could not write failure audit log: {log_err}")


def record_billing(handoff_id: str, customer_id: str = None):
    """Record one metered usage event against a specific Stripe customer.

    customer_id takes precedence; falls back to STRIPE_CUSTOMER_ID env for
    single-tenant/backward-compat. Stays in demo mode (no charge) if either the
    Stripe key or the customer is missing -- that's an expected, logged
    no-op, not a failure.

    Returns a dict: {"billed": bool, "status": "billed" | "demo" | "failed", "error": str | None}
    A handoff must always succeed regardless of this result -- callers should
    NOT raise on a False/failed billed status. They should, however, surface
    it loudly (see main.py) rather than discard it.
    """
    try:
        key = os.getenv("STRIPE_SECRET_KEY")
        if not key:
            logging.warning(f"[BILLING] Demo mode - STRIPE_SECRET_KEY not set. handoff: {handoff_id}")
            _record_failure("demo_mode_no_key", handoff_id, customer_id)
            return {"billed": False, "status": "demo", "error": None}

        stripe.api_key = key
        customer_id = customer_id or os.getenv("STRIPE_CUSTOMER_ID")
        if not customer_id:
            logging.warning(f"[BILLING] Demo mode - no customer id. handoff: {handoff_id}")
            _record_failure("demo_mode_no_customer", handoff_id, customer_id)
            return {"billed": False, "status": "demo", "error": None}

        event_name = os.getenv("STRIPE_METER_EVENT", "agent_handoff")

        stripe.billing.MeterEvent.create(
            event_name=event_name,
            payload={
                "value": "1",
                "stripe_customer_id": customer_id,
            },
        )
        logging.info(f"[BILLING] Recorded meter event '{event_name}' for {customer_id}: {handoff_id}")
        return {"billed": True, "status": "billed", "error": None}

    except Exception as e:
        # This is the case that used to vanish: a real Stripe failure (bad
        # customer id, expired key, API outage) with a live key configured.
        # Log LOUD, write it to the durable audit trail, and tell the caller
        # honestly that the charge did not go through.
        error_msg = f"{type(e).__name__}: {e}"
        logging.error(
            f"[BILLING ERROR] Charge FAILED for handoff {handoff_id} "
            f"(customer={customer_id}): {error_msg}"
        )
        _record_failure("stripe_error", handoff_id, customer_id, error_msg)
        return {"billed": False, "status": "failed", "error": error_msg}