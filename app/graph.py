from langgraph.graph import END, StateGraph

from app.agents.audit_agent import audit_agent
from app.agents.inventory_agent import inventory_agent
from app.agents.invoice_agent import invoice_agent
from app.agents.pricing_agent import pricing_agent
from app.agents.risk_agent import risk_agent
from app.state import CashGuardState

def route_after_checks(state: CashGuardState) -> str:
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
        state.human_decision.reason = "One or more checks require human approval."
        return "audit"
    
    return "invoice"

def build_graph():
    graph = StateGraph(CashGuardState)

    graph.add_node("risk", risk_agent)
    graph.add_node("pricing", pricing_agent)
    graph.add_node("inventory", inventory_agent)
    graph.add_node("invoice", invoice_agent)
    graph.add_node("audit", audit_agent)

    graph.set_entry_point("risk")

    graph.add_edge("risk", "pricing")
    graph.add_edge("pricing", "inventory")

    graph.add_conditional_edges(
        "inventory",
        route_after_checks,
        {
            "invoice": "invoice",
            "audit": "audit",
        },
    )

    graph.add_edge("invoice", "audit")
    graph.add_edge("audit", END)

    return graph.compile()