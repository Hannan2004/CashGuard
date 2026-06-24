from datetime import date, datetime
from typing import Any

from app.utils import find_one, load_json


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

CollectionRecommendation = dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_overdue(due_date_str: str) -> int:
    """Return how many days past the due date today is. 0 if not yet overdue."""
    due = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    delta = date.today() - due
    return max(0, delta.days)


def _has_open_dispute(invoice_id: str, disputes: list[dict]) -> bool:
    """Return True if the invoice has at least one open dispute record."""
    return any(
        d["invoice_id"] == invoice_id and d["status"] == "open"
        for d in disputes
    )


def _recommend_action(
    days: int,
    payment_risk: str,
    dispute_history: str,
    has_dispute: bool,
    amount_due: float,
) -> tuple[str, str, float]:
    """
    Apply policy rules and return (action, reason, confidence).

    Policy (from policy.txt):
    - Urgent follow-up for 15+ days overdue.
    - Write-off consideration at 90+ days.
    - High-risk customers with disputes are escalated regardless of age.
    """

    # Active dispute on this specific invoice → escalate to sales/finance.
    if has_dispute:
        return (
            "escalate",
            (
                "Invoice has an open dispute. Escalate to sales or finance "
                "for resolution before any collections action."
            ),
            0.93,
        )

    # 90+ days — write-off territory.
    if days >= 90:
        return (
            "write_off_review",
            (
                f"Invoice is {days} days overdue. "
                "Refer to finance for write-off review per collections policy."
            ),
            0.90,
        )

    # High-risk customer with a history of disputes AND 15+ days overdue.
    if days >= 15 and payment_risk == "high" and dispute_history == "frequent":
        return (
            "escalate",
            (
                f"Invoice is {days} days overdue. Customer is high-risk with "
                "a frequent dispute history. Escalate to senior collections team."
            ),
            0.88,
        )

    # 15+ days overdue — urgent follow-up.
    if days >= 15:
        return (
            "urgent_follow_up",
            (
                f"Invoice is {days} days overdue. "
                "Send urgent payment reminder and initiate phone follow-up."
            ),
            0.85,
        )

    # Overdue but under 15 days — standard reminder.
    return (
        "standard_reminder",
        (
            f"Invoice is {days} days overdue. "
            "Send standard payment reminder email."
        ),
        0.80,
    )

def analyze_invoice(invoice: dict) -> CollectionRecommendation:
    """
    Analyse a single invoice and return a structured collections recommendation.
    Only meaningful for invoices with status == 'overdue'; others are noted
    but not actioned.
    """
    customers = load_json("customers.json")
    disputes = load_json("disputes.json")
    payments = load_json("payments.json")

    customer = find_one(customers, "customer_id", invoice["customer_id"])
    payment_risk = customer["payment_risk"] if customer else "unknown"
    dispute_history = customer["dispute_history"] if customer else "unknown"

    # Sum any partial payments already recorded against this invoice.
    total_paid = sum(
        p["amount"]
        for p in payments
        if p["invoice_id"] == invoice["invoice_id"]
    )
    outstanding = invoice["amount_due"] - total_paid

    days = _days_overdue(invoice["due_date"])
    has_dispute = _has_open_dispute(invoice["invoice_id"], disputes)

    action, reason, confidence = _recommend_action(
        days=days,
        payment_risk=payment_risk,
        dispute_history=dispute_history,
        has_dispute=has_dispute,
        amount_due=outstanding,
    )

    return {
        "invoice_id": invoice["invoice_id"],
        "customer_id": invoice["customer_id"],
        "customer_name": invoice["customer_name"],
        "status": invoice["status"],
        "amount_due": invoice["amount_due"],
        "amount_paid": total_paid,
        "outstanding": outstanding,
        "due_date": invoice["due_date"],
        "days_overdue": days,
        "payment_risk": payment_risk,
        "dispute_history": dispute_history,
        "has_open_dispute": has_dispute,
        "recommended_action": action,
        "reason": reason,
        "confidence": confidence,
    }


def run_collections(invoice_id: str | None = None) -> list[CollectionRecommendation]:
    """
    Run collections analysis.

    - If invoice_id is provided, analyse that single invoice (any status).
    - Otherwise, analyse all invoices whose status is 'overdue'.
    """
    invoices = load_json("invoices.json")

    if invoice_id is not None:
        target = find_one(invoices, "invoice_id", invoice_id)
        if target is None:
            return []
        return [analyze_invoice(target)]

    overdue = [inv for inv in invoices if inv["status"] == "overdue"]
    return [analyze_invoice(inv) for inv in overdue]