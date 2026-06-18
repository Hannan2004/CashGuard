from langgraph.graph import END, StateGraph

from app.agents.audit_agent import audit_agent
from app.agents.intake_agent import intake_agent
from app.agents.inventory_agent import inventory_agent
from app.agents.invoice_agent import invoice_agent
from app.agents.pricing_agent import pricing_agent
from app.agents.recommendation_agent import recommendation_agent
from app.agents.risk_agent import risk_agent
from app.agents.human_review_agent import human_review_agent 
from app.state import CashGuardState
from app.checkpointer import checkpointer

def route_after_recommendation(state: CashGuardState) -> str:
    recommendation = state.recommendation or {}

    if recommendation.get("human_approval_required"):
        state.next_action = "needs_human_review"
        state.human_decision.required = True
        state.human_decision.reason = recommendation.get(
            "reason",
            "Recommendation agent requested review.",
        )

        return "human_review"
    
    statuses = [
        state.credit_status,
        state.pricing_status,
        state.inventory_status,
    ]

    if "blocked" in statuses:
        state.next_action = "blocked"
        return "audit"
    
    if "needs_human_review" in statuses:
        state.next_action = "needs_human_review"
        state.human_decision.required = True
        state.human_decision.reason = (
            "One or more checks require human approval."
        )

        return "human_review"
    
    return "invoice"

def route_after_human_review(state: CashGuardState) -> str:
    if (
        state.human_decision.status == "approved"
    ): 
        return "invoice"
    
    return "audit"

def build_graph():
    graph = StateGraph(CashGuardState)
    
    graph.add_node("intake", intake_agent)
    graph.add_node("risk", risk_agent)
    graph.add_node("pricing", pricing_agent)
    graph.add_node("inventory", inventory_agent)
    graph.add_node("invoice", invoice_agent)
    graph.add_node("audit", audit_agent)
    graph.add_node("recommendation", recommendation_agent)
    graph.add_node("human_review", human_review_agent)

    graph.set_entry_point("intake")
    
    graph.add_edge("intake", "risk")
    graph.add_edge("risk", "pricing")
    graph.add_edge("pricing", "inventory")
    graph.add_edge("inventory", "recommendation")
    graph.add_conditional_edges(
        "recommendation",
        route_after_recommendation,
        {
            "invoice": "invoice",
            "human_review": "human_review",
        },
    )
    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "invoice": "invoice",
            "audit": "audit"
        },
    )
    graph.add_edge("invoice", "audit")
    graph.add_edge("audit", END)

    return graph.compile(
        checkpointer=checkpointer
    )