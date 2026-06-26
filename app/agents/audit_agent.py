from datetime import datetime, timezone

from app.state import AuditEntry, CashGuardState

_AGENT_ACTION_MAP: dict[str, str] = {
    "intake_agent":          "order_parsing",
    "risk_agent":            "credit_check",
    "pricing_agent":         "price_validation",
    "inventory_agent":       "stock_check",
    "recommendation_agent":  "recommendation",
    "invoice_agent":         "invoice_generation",
    "human_review_agent":    "human_review",
    "collections_agent":     "collections_analysis",
    "dispute_agent":         "dispute_analysis",
}


def _decision_for_agent(state: CashGuardState, agent: str) -> str:
    """
    Pick the most relevant DecisionStatus for a given agent by looking at
    the state fields each agent is responsible for.
    """
    if agent == "risk_agent":
        return state.credit_status
    if agent == "pricing_agent":
        return state.pricing_status
    if agent == "inventory_agent":
        return state.inventory_status
    if agent == "invoice_agent":
        return state.next_action or "invoice_generated"
    if agent == "human_review_agent":
        return state.human_decision.status
    if agent == "recommendation_agent":
        rec = state.recommendation or {}
        return rec.get("recommended_action", "pending")
    # intake, collections, dispute — derive from their finding summary
    return "completed"


def audit_agent(state: CashGuardState) -> CashGuardState:
    """
    Build one structured AuditEntry for every agent finding recorded so far,
    then attach them all to state.audit_log.

    This node runs at the end of the pipeline so every upstream finding is
    already present in state.findings.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    case_id   = state.order.order_id

    # The human approver is only known after human_review_agent runs.
    human_approver = state.human_decision.approved_by or None

    new_entries: list[AuditEntry] = []

    for finding in state.findings:
        agent_name = finding.agent
        action     = _AGENT_ACTION_MAP.get(agent_name, agent_name)
        decision   = _decision_for_agent(state, agent_name)

        entry = AuditEntry(
            timestamp      = timestamp,
            case_id        = case_id,
            agent          = agent_name,
            action         = action,
            decision       = decision,
            reason         = finding.summary,
            confidence     = finding.confidence,
            human_approver = human_approver if agent_name == "human_review_agent" else None,
        )
        new_entries.append(entry)

    # Append to whatever was already in the log (supports re-runs / partial graphs).
    state.audit_log.extend(new_entries)

    return state