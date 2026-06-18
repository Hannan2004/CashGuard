from pathlib import Path 

from app.llm import call_gemini_json
from app.state import AgentFinding, CashGuardState 
from app.utils import find_one, load_json 

def recommendation_agent(state: CashGuardState) -> CashGuardState:
    """
    Recommendation Agent

    Purpose:
    Combine findings from all previous agents and ask Gemini what action should be taken.

    This is the AI reasoning layer of CashGuard. 
    """

    policy_file = Path(__file__).parent.parent / "data" / "policy.txt"

    if policy_file.exists():
        policy_text = policy_file.read_text(encoding="utf-8")
    else:
        policy_text = "No policy document found."
    
    customer_memory = None

    try:
        memory_records = load_json("memory.json")

        customer_memory = find_one(
            memory_records,
            "customer_id",
            state.order.customer_id,
        )
    except FileNotFoundError:
        pass

    findings_text = []

    for finding in findings_text:
        findings_text.append(
            {
                "agent": finding.agent,
                "summary": finding.summary,
                "confidence": finding.confidence,
                "data": finding.data,
            }
        )
    
    prompt = f"""
You are a finance operations recommendation engine.

POLICIES:
{policy_text}

CUSTOMER MEMORY:
{customer_memory}

ORDER ID:
{state.order.order_id}

CUSTOMER:
{state.order.customer_name}

RISK SCORE:
{state.risk_score}

RISK LEVEL:
{state.risk_level}

AGENT FINDINGS:
{findings_text}

Return ONLY valid JSON.

{{
    "recommended_action": "auto_invoice",
    "reason": "Short explanation",
    "policy_references": [],
    "human_approval_required": false,
    "confidence": 0.95
}}
"""
    
    recommendation = call_gemini_json(prompt)

    if "error" in recommendation:
        statuses = [
            state.credit_status,
            state.pricing_status,
            state.inventory_status,
        ]

        requires_review = "needs_human_review" in statuses

        recommendation = {
            "recommended_action": (
                "route_to_human_review"
                if requires_review 
                else "auto_invoice"
            ),
            "reason": "Fallback recommendation because Gemini returned invalid JSON.",
            "policy_references": [],
            "human_approval_required": requires_review,
            "confidence": 0.50,
        }
    
    state.recommendation = recommendation 

    state.findings.append(
        AgentFinding(
            agent="recommendation_agent",
            summary=recommendation.get("reason", ""),
            confidence=recommendation.get("confidence", ""),
            data=recommendation,
        )
    )

    return state
    
