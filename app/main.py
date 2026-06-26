import os
from fastapi import FastAPI, HTTPException

from app.agents.intake_agent import intake_agent
from app.agents.collections_agent import run_collections
from app.agents.dispute_agent import run_disputes
from app.gmail_helper import get_latest_unread_email
from app.graph import build_graph
from app.state import CashGuardState, OrderInput, ReviewRequest
from app.utils import find_one, load_json
from app.case_store import initialize_case_store, upsert_case, list_cases
from langgraph.types import Command

app = FastAPI(title="CashGuard Agentic Order-to-Cash API")

@app.on_event("startup")
def startup():
    initialize_case_store()

GMAIL_LABEL = os.environ.get("GMAIL_LABEL", "CashGuard")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.7"))

cashguard_graph = build_graph()

def validate_pending_review(order_id: str):
    state = cashguard_graph.get_state(
        config={
            "configurable": {
                "thread_id": order_id
            }
        }
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail="Case not found"
        )
    
    workflow = state.values 

    if not workflow["human_decision"]["required"]:
        raise HTTPException(
            status_code=404,
            detail="Human review not required"
        )
    
    if not workflow["human_decision"]["status"] != "pending":
        raise HTTPException(
            status_code=404,
            detail="Case already reviewed"
        )
    
    return state

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/cases/run")
def run_case(order: OrderInput):
    initial_state = CashGuardState(order=order)
    upsert_case(
        order.order_id,
        "running"
    )
    final_state = cashguard_graph.invoke(
        initial_state,
        config={
            "configurable": {
                "thread_id": order.order_id
            }
        }
    )
    return final_state

@app.post("/cases/run/{order_id}")
def run_case_by_order_id(order_id: str):
    orders = load_json("orders.json")
    order = find_one(orders, "order_id", order_id)

    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found")
    
    initial_state = CashGuardState(order=OrderInput(**order))
    upsert_case(
        order["order_id"],
        "running"
    )
    final_state = cashguard_graph.invoke(
        initial_state,
        config={
            "configurable": {
                "thread_id": order["order_id"]
            }
        }
    )

    return final_state

@app.post("/intake/email")
async def intake_from_email():
    email_body = get_latest_unread_email(GMAIL_LABEL)

    if email_body is None:
        raise HTTPException(
            status_code=404,
            detail=f"No unread emails found under Gmail label '{GMAIL_LABEL}'",
        )
   
    order = OrderInput(
        order_id="EMAIL-PENDING",
        customer_id="UNKNOWN",
        customer_name="UNKNOWN",
        lines=[],
        raw_text=email_body
    )

    initial_state=CashGuardState(order=order)
    post_intake_state=intake_agent(initial_state)

    intake_finding = next(
        (f for f in post_intake_state.findings if f.agent == "intake_agent"),
        None,
    )

    if intake_finding is None or intake_finding.confidence < CONFIDENCE_THRESHOLD:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    f"Gemini extraction confidence"
                    f"({intake_finding.confidence if intake_finding else 0.0:.2f}) "
                    f"is below threshold ({CONFIDENCE_THRESHOLD}). "
                    "Manual review required."
                ),
                "raw_text": email_body,
                "extraction": intake_finding.data if intake_finding else {},
            },
        )
    
    final_state = cashguard_graph.invoke(
        post_intake_state,
        config={
            "configurable": {
                "thread_id": order.order_id
            }
        }
    )
    return final_state

@app.post("/cases/{order_id}/review")
def review_case(order_id: str, request: ReviewRequest):
    try:
        result = cashguard_graph.invoke(
        Command(
            resume={
                "approved": request.approved,
                "approved_by": request.approved_by,
                "comments": request.comments,
            }
        ),
        config={
            "configurable": {
                "thread_id": order_id
            }
        }
        )

        return result
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    
@app.get("/cases/{order_id}/state")
def get_case_state(order_id: str):
    state = cashguard_graph.get_state(
        config={
            "configurable": {
                "thread_id": order_id
            }
        }
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found"
        )

    return state.values

@app.get("/cases")
def get_cases():
    return list_cases()

@app.post("/cases/{order_id}/approve")
def approve_case(
    order_id: str,
    request: ReviewRequest
): 
    validate_pending_review(order_id)

    result = cashguard_graph.invoke(
        Command(
            resume={
                "approved": True,
                "approved_by": request.approved_by,
                "comments": request.comments
            }
        ),
        config={
            "configurable": {
                "thread_id": order_id
            }
        }
    )

    upsert_case(
        order_id,
        "approved"
    )

    return result

@app.post("/cases/{order_id}/reject")
def reject_case(
    order_id: str,
    request: ReviewRequest
):
    validate_pending_review(order_id)

    result = cashguard_graph.invoke(
        Command(
            resume={
                "approved": False,
                "approved_by": request.approved_by,
                "comments": request.comments
            }
        ),
        config={
            "configurable": {
                "thread_id": order_id
            }
        }
    )

    upsert_case(
        order_id,
        "rejected"
    )

    return result


@app.post("/collections/run")
def collections_run_all():
    """Analyse all overdue invoices and return collections recommendations."""
    results = run_collections()
    return {"analysed": len(results), "results": results}

@app.post("/collections/run/{invoice_id}")
def collections_run_one(invoice_id: str):
    """Analyse a specific invoice by ID."""
    results = run_collections(invoice_id=invoice_id)
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Invoice '{invoice_id}' not found.",
        )
    return results[0]


# ---------------------------------------------------------------------------
# Dispute endpoints
# ---------------------------------------------------------------------------

@app.post("/disputes/run")
def disputes_run_all():
    """
    Analyse all open disputes.

    For each dispute, this will:
      1. Gather invoice / order / contract evidence from JSON data
      2. Fetch the contract PDF from Google Drive
      3. Ask Gemini for a resolution recommendation
    """
    results = run_disputes()
    return {"analysed": len(results), "results": results}


@app.post("/disputes/run/{dispute_id}")
def disputes_run_one(dispute_id: str):
    """Analyse a specific dispute by ID."""
    results = run_disputes(dispute_id=dispute_id)
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Dispute '{dispute_id}' not found.",
        )
    return results[0]


@app.post("/disputes/{dispute_id}/resolve")
def disputes_resolve(dispute_id: str, resolution: dict):
    """
    Submit a human resolution decision for a dispute.

    Expected request body:
    {
        "resolved_by": "jane.doe@company.com",
        "action_taken": "credit_memo",          // or corrected_invoice / escalate_to_sales / proceed_with_collection
        "notes": "Customer claim verified. Credit memo issued for $440."
    }

    This endpoint patches the in-memory dispute record with the resolution
    and returns the updated state. In production you would persist this to
    a database; here we echo back the resolved dispute for the demo.
    """
    from app.utils import find_one, load_json

    disputes = load_json("disputes.json")
    dispute  = find_one(disputes, "dispute_id", dispute_id)

    if dispute is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dispute '{dispute_id}' not found.",
        )

    resolved_by  = resolution.get("resolved_by")
    action_taken = resolution.get("action_taken")
    notes        = resolution.get("notes", "")

    if not resolved_by or not action_taken:
        raise HTTPException(
            status_code=422,
            detail="Both 'resolved_by' and 'action_taken' are required.",
        )

    valid_actions = {
        "credit_memo",
        "corrected_invoice",
        "escalate_to_sales",
        "proceed_with_collection",
    }
    if action_taken not in valid_actions:
        raise HTTPException(
            status_code=422,
            detail=f"'action_taken' must be one of: {sorted(valid_actions)}",
        )

    return {
        "dispute_id":    dispute_id,
        "previous_status": dispute.get("status"),
        "new_status":    "resolved",
        "action_taken":  action_taken,
        "resolved_by":   resolved_by,
        "notes":         notes,
        "message":       f"Dispute {dispute_id} resolved with action '{action_taken}'.",
    }

# ---------------------------------------------------------------------------
# Audit endpoint
# ---------------------------------------------------------------------------

@app.get("/audit")
def get_audit(case_id: str | None = None):
    """
    Return structured audit entries across all processed cases.

    Query params:
      - case_id (optional): filter to a single order, e.g. ?case_id=ORD-002

    Each entry in the response follows the schema:
    {
        "timestamp":      "2024-06-21T10:30:00+00:00",
        "case_id":        "ORD-002",
        "agent":          "risk_agent",
        "action":         "credit_check",
        "decision":       "needs_human_review",
        "reason":         "Credit utilisation at 95%. Payment risk: high.",
        "confidence":     0.9,
        "human_approver": null
    }
    """
    cases = list_cases()  # [{"order_id": ..., "status": ...}, ...]

    all_entries = []

    for case in cases:
        order_id = case["order_id"]

        # Skip if caller wants a specific case and this isn't it.
        if case_id and order_id != case_id:
            continue

        try:
            graph_state = cashguard_graph.get_state(
                config={"configurable": {"thread_id": order_id}}
            )
        except Exception:
            continue

        if graph_state is None:
            continue

        raw_log = graph_state.values.get("audit_log", [])

        for entry in raw_log:
            # Entries are AuditEntry Pydantic objects when coming from a live
            # graph state, or plain dicts when deserialized from the SQLite
            # checkpointer — handle both.
            if isinstance(entry, dict):
                all_entries.append(entry)
            else:
                all_entries.append(entry.model_dump())

    if case_id and not all_entries:
        raise HTTPException(
            status_code=404,
            detail=f"No audit entries found for case '{case_id}'.",
        )

    # Most recent first.
    all_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    return {
        "total": len(all_entries),
        "filter": {"case_id": case_id},
        "entries": all_entries,
    }