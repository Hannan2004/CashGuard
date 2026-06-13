# CashGuard — Build Plan

Hackathon: UiPath AgentHack 2026 — Track 2 (BPMN Business Process)
Submission deadline: June 29, 2026 at 11:45 PM PDT (treat June 29 as the real deadline)
Repository: https://github.com/Hannan2004/CashGuard

---

## June 7–9 — Foundation ✅ COMPLETE

See `WORK_DONE.md` for full details.

**Delivered:** Docker setup, FastAPI app, LangGraph graph with risk/pricing/inventory/invoice/audit agents, mock data for customers/contracts/inventory/orders, two working demo scenarios.

---

## June 10–11 — Stabilise + Gemini

**Goal:** Fix known issues and wire in the Gemini LLM so all subsequent agents can use it.

**Tasks:**

1. Test Docker workflow end-to-end
   - `docker compose up --build`
   - `GET /health` → `{"status": "ok"}`
   - `POST /cases/run/ORD-001` → invoice generated, credit/pricing/inventory all `auto_approved`
   - `POST /cases/run/ORD-002` → `needs_human_review` (credit high risk + pricing mismatch + inventory shortage)

2. Fix `inventory_agent` path bug
   - Change `load_json("data/inventory.json")` to `load_json("inventory.json")`

3. Create `app/data/policy.txt`
   - Credit thresholds: auto-approve below 75% utilisation, review above 75%, block above 95% or `payment_risk = high`
   - Pricing rules: flag any deviation from contract price regardless of amount
   - Inventory rules: flag if requested quantity exceeds available stock
   - Dispute guidelines: credit memo for valid pricing disputes under $500; escalate to sales above $500
   - Collections rules: urgent follow-up for 15+ days overdue; write-off consideration at 90+ days

4. Create `app/llm.py`
   - Initialise Gemini client using `GOOGLE_API_KEY` and `GEMINI_MODEL` env vars
   - Expose a `call_gemini(prompt: str) -> str` helper
   - Expose a `call_gemini_json(prompt: str) -> dict` helper that parses JSON response safely

---

## June 12 — Intake Agent + Gmail MCP

**Goal:** Replace hardcoded `raw_text` in `orders.json` with real email parsing. Make the demo feel real from the first frame.

**Tasks:**

1. Implement `app/agents/intake_agent.py`
   - Mode 1 (structured passthrough): if `order.lines` is already populated, validate fields and pass forward
   - Mode 2 (Gemini extraction): if `order.raw_text` is set and `lines` is empty, call Gemini to extract `customer_name`, `po_number`, `sku`, `quantity`, `unit_price`, `requested_delivery_date`
   - Add `AgentFinding` with extraction confidence

2. Wire Gmail MCP for `POST /intake/email`
   - Fetch latest unread email from `GMAIL_LABEL` inbox label
   - Pass email body as `raw_text` to intake agent
   - If extraction confidence below 0.7, return `400` with raw body for manual review
   - If successful, run full order-to-cash graph on extracted order

3. Add `intake` as graph entry point
   - Update `graph.py`: `intake → risk → pricing → inventory → ...`

**MCP Server:** Gmail (`https://gmail.googleapis.com/mcp/v1` or equivalent)

---

## June 13–14 — Recommendation Agent + Graph Update

**Goal:** Add the Gemini reasoning layer that synthesises all agent findings and makes the routing decision. This is the core "AI value-add" of the project.

**Tasks:**

1. Create `app/agents/recommendation_agent.py`
   - Reads: all `findings` from state, `policy.txt`, `risk_score`, `risk_level`
   - Reads: customer memory patterns from `memory.json` if available
   - Calls Gemini with a structured prompt including all findings and policy context
   - Returns structured JSON:
     ```json
     {
       "recommended_action": "route_to_human_review",
       "reason": "Customer near credit limit with high payment risk. Pricing mismatch on SKU-MONITOR-27.",
       "policy_references": ["Credit policy: review above 75% utilisation", "Pricing policy: flag any deviation"],
       "human_approval_required": true,
       "confidence": 0.89
     }
     ```
   - Add to `CashGuardState` as `recommendation: dict | None`

2. Update `graph.py`
   - New flow: `intake → risk → pricing → inventory → recommendation → route → invoice or human_review → audit`
   - The routing gateway now reads `state.recommendation.human_approval_required` as primary signal, with status fields as fallback

---

## June 15–16 — Persistence + Case Store + Human Approval API

**Goal:** Make cases long-running and resumable. Without this, human-in-the-loop is fiction.

**Tasks:**

1. Add SQLite persistence
   - Use LangGraph's `SqliteSaver` with `app/data/cashguard.db`
   - Each case uses `thread_id = order_id` for checkpointing
   - Update `build_graph()` to accept the checkpointer

2. Add case store endpoints in `main.py`
   - `GET /cases` — list all cases with status summary
   - `GET /cases/{case_id}` — full state for a specific case

3. Add human approval endpoints
   - `POST /cases/{case_id}/approve` — write human decision to state, resume graph
   - `POST /cases/{case_id}/reject` — write rejection to state, resume graph
   - Both require `approved_by` and `comments` in body
   - Both validate that `human_decision.required == True` and status is `pending`

4. Create `app/agents/human_review_agent.py`
   - Formalises the pause point in the graph
   - Waits for external signal (approve/reject API call) before proceeding
   - On approval: routes to invoice generation
   - On rejection: routes to audit with `next_action = "blocked_by_human"`

---

## June 17–18 — Mock Data Expansion + Collections + Dispute Data

**Goal:** Prepare the collections and dispute workflows by adding missing mock data and building the collections agent.

**Tasks:**

1. Create `app/data/invoices.json` — 3 invoices: one paid, one overdue, one disputed
2. Create `app/data/payments.json` — payment records for the invoices
3. Create `app/data/disputes.json` — one open dispute referencing the disputed invoice

4. Create `app/agents/collections_agent.py`
   - Reads `invoices.json` and `payments.json`
   - For each overdue invoice, assesses: days overdue, customer risk, dispute history
   - Recommends: `standard_reminder`, `urgent_follow_up`, `escalate`, `write_off_review`
   - Adds reasoning and confidence per invoice

5. Add collections endpoints
   - `POST /collections/run` — analyze all overdue invoices
   - `POST /collections/run/{invoice_id}` — analyze a specific invoice

---

## June 19–20 — Dispute Agent + Google Drive MCP

**Goal:** Build the dispute investigation flow with real document retrieval. This is the second highest-impact MCP integration — judges will see actual Drive documents being fetched as evidence.

**Tasks:**

1. Create `app/agents/dispute_agent.py`
   - Reads dispute from `disputes.json`
   - Gathers evidence: matching invoice, order, contract price from JSON
   - Fetches contract PDF from Google Drive using Drive MCP (folder ID from `GDRIVE_CONTRACTS_FOLDER_ID` env var)
   - Passes all evidence to Gemini with dispute resolution prompt
   - Returns recommendation: `credit_memo`, `corrected_invoice`, `escalate_to_sales`, `proceed_with_collection`
   - Always sets `human_approval_required = true` for credit memos and escalations

2. Add dispute endpoints
   - `POST /disputes/run` — analyze all open disputes
   - `POST /disputes/run/{dispute_id}` — analyze a specific dispute
   - `POST /disputes/{dispute_id}/resolve` — submit human resolution decision

3. Stage Google Drive folder
   - Create `CashGuard/contracts/` folder in Google Drive
   - Upload mock contract PDFs: `CUST-1001-SKU-LAPTOP-14.pdf`, `CUST-2002-SKU-MONITOR-27.pdf`
   - Note `GDRIVE_CONTRACTS_FOLDER_ID` in `.env`

**MCP Server:** Google Drive (`https://drivemcp.googleapis.com/mcp/v1`)

---

## June 21 — State Expansion + Memory + Audit Improvement

**Goal:** Complete the state model and make the audit trail useful for the demo and for judges reviewing the submission.

**Tasks:**

1. Update `CashGuardState` in `state.py`
   - Add: `recommendation: dict | None`
   - Add: `dispute: dict | None`
   - Add: `payment_status: str | None`
   - Add: `memory_record: dict | None`

2. Create `app/data/memory.json` — add customer memory patterns for CUST-1001 and CUST-2002

3. Update `audit_agent.py` to produce structured audit entries
   ```json
   {
     "timestamp": "...",
     "case_id": "ORD-002",
     "agent": "risk_agent",
     "action": "credit_check",
     "decision": "needs_human_review",
     "reason": "Credit utilisation at 95%. Payment risk: high.",
     "confidence": 0.9,
     "human_approver": null
   }
   ```

4. Add `GET /audit` endpoint with optional `case_id` filter

---

## June 22–23 — Slack MCP + Demo Scenario Validation

**Goal:** Wire Slack notifications and validate all three demo scenarios work perfectly end-to-end.

**Tasks:**

1. Add Slack notification in `human_review_agent.py`
   - When a case is routed to human review, post a message to `SLACK_APPROVALS_CHANNEL`
   - Message should include: case ID, customer name, order total, risk summary, approve/reject API commands
   - Requires `SLACK_BOT_TOKEN` and `SLACK_APPROVALS_CHANNEL` env vars

2. Validate Scenario 1 — Clean Order (ORD-001: Northstar Retail)
   - Credit: auto_approved (utilisation ~28%)
   - Pricing: auto_approved (matches contract)
   - Inventory: auto_approved (stock available)
   - Recommendation: auto-invoice
   - Outcome: invoice generated, no human required

3. Validate Scenario 2 — Risky Exception Order (ORD-002: MetroBuild Supplies)
   - Credit: needs_human_review (high risk, 95%+ utilisation)
   - Pricing: needs_human_review (submitted $210, contract $220)
   - Inventory: needs_human_review (10 requested, 4 available)
   - Recommendation: human review with full evidence summary
   - Slack ping fires
   - Human approves via `POST /cases/ORD-002/approve`
   - Case resumes to invoice generation

4. Validate Scenario 3 — Invoice Dispute (DISP-001)
   - Dispute agent fetches contract PDF from Google Drive
   - Gemini recommends corrected invoice
   - Human approves resolution via `POST /disputes/DISP-001/resolve`

**MCP Server:** Slack (configure bot token and channel)

---

## June 24–25 — Architecture Diagram + Documentation

**Goal:** Prepare all submission materials so June 26–27 is purely video recording and final polish.

**Tasks:**

1. Create architecture diagram (for Devpost and README)
   - Blocks: Finance Manager → UiPath Maestro BPMN → CashGuard FastAPI → LangGraph Agents → Gemini → Mock Enterprise Systems + Drive + Gmail + Slack
   - Show MCP connections explicitly

2. Write `README.md`
   - Project overview and one-line pitch
   - Architecture overview
   - Setup instructions (clone, `.env`, `docker compose up`)
   - Demo scenario walkthrough with example API calls
   - Environment variables reference
   - Track 2 alignment statement

3. Update `WORK_DONE.md` to reflect completed phases

4. Design UiPath Maestro BPMN process map matching the flow in `graph.py`

---

## June 26–27 — Demo Video + Devpost Submission

**Goal:** Record a compelling 3–5 minute demo and submit.

**Demo script:**

1. Show an incoming email in Gmail (order from MetroBuild Supplies)
2. Call `POST /intake/email` — show Gemini extracting the order
3. Show the graph running: risk flags high utilisation, pricing flags mismatch, inventory flags shortage
4. Show recommendation agent output (Gemini reasoning, policy references)
5. Show Slack message in `#cashguard-approvals` channel
6. Call `POST /cases/ORD-002/approve` — case resumes, invoice generated
7. Switch to dispute scenario — call `POST /disputes/run/DISP-001`
8. Show Drive document retrieval in agent output
9. Show Gemini recommendation: corrected invoice
10. Show audit trail via `GET /audit?case_id=ORD-002`

**Devpost title:** CashGuard: Agentic Order-to-Cash Exception Orchestration with UiPath Maestro and LangGraph

**Short description:** CashGuard orchestrates order-to-cash exceptions using UiPath Maestro BPMN and LangGraph agents, helping finance teams resolve credit holds, pricing mismatches, inventory shortages, invoice disputes, and collections delays with human approval and full auditability.

**One-line pitch:** CashGuard turns messy finance exceptions into a governed, agent-assisted BPMN workflow that protects revenue and accelerates cash collection.

---

## June 28–29 — Buffer

Emergency buffer only. If June 26–27 was clean, use this time to:
- Add one more edge case demo
- Polish README formatting
- Re-record any unclear sections of the demo video
- Double-check Devpost submission form completeness

**Hard deadline: June 29, 11:45 PM PDT**

---

## MCP Integration Summary

| MCP Server | When Added | What It Replaces | Why It Matters |
|---|---|---|---|
| **Gmail** | June 12 | Hardcoded `raw_text` in `orders.json` | Shows real order intake from email — makes Scenarios 1 & 2 feel real in the demo |
| **Google Drive** | June 19–20 | `contracts.json` for dispute evidence | Dispute agent retrieves actual PDF contracts — judges see real document retrieval |
| **Slack** | June 22–23 | No notification (human review was invisible) | Finance manager gets a real Slack ping — closes the human-in-the-loop story visually |

---

## What Is Explicitly Out of Scope for MVP

- Real SAP/Oracle/NetSuite ERP integration
- Real payment gateway integration
- Real email inbox parsing beyond Gmail MCP
- Full production authentication and authorisation
- Complex A2A agent interoperability with external agents
- Production dashboard with charts and drill-downs
- Multi-tenant or multi-company support

**Mention as future expansion in Devpost submission:**
- Real ERP connectors (SAP, Oracle, NetSuite)
- Teams/Slack approval workflows
- Predictive DSO (Days Sales Outstanding) optimisation
- A2A agent interoperability
- Full audit dashboard

---

## Success Metrics (Demo Wording)

Use "designed to" framing — do not claim measured production results.

- CashGuard is designed to reduce manual order exception review time by 60%
- CashGuard is designed to reduce invoice dispute investigation time by 50%
- CashGuard is designed to improve order release speed for clean orders from hours to minutes
- CashGuard is designed to increase consistency of credit and pricing decisions through policy-grounded AI reasoning
- CashGuard is designed to improve audit readiness for finance approvals through structured, timestamped decision records
