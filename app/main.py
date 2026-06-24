import os
from fastapi import FastAPI, HTTPException

from app.agents.intake_agent import intake_agent
from app.agents.collections_agent import run_collections
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
