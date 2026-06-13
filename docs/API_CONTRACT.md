# CashGuard — API Contract

Base URL (local): `http://localhost:8000`

All request and response bodies are JSON. All timestamps are ISO 8601 UTC.

---

## Health

### `GET /health`

Returns service status.

**Response**
```json
{ "status": "ok" }
```

---

## Cases — Order-to-Cash Workflow

### `POST /cases/run`

Run a full order-to-cash workflow from a structured or raw order payload.

**Request Body**
```json
{
  "order_id": "ORD-003",
  "customer_id": "CUST-1001",
  "customer_name": "Northstar Retail",
  "po_number": "PO-7782",
  "requested_delivery_date": "2026-06-20",
  "lines": [
    { "sku": "SKU-LAPTOP-14", "quantity": 2, "unit_price": 950 }
  ],
  "raw_text": null
}
```

Pass `raw_text` and omit `lines` to trigger Gemini extraction via the intake agent.

**Response** — full `CashGuardState` object (see DB_SCHEMA.md)

---

### `POST /cases/run/{order_id}`

Run a workflow for an order that already exists in `orders.json`.

**Path Parameter:** `order_id` — e.g. `ORD-001`

**Response** — full `CashGuardState` object

**Errors**
- `404` — Order not found in mock data

---

### `GET /cases`

List all cases with their current status. Requires SQLite persistence (June 15).

**Response**
```json
[
  {
    "case_id": "ORD-001",
    "status": "invoice_generated",
    "credit_status": "auto_approved",
    "pricing_status": "auto_approved",
    "inventory_status": "auto_approved",
    "invoice_id": "INV-001",
    "human_decision_required": false,
    "last_updated": "2026-06-15T10:23:45Z"
  }
]
```

---

### `GET /cases/{case_id}`

Get full state for a specific case. Requires SQLite persistence (June 15).

**Path Parameter:** `case_id` — e.g. `ORD-002`

**Response** — full `CashGuardState` object

**Errors**
- `404` — Case not found

---

### `POST /cases/{case_id}/approve`

Submit a human approval decision for a case awaiting review. Resumes the paused LangGraph graph.

**Path Parameter:** `case_id` — e.g. `ORD-002`

**Request Body**
```json
{
  "approved_by": "finance_manager@company.com",
  "comments": "Credit exception approved given strategic account status."
}
```

**Response**
```json
{
  "case_id": "ORD-002",
  "status": "approved",
  "resumed": true
}
```

**Errors**
- `404` — Case not found
- `400` — Case does not require human review or is already decided

---

### `POST /cases/{case_id}/reject`

Submit a human rejection for a case awaiting review.

**Path Parameter:** `case_id` — e.g. `ORD-002`

**Request Body**
```json
{
  "approved_by": "finance_manager@company.com",
  "comments": "Credit limit already at risk. Cannot approve additional exposure."
}
```

**Response**
```json
{
  "case_id": "ORD-002",
  "status": "rejected",
  "resumed": true
}
```

---

## Collections

### `POST /collections/run`

Run the collections agent over all overdue invoices. Added June 17.

**Request Body** — empty `{}`

**Response**
```json
{
  "analyzed": 3,
  "actions": [
    {
      "invoice_id": "INV-002",
      "customer_id": "CUST-2002",
      "days_overdue": 18,
      "recommended_action": "urgent_follow_up",
      "reason": "High-risk customer with frequent dispute history. Amount: $2,100.",
      "confidence": 0.88
    }
  ]
}
```

---

### `POST /collections/run/{invoice_id}`

Run the collections agent for a single invoice. Added June 17.

**Path Parameter:** `invoice_id` — e.g. `INV-002`

**Response** — single action object as above

---

## Disputes

### `POST /disputes/run`

Run the dispute agent for all open disputes. Uses Google Drive MCP to retrieve contract evidence. Added June 19.

**Request Body** — empty `{}`

**Response**
```json
{
  "analyzed": 1,
  "recommendations": [
    {
      "dispute_id": "DISP-001",
      "invoice_id": "INV-002",
      "customer_id": "CUST-2002",
      "evidence_sources": ["contracts/CUST-2002-SKU-MONITOR-27.pdf", "orders.json:ORD-002"],
      "recommended_action": "corrected_invoice",
      "reason": "Contract price is $220, invoice shows $210. Customer dispute is valid.",
      "human_approval_required": true,
      "confidence": 0.91
    }
  ]
}
```

---

### `POST /disputes/run/{dispute_id}`

Run the dispute agent for a single dispute. Added June 19.

**Path Parameter:** `dispute_id` — e.g. `DISP-001`

**Response** — single recommendation object as above

---

### `POST /disputes/{dispute_id}/resolve`

Submit the human resolution decision for a dispute.

**Request Body**
```json
{
  "action": "corrected_invoice",
  "approved_by": "finance_manager@company.com",
  "comments": "Confirmed price mismatch. Reissuing invoice at contract price."
}
```

**action values:** `credit_memo`, `corrected_invoice`, `escalate_to_sales`, `proceed_with_collection`

**Response**
```json
{
  "dispute_id": "DISP-001",
  "status": "resolved",
  "action_taken": "corrected_invoice"
}
```

---

## Gmail Intake (MCP-powered)

### `POST /intake/email`

Fetch the latest unread order email from the configured Gmail label, extract order details via Gemini, and run the full order-to-cash workflow. Added June 12.

**Request Body** — empty `{}`

**Response** — full `CashGuardState` object from the extracted order

**Notes**
- Requires `GMAIL_LABEL` env var (default: `cashguard-orders`)
- Gemini extracts: `customer_name`, `po_number`, `sku`, `quantity`, `unit_price`, `requested_delivery_date`
- If extraction confidence is below threshold, returns `400` with raw email body for manual review

---

## Audit

### `GET /audit`

Return all audit log entries across all cases. Added June 21.

**Query Parameters**
- `case_id` (optional) — filter by case
- `limit` (optional, default 50) — number of entries to return

**Response**
```json
{
  "entries": [
    {
      "timestamp": "2026-06-15T10:23:45Z",
      "case_id": "ORD-001",
      "agent": "risk_agent",
      "action": "credit_check",
      "decision": "auto_approved",
      "reason": "Credit utilisation at 28.5%. Within acceptable range.",
      "confidence": 0.9,
      "human_approver": null
    }
  ]
}
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Yes | Gemini API key |
| `GEMINI_MODEL` | No | Model name (default: `gemini-1.5-flash`) |
| `GMAIL_LABEL` | For Gmail MCP | Gmail label to watch for order emails |
| `GDRIVE_CONTRACTS_FOLDER_ID` | For Drive MCP | Google Drive folder ID containing contract PDFs |
| `SLACK_BOT_TOKEN` | For Slack MCP | Slack bot token for approval notifications |
| `SLACK_APPROVALS_CHANNEL` | For Slack MCP | Channel ID for human approval pings |
