from fastapi import FastAPI, HTTPException

from app.graph import build_graph
from app.state import CashGuardState, OrderInput
from app.utils import find_one, load_json

app = FastAPI(title="CashGuard Agentic Order-to-Cash API")

cashguard_graph = build_graph()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/cases/run")
def run_case(order: OrderInput):
    initial_state = CashGuardState(order=order)
    final_state = cashguard_graph.invoke(initial_state)
    return final_state

@app.post("/cases/run/{order_id}")
def run_case_by_order_id(order_id: str):
    orders = load_json("orders.json")
    order = find_one(orders, "order_id", order_id)

    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    
    initial_state = CashGuardState(order=OrderInput(**order))
    final_state = cashguard_graph.invoke(initial_state)

    return final_state