from typing import Any, Literal
from pydantic import BaseModel, Field

DecisionStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "needs_human_review",
    "auto_approved",
    "blocked",
]

class OrderLine(BaseModel):
    sku: str
    quantity: int
    unit_price: float

class OrderInput(BaseModel):
    order_id: str
    customer_id: str
    customer_name: str
    po_number: str | None = None
    requested_delivery_date: str | None = None
    lines: list[OrderLine]
    raw_text: str | None = None

class AgentFinding(BaseModel):
    agent: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    data: dict[str, Any] = Field(default_factory=dict)

class HumanDecision(BaseModel):
    required: bool = False
    reason: str | None = None
    status: DecisionStatus = "pending"
    approved_by: str | None = None
    comments: str | None = None

class CashGuardState(BaseModel):
    order: OrderInput
    
    findings: list[AgentFinding] = Field(default_factory=list)
    risk_score: float | None = None
    risk_level: Literal["low", "medium", "high"] | None = None

    pricing_status: DecisionStatus = "pending"
    inventory_status: DecisionStatus = "pending"
    credit_status: DecisionStatus = "pending"

    human_decision: HumanDecision = Field(default_factory=HumanDecision)

    next_action: str | None = None
    invoice_id: str | None = None
    audit_log: list[str] = Field(default_factory=list)