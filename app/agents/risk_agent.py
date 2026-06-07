from app.state import AgentFinding, CashGuardState
from app.utils import find_one, load_json

def risk_agent(state: CashGuardState) -> CashGuardState:
    customers = load_json("customers.json")
    customer = find_one(customers, "customer_id", state.order.customer_id)

    if customer is None:
        state.credit_status = "blocked"
        state.risk_level = "high"
        state.risk_score = 1.0
        state.findings.append(
            AgentFinding(
                agent="risk_agent",
                summary="Customer was not found in customer master data.",
                confidence=0.95,
            )
        )
        return state
    
    credit_limit = float(customer["credit_limit"])
    open_balance = float(customer["open_balance"])
    order_total = sum(line.quantity * line.unit_price for line in state.order.lines)

    projected_balance = open_balance + order_total
    utilization = projected_balance / credit_limit if credit_limit > 0 else 1.0

    if customer["payment_risk"] == "high" or utilization > 0.95:
        state.credit_status = "needs_human_review"
        state.risk_level = "high"
        state.risk_score = min(1.0, utilization)
        summary = "Order requires finance review due to high payment risk or credit utilization."
    elif utilization > 0.75:
        state.credit_status = "needs_human_review"
        state.risk_level = "medium"
        state.risk_score = utilization
        summary = "Order is close to credit limit and should be reviewed."
    else:
        state.credit_status = "auto_approved"
        state.risk_level = "low"
        state.risk_score = utilization
        summary = "Customer credit profile is acceptable for auto-approval."
    
    state.findings.append(
        AgentFinding(
            agent="risk_agent",
            summary=summary,
            confidence=0.9,
            data={
                "credit_limit": credit_limit,
                "open_balance": open_balance,
                "order_total": order_total,
                "projected_balance": projected_balance,
                "utilization": utilization,
            },
        )
    )

    return state