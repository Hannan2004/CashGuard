"""
Recommendation Agent
====================
Combines findings from all previous agents and asks Gemini what action
should be taken. Also sets human_decision fields on state so the routing
function in graph.py stays read-only.
"""

from pathlib import Path

from app.llm import call_gemini_json
from app.state import AgentFinding, CashGuardState
from app.utils import find_one, load_json


def recommendation_agent(state: CashGuardState) -> CashGuardState:
    # ------------------------------------------------------------------
    # 1. Load policy document
    # ------------------------------------------------------------------
    policy_file = Path(__file__).parent.parent / "data" / "policy.txt"
    policy_text = (
        policy_file.read_text(encoding="utf-8")
        if policy_file.exists()
        else "No policy document found."
    )

    # ------------------------------------------------------------------
    # 2. Load customer memory (if available)
    # ------------------------------------------------------------------
    customer_memory = None
    try:
        memory_records = load_json("memory.json")
        customer_memory = find_one(memory_records, "customer_id", state.order.customer_id)
    except FileNotFoundError:
        pass

    # ------------------------------------------------------------------
    # 3. Serialise upstream findings  ← BUG FIX: was iterating findings_text
    #    (empty list) instead of state.findings
    # ------------------------------------------------------------------
    findings_text = [
        {
            "agent":      f.agent,
            "summary":    f.summary,
            "confidence": f.confidence,
            "data":       f.data,
        }
        for f in state.findings
    ]

    # ------------------------------------------------------------------
    # 4. Ask Gemini
    # ------------------------------------------------------------------
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

CREDIT STATUS:  {state.credit_status}
PRICING STATUS: {state.pricing_status}
INVENTORY STATUS: {state.inventory_status}

AGENT FINDINGS:
{findings_text}

Return ONLY valid JSON — no markdown fences, no extra text.

{{
    "recommended_action": "auto_invoice",
    "reason": "Short explanation",
    "policy_references": [],
    "human_approval_required": false,
    "confidence": 0.95
}}
"""

    recommendation = call_gemini_json(prompt)

    # ------------------------------------------------------------------
    # 5. Fallback if Gemini returns garbage
    # ------------------------------------------------------------------
    if "error" in recommendation:
        statuses      = [state.credit_status, state.pricing_status, state.inventory_status]
        requires_review = "needs_human_review" in statuses

        recommendation = {
            "recommended_action": "route_to_human_review" if requires_review else "auto_invoice",
            "reason":             "Fallback recommendation — Gemini returned invalid JSON.",
            "policy_references":  [],
            "human_approval_required": requires_review,
            "confidence":         0.50,
        }

    # ------------------------------------------------------------------
    # 6. Write recommendation to state
    #    Also set human_decision fields here so graph.py routing stays
    #    read-only (LangGraph silently discards mutations in edge fns).
    # ------------------------------------------------------------------
    state.recommendation = recommendation

    if recommendation.get("human_approval_required"):
        state.human_decision.required = True
        state.human_decision.reason   = recommendation.get(
            "reason", "Recommendation agent requested review."
        )

    # Mirror next_action for any downstream consumer
    state.next_action = (
        "needs_human_review"
        if recommendation.get("human_approval_required")
        else recommendation.get("recommended_action", "auto_invoice")
    )

    state.findings.append(
        AgentFinding(
            agent      = "recommendation_agent",
            summary    = recommendation.get("reason", ""),
            confidence = float(recommendation.get("confidence", 0.5)),
            data       = recommendation,
        )
    )

    return state