from app.state import AgentFinding, CashGuardState
from app.utils import load_json

def pricing_agent(state: CashGuardState) -> CashGuardState:
    contracts = load_json("contracts.json")
    mismatches = []

    for line in state.order.lines:
        contract = next(
            (
                item
                for item in contracts
                if item["customer_id"] == state.order.customer_id and item["sku"] == line.sku
            ),
            None,
        )

        if contract is None:
            mismatches.append(
                {
                    "sku": line.sku,
                    "issue": "No contract price found.",
                    "submitted_price": line.unit_price,
                }
            )
            continue

        contract_price = float(contract["contract_price"])

        if line.unit_price != contract_price:
            mismatches.append(
                {
                    "sku": line.sku,
                    "issue": "Submitted price does not match contract price.",
                    "submitted_price": line.unit_price,
                    "contract_price": contract_price,
                }
            )
        
    if mismatches:
        state.pricing_status = "needs_human_review"
        summary = "Pricing mismatch found. Sales or finance review is required."
        confidence = 0.92
    else:
        state.pricing_status = "auto_approved"
        summary = "Submitted order pricing matches contract terms."
        confidence = 0.95

    state.findings.append(
        AgentFinding(
            agent="pricing_agent",
            summary=summary,
            confidence=confidence,
            data={"mismatches": mismatches},
        )
    )

    return state