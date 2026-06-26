"""
Human Review Agent
==================
Pauses the LangGraph pipeline via interrupt() and waits for a human
approve/reject decision via the REST API.

On entering this node (before interrupt):
  1. Calculates order total from order lines
  2. Collects a risk summary from upstream findings
  3. Fires a Slack notification to SLACK_APPROVALS_CHANNEL with full
     context and ready-to-paste curl commands for approve/reject
  4. Marks the case as "awaiting_human_review" in the case store

On resume (after human posts to /cases/{id}/approve or /cases/{id}/reject):
  5. Updates human_decision status, approved_by, and comments
"""

from langgraph.types import interrupt

from app.case_store import upsert_case
from app.slack_helper import post_human_review_alert
from app.state import CashGuardState


def _compute_order_total(state: CashGuardState) -> float:
    """Sum quantity * unit_price across all order lines."""
    return sum(line.quantity * line.unit_price for line in state.order.lines)


def _build_risk_summary(state: CashGuardState) -> str:
    """
    Collect the summaries from risk, pricing, and inventory findings
    into a single human-readable string for the Slack message.
    """
    relevant_agents = {"risk_agent", "pricing_agent", "inventory_agent", "recommendation_agent"}
    lines: list[str] = []

    for finding in state.findings:
        if finding.agent in relevant_agents:
            lines.append(f"• [{finding.agent}] {finding.summary}")

    return "\n".join(lines) if lines else "No detailed summary available."


def human_review_agent(state: CashGuardState) -> CashGuardState:
    """
    Pause execution and wait for a human decision.
    Sends a Slack alert before interrupting.
    """
    order_total  = _compute_order_total(state)
    risk_summary = _build_risk_summary(state)

    post_human_review_alert(
        order_id      = state.order.order_id,
        customer_name = state.order.customer_name,
        order_total   = order_total,
        risk_level    = state.risk_level,
        risk_summary  = risk_summary,
    )

    review_request = {
        "order_id":       state.order.order_id,
        "customer":       state.order.customer_name,
        "order_total":    order_total,
        "reason":         state.human_decision.reason,
        "risk_level":     state.risk_level,
        "risk_summary":   risk_summary,
        "recommendation": state.recommendation,
    }

    upsert_case(state.order.order_id, "awaiting_human_review")

    decision = interrupt(review_request)

    if decision.get("approved"):
        state.human_decision.status = "approved"
    else:
        state.human_decision.status = "rejected"
        state.next_action = "blocked_by_human"

    state.human_decision.approved_by = decision.get("approved_by")
    state.human_decision.comments    = decision.get("comments")

    return state