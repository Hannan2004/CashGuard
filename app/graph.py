"""
CashGuard LangGraph Pipeline
=============================

Node order:
  intake → risk → pricing → inventory → recommendation
    → [human_review] → invoice → audit → END
    → [blocked]      → audit   → END

IMPORTANT: LangGraph conditional edge functions must be PURELY READ-ONLY.
State mutations inside routing functions are silently discarded.
All state writes happen inside node functions (e.g. recommendation_agent
or the pre-interrupt block of human_review_agent).
"""

from langgraph.graph import END, StateGraph

from app.agents.audit_agent import audit_agent
from app.agents.human_review_agent import human_review_agent
from app.agents.intake_agent import intake_agent
from app.agents.inventory_agent import inventory_agent
from app.agents.invoice_agent import invoice_agent
from app.agents.pricing_agent import pricing_agent
from app.agents.recommendation_agent import recommendation_agent
from app.agents.risk_agent import risk_agent
from app.checkpointer import checkpointer
from app.state import CashGuardState


# ---------------------------------------------------------------------------
# Routing functions — READ ONLY, no state mutations allowed here.
# ---------------------------------------------------------------------------

def route_after_recommendation(state: CashGuardState) -> str:
    """
    Decide what happens after the recommendation agent runs.

    Priority:
      1. Recommendation agent explicitly requests human review.
      2. Any upstream agent set a status of 'needs_human_review'.
      3. Any upstream agent blocked the order.
      4. Otherwise auto-proceed to invoice.

    NOTE: human_decision.required / reason / next_action are set inside
    recommendation_agent (the node), not here.
    """
    recommendation = state.recommendation or {}

    if recommendation.get("human_approval_required"):
        return "human_review"

    statuses = [state.credit_status, state.pricing_status, state.inventory_status]

    if "blocked" in statuses:
        return "audit"

    if "needs_human_review" in statuses:
        return "human_review"

    return "invoice"


def route_after_human_review(state: CashGuardState) -> str:
    """After a human decision, either proceed to invoice or audit (blocked)."""
    if state.human_decision.status == "approved":
        return "invoice"
    return "audit"


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(CashGuardState)

    graph.add_node("intake",         intake_agent)
    graph.add_node("risk",           risk_agent)
    graph.add_node("pricing",        pricing_agent)
    graph.add_node("inventory",      inventory_agent)
    graph.add_node("recommendation", recommendation_agent)
    graph.add_node("human_review",   human_review_agent)
    graph.add_node("invoice",        invoice_agent)
    graph.add_node("audit",          audit_agent)

    graph.set_entry_point("intake")

    graph.add_edge("intake",         "risk")
    graph.add_edge("risk",           "pricing")
    graph.add_edge("pricing",        "inventory")
    graph.add_edge("inventory",      "recommendation")

    graph.add_conditional_edges(
        "recommendation",
        route_after_recommendation,
        {
            "invoice":      "invoice",
            "human_review": "human_review",
            "audit":        "audit",
        },
    )

    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "invoice": "invoice",
            "audit":   "audit",
        },
    )

    graph.add_edge("invoice", "audit")
    graph.add_edge("audit",   END)

    return graph.compile(checkpointer=checkpointer)