from datetime import datetime, timezone
from app.state import CashGuardState

def audit_agent(state: CashGuardState) -> CashGuardState:
    timestamp = datetime.now(timezone.utc).isoformat()

    state.audit_log.append(
        f"{timestamp} | order={state.order.order_id} | "
        f"credit={state.credit_status} | pricing={state.pricing_status} | "
        f"inventory={state.inventory_status} | next_action={state.next_action}"
    )

    return state