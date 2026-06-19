from langgraph.types import interrupt 
from app.state import CashGuardState 
from app.case_store import upsert_case 

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
    
    upsert_case(
        state.order.order_id,
        "awaiting_human_review"
    )
    decision = interrupt(review_request)

    if decision["approved"]:
        state.human_decision.status = "approved"
    
    else:
        state.human_decision.status = "rejected"
        state.next_action = "blocked_by_human"

    state.human_decision.approved_by = (
        decision.get("approved_by")
    )

    state.human_decision.comments = (
        decision.get("comments")
    )

    return state