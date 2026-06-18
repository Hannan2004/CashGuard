from langgraph.types import interrupt 
from app.state import CashGuardState 

def human_review_agent(state: CashGuardState) -> CashGuardState:
    """
    Pause execution and wait for a human decision.
    """

    review_request = {
        "order_id": state.order.order_id,
        "customer": state.order.customer_name,
        "reason": state.human_decision.reason,
        "risk_level": state.risk_level,
        "recommendation": state.recommendation
    }

    decision = interrupt(review_request)

    state.human_decision.status = (
        "approved"
        if decision["approved"]
        else "rejected"
    )

    state.human_decision.approved_by = (
        decision.get("approved_by")
    )

    state.human_decision.comments = (
        decision.get("comments")
    )

    return state