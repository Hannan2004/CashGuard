from app.state import AgentFinding, CashGuardState
from app.utils import load_json

def inventory_agent(state: CashGuardState) -> CashGuardState:
    inventory = load_json("inventory.json")
    shortages = []

    for line in state.order.lines:
        item = next((row for row in inventory if row["sku"] == line.sku), None)

        if item is None:
            shortages.append(
                {
                    "sku": line.sku,
                    "requested": line.quantity,
                    "available": 0,
                    "issue": "SKU was not found in inventory.",
                }
            )
            continue

        available_quantity = int(item["available_quantity"])

        if line.quantity > available_quantity:
            shortages.append(
                {
                    "sku": line.sku,
                    "requested": line.quantity,
                    "available": available_quantity,
                    "issue": "Requested quantity exceeds available stock.",
                }
            )
            
    if shortages:
        state.inventory_status = "needs_human_review"
        summary = "Inventory shortage found. Fulfillment review is required."
        confidence = 0.9
    else:
        state.inventory_status = "auto_approved"
        summary = "Inventory is available for all order lines."
        confidence = 0.95
    
    state.findings.append(
        AgentFinding(
            agent="inventory_agent",
            summary=summary,
            confidence=confidence,
            data={"shortages": shortages},
        )
    )

    return state