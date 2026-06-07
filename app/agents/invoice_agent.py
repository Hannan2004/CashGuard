from app.state import AgentFinding, CashGuardState
from app.utils import load_json

def invoice_agent(state: CashGuardState) -> CashGuardState:
    state.invoice_id = f"INV-{state.order.order_id.replace('ORD-', '')}"

    state.findings.append(
        AgentFinding(
            agent="invoice_agent",
            summary="Invoice was generated for the approved order.",
            confidence=0.98,
            data={"invoice_id": state.invoice_id},
        )
    )

    state.next_action = "invoice_generated"

    return state