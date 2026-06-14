from app.state import AgentFinding, CashGuardState,OrderLine
from app.utils import find_one, load_json
from app.llm import call_gemini_json

def intake_agent(state: CashGuardState) -> CashGuardState:
    if state.order.lines:
        issues = []
        for line in state.order.lines:
            if line.quantity <= 0:
                issues.append(f"{line.sku}: quantity must be positive")
            if line.unit_price <= 0:
                issues.append(f"{line.sku}: unit_price must be positive")

        confidence = 1.0 if not issues else 0.5
        summary = (
            "Order lines already structured; passthrough validated."
            if not issues
            else f"Structured order has issues: {', '.join(issues)}"
        )

        state.findings.append(
            AgentFinding(
                agent="intake_agent",
                summary=summary,
                confidence=confidence,
                data={
                    "mode": "structured_passthrough",
                    "issues": issues
                },
            )
        )
        return state
    
    else:
        customers=load_json("customers.json")
        
        prompt = (
            "Extract order details from this email. "
            "Respond with JSON only, no markdown fences, no explanation. "
            "Use exactly this shape:\n"
            "{\n"
            '  "customer_name": "...",\n'
            '  "po_number": "...",\n'
            '  "lines": [{"sku": "...", "quantity": 0, "unit_price": 0.0}],\n'
            '  "requested_delivery_date": "YYYY-MM-DD",\n'
            '  "confidence": 0.0\n'
            "}\n\n"
            # confidence = how unambiguous the email was (1.0 = crystal clear, 0.0 = total guess)
            "Set confidence between 0 and 1 based on how clearly the email states the order details.\n\n"
            f"Email:\n{state.order.raw_text}"
        )

        extracted = call_gemini_json(prompt)

        if "error" in extracted:
            state.findings.append(
                AgentFinding(
                    agent="intake_agent",
                    summary="Failed to extract order details from email. Manual review needed.",
                    confidence=0.0,
                    data={
                        "mode": "gemini_extracted",
                        "error": extracted,
                        "raw_text": state.order.raw_text,
                    },
                )
            )
            return state
        
        extracted_customer_name = extracted.get("customer_name")
        customer = find_one(customers, "customer_name", extracted_customer_name)
        
        if customer:
            state.order.customer_id = customer["customer_id"]
            state.order.customer_name = customer["customer_name"]
        
        state.order.lines = [OrderLine(**line) for line in extracted["lines"]]
        if extracted.get("po_number"):
            state.order.po_number = extracted["po_number"]
        if extracted.get("requested_delivery_date"): 
            state.order.requested_delivery_date = extracted["requested_delivery_date"]
        
        confidence = float(extracted.get("confidence", 0.75))

        state.findings.append(
            AgentFinding(
                agent="intake_agent",
                summary="Order details extracted from email via Gemini.",
                confidence=confidence,
                data={
                    "mode": "gemini_extraction",
                    "extracted": extracted,
                    "customer_resolved": customer is not None,
                },
            )
        )
        return state