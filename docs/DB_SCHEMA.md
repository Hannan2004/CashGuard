# CashGuard — Database Schema

CashGuard uses two storage layers:

- **Mock JSON files** in `app/data/` simulate enterprise systems (CRM, ERP, contract repo, inventory, payment system, dispute inbox).
- **SQLite** (added in June 15–16 phase) stores LangGraph checkpoints for long-running case state and the audit log.

---

## Mock Data Files

### `customers.json` — Mock CRM / Credit System

Represents the customer master record used by the risk agent.

| Field | Type | Description |
|---|---|---|
| `customer_id` | string | Unique customer identifier (e.g. `CUST-1001`) |
| `name` | string | Customer display name |
| `credit_limit` | number | Maximum approved credit in USD |
| `open_balance` | number | Current outstanding balance in USD |
| `payment_risk` | string | `low`, `medium`, or `high` — manual risk classification |
| `dispute_history` | string | `rare`, `occasional`, or `frequent` — historical pattern |

---

### `contracts.json` — Mock Contract Repository

Used by the pricing agent to validate submitted order prices against agreed contract terms.

| Field | Type | Description |
|---|---|---|
| `customer_id` | string | Customer this contract applies to |
| `sku` | string | Product SKU covered by this price agreement |
| `contract_price` | number | Agreed unit price in USD |

> The actual PDF contract documents live in Google Drive and are retrieved by the dispute agent via Google Drive MCP when gathering evidence.

---

### `inventory.json` — Mock Warehouse / Inventory System

Used by the inventory agent to check stock availability.

| Field | Type | Description |
|---|---|---|
| `sku` | string | Product SKU |
| `available_quantity` | number | Units currently in stock |

---

### `orders.json` — Mock Order Intake / ERP Order Queue

Seed data for running cases. In production, orders arrive via Gmail MCP or direct API POST.

| Field | Type | Description |
|---|---|---|
| `order_id` | string | Unique order identifier (e.g. `ORD-001`) |
| `customer_id` | string | Reference to `customers.json` |
| `customer_name` | string | Customer display name |
| `po_number` | string \| null | Customer's purchase order number |
| `requested_delivery_date` | string \| null | ISO 8601 date |
| `lines` | array | List of `OrderLine` objects (see below) |
| `raw_text` | string \| null | Unstructured order text for Gemini extraction |

**OrderLine:**

| Field | Type | Description |
|---|---|---|
| `sku` | string | Product SKU |
| `quantity` | number | Units ordered |
| `unit_price` | number | Price submitted by customer |

---

### `invoices.json` — Mock ERP Invoice Module *(added June 17)*

| Field | Type | Description |
|---|---|---|
| `invoice_id` | string | e.g. `INV-001` |
| `order_id` | string | Reference to originating order |
| `customer_id` | string | Customer reference |
| `amount_due` | number | Total invoice value in USD |
| `due_date` | string | ISO 8601 payment due date |
| `status` | string | `unpaid`, `paid`, `overdue`, `disputed` |
| `issued_date` | string | ISO 8601 date invoice was generated |

---

### `payments.json` — Mock Accounts Receivable / Payment System *(added June 17)*

| Field | Type | Description |
|---|---|---|
| `invoice_id` | string | Reference to `invoices.json` |
| `customer_id` | string | Customer reference |
| `amount_paid` | number | Amount received |
| `payment_date` | string \| null | ISO 8601 date of payment |
| `days_overdue` | number | Days past due date (0 if paid on time) |

---

### `disputes.json` — Mock Customer Dispute Inbox *(added June 17)*

| Field | Type | Description |
|---|---|---|
| `dispute_id` | string | e.g. `DISP-001` |
| `invoice_id` | string | Reference to disputed invoice |
| `customer_id` | string | Customer reference |
| `reason` | string | Customer-stated reason (e.g. `price_mismatch`, `missing_po`, `delivery_issue`) |
| `status` | string | `open`, `resolved`, `escalated` |
| `opened_date` | string | ISO 8601 date dispute was raised |
| `evidence_gathered` | boolean | Whether dispute agent has run |

---

### `memory.json` — Long-Term Customer Behavior Memory *(added June 21)*

Stores patterns learned from past cases. Used by the recommendation agent to personalise decisions.

| Field | Type | Description |
|---|---|---|
| `customer_id` | string | Customer reference |
| `patterns` | array of string | e.g. `"often disputes freight charges"`, `"requires PO on invoice"` |
| `last_updated` | string | ISO 8601 timestamp |

---

## SQLite — LangGraph Persistence *(added June 15)*

LangGraph's `SqliteSaver` checkpoints full `CashGuardState` after every node. The SQLite file lives at `app/data/cashguard.db`.

Each case maps to a `thread_id` equal to its `order_id`. This allows:

- Long-running cases to survive process restarts.
- Human approval endpoints to resume a paused graph by `thread_id`.
- `GET /cases` to list all active and completed cases.

LangGraph manages the internal schema of `cashguard.db`. No manual schema definition is needed.

---

## CashGuardState — Runtime State Object

This is the in-memory state passed between LangGraph nodes. It is persisted to SQLite after each node.

| Field | Type | Description |
|---|---|---|
| `order` | `OrderInput` | The normalised order being processed |
| `findings` | list of `AgentFinding` | Outputs from each agent |
| `risk_score` | float \| null | Credit utilisation ratio |
| `risk_level` | string \| null | `low`, `medium`, or `high` |
| `credit_status` | `DecisionStatus` | Credit check outcome |
| `pricing_status` | `DecisionStatus` | Pricing validation outcome |
| `inventory_status` | `DecisionStatus` | Stock check outcome |
| `recommendation` | dict \| null | Gemini recommendation output *(added June 13)* |
| `human_decision` | `HumanDecision` | Human approval state |
| `invoice_id` | string \| null | Generated invoice ID |
| `dispute` | dict \| null | Dispute details if a dispute case *(added June 21)* |
| `payment_status` | string \| null | Payment tracking status *(added June 21)* |
| `memory_record` | dict \| null | Relevant customer memory patterns *(added June 21)* |
| `next_action` | string \| null | Routing signal for the graph |
| `audit_log` | list of string | Timestamped event log |

**DecisionStatus values:** `pending`, `approved`, `rejected`, `needs_human_review`, `auto_approved`, `blocked`
