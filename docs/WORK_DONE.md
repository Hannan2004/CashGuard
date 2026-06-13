# CashGuard — Work Done

Last updated: June 10, 2026 (start of June 10–15 phase)

---

## June 7–9 Phase — Foundation ✅

### Project Setup
- Initialised GitHub repository: `Hannan2004/CashGuard`
- Configured Docker and `docker-compose.yml` for containerised development
- Set up FastAPI application with Uvicorn
- Configured `.env` and `.gitignore`
- Added `requirements.txt` with: `langgraph`, `langchain`, `langchain-google-genai`, `pydantic`, `python-dotenv`, `fastapi`, `uvicorn`

### Data Model
- Defined `CashGuardState` in `app/state.py` — the core LangGraph state object
- Defined supporting models: `OrderInput`, `OrderLine`, `AgentFinding`, `HumanDecision`
- Defined `DecisionStatus` literal type

### Mock Data
- `app/data/customers.json` — 2 customers: Northstar Retail (low risk) and MetroBuild Supplies (high risk, frequent disputes)
- `app/data/contracts.json` — contract prices for each customer/SKU combination
- `app/data/inventory.json` — available stock per SKU
- `app/data/orders.json` — 2 seed orders: ORD-001 (clean order) and ORD-002 (risky exception)

### Agents Built
- `risk_agent` — checks customer credit utilisation and payment risk. Classifies as `auto_approved`, `needs_human_review`, or `blocked`. Stores `AgentFinding` with credit data.
- `pricing_agent` — validates each order line's submitted price against `contracts.json`. Flags mismatches. Stores `AgentFinding` with mismatch details.
- `inventory_agent` — checks each SKU against `inventory.json`. Flags shortages. Stores `AgentFinding` with shortage data.
- `invoice_agent` — generates invoice ID (`INV-XXX`) for auto-approved orders. Sets `next_action = "invoice_generated"`.
- `audit_agent` — appends timestamped log entry to `state.audit_log` with credit/pricing/inventory statuses and next action.
- `intake_agent` — file created, implementation pending (June 12 phase)

### LangGraph Graph (`app/graph.py`)
- Nodes: `risk → pricing → inventory → [conditional] → invoice or audit → END`
- Routing logic: if any status is `blocked` → audit; if any status is `needs_human_review` → audit (with human decision flagged); otherwise → invoice → audit
- Graph compiled with `StateGraph(CashGuardState)`

### API (`app/main.py`)
- `GET /health` — service health check
- `POST /cases/run` — run workflow from structured order payload
- `POST /cases/run/{order_id}` — run workflow for order in `orders.json`

### Utility (`app/utils.py`)
- `load_json(filename)` — loads JSON from `app/data/` directory
- `find_one(items, key, value)` — finds first matching item in a list

---

## What Is Not Yet Built

The following are planned and tracked in `BUILD_PLAN.md`:

- Gemini LLM helper (`app/llm.py`)
- `intake_agent` implementation with Gemini extraction and Gmail MCP
- `recommendation_agent` with policy-aware Gemini reasoning
- `collections_agent` and `dispute_agent`
- SQLite persistence and LangGraph checkpointing
- Human approval API endpoints (`/approve`, `/reject`)
- Google Drive MCP integration in dispute agent
- Slack MCP for approval notifications
- Additional mock data: `invoices.json`, `payments.json`, `disputes.json`, `memory.json`
- Audit log structured format (currently plain strings)
- Full demo scenario validation (Scenario 3 — dispute)
- UiPath Maestro BPMN process design
- README, architecture diagram, Devpost submission materials

---

## Known Issues

- `inventory_agent` has a path bug: it loads `data/inventory.json` instead of `inventory.json` — all other agents use `load_json("filename.json")` which resolves from `app/data/` correctly. Fix in June 10 stabilisation step.
- `intake_agent.py` exists but is empty — implementation is in scope for June 12.
- No SQLite persistence yet — `GET /cases` and `GET /cases/{case_id}` endpoints do not exist.
- Human approval endpoints do not exist — cases requiring review are currently terminal.
- Audit log entries are plain strings rather than structured objects.
