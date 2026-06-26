"""
Demo Scenario Validation Script
================================
Validates all three demo scenarios end-to-end against a running CashGuard
server. Run with:

    python -m app.scripts.validate_scenarios

Or against a specific host:

    BASE_URL=http://localhost:8000 python -m app.scripts.validate_scenarios

Scenarios covered:
  1. ORD-001 (Northstar Retail) — Clean order, fully auto-approved
  2. ORD-002 (MetroBuild Supplies) — Exception order, human review required
  3. DISP-001 — Invoice dispute, Gemini recommends corrected invoice

Exit code 0 = all scenarios passed. Non-zero = at least one failure.
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

# ANSI colours for terminal output
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}✓ PASS{RESET}"
FAIL = f"{RED}✗ FAIL{RESET}"
INFO = f"{YELLOW}ℹ{RESET}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post(path: str, payload: dict | None = None) -> dict:
    url  = f"{BASE_URL}{path}"
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get(path: str, params: dict | None = None) -> dict:
    url  = f"{BASE_URL}{path}"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    suffix = f"  {YELLOW}({detail}){RESET}" if detail else ""
    print(f"    {status}  {label}{suffix}")
    return condition


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    print("─" * 60)


# ---------------------------------------------------------------------------
# Scenario 1 — Clean order (ORD-001)
# ---------------------------------------------------------------------------

def scenario_1() -> bool:
    section("Scenario 1 — Clean Order (ORD-001: Northstar Retail)")
    failures = 0

    try:
        result = post("/cases/run/ORD-001")
    except Exception as exc:
        print(f"  {FAIL}  Could not run ORD-001: {exc}")
        return False

    credit    = result.get("credit_status")
    pricing   = result.get("pricing_status")
    inventory = result.get("inventory_status")
    rec       = (result.get("recommendation") or {})
    invoice   = result.get("invoice_id")
    h_req     = (result.get("human_decision") or {}).get("required", True)
    risk_lvl  = result.get("risk_level")

    failures += not check("credit_status == auto_approved",   credit    == "auto_approved", credit)
    failures += not check("pricing_status == auto_approved",  pricing   == "auto_approved", pricing)
    failures += not check("inventory_status == auto_approved",inventory == "auto_approved", inventory)
    failures += not check("risk_level == low",                risk_lvl  == "low",           risk_lvl)
    failures += not check("human_decision.required == False", h_req     is False,            str(h_req))
    failures += not check("invoice_id is set",                bool(invoice),                 invoice or "None")
    failures += not check(
        "recommendation: auto_invoice or no human required",
        not rec.get("human_approval_required", True),
        rec.get("recommended_action", "n/a"),
    )

    # Audit entries should exist
    try:
        audit = get("/audit", params={"case_id": "ORD-001"})
        failures += not check(
            "audit trail has entries",
            audit.get("total", 0) > 0,
            f"{audit.get('total', 0)} entries",
        )
    except Exception as exc:
        failures += 1
        print(f"    {FAIL}  Could not fetch audit: {exc}")

    return failures == 0


# ---------------------------------------------------------------------------
# Scenario 2 — Exception order (ORD-002)
# ---------------------------------------------------------------------------

def scenario_2() -> bool:
    section("Scenario 2 — Risky Exception Order (ORD-002: MetroBuild Supplies)")
    failures = 0

    # Step 1: run the case — it should pause at human_review
    print(f"\n  {INFO}  Step 2a: running ORD-002 (expect pause at human_review)…")
    try:
        result = post("/cases/run/ORD-002")
    except Exception as exc:
        print(f"  {FAIL}  Could not run ORD-002: {exc}")
        return False

    credit    = result.get("credit_status")
    pricing   = result.get("pricing_status")
    inventory = result.get("inventory_status")
    h_req     = (result.get("human_decision") or {}).get("required", False)

    failures += not check("credit_status == needs_human_review",   credit    == "needs_human_review", credit)
    failures += not check("pricing_status == needs_human_review",  pricing   == "needs_human_review", pricing)
    failures += not check("inventory_status == needs_human_review",inventory == "needs_human_review", inventory)
    failures += not check("human_decision.required == True",        h_req     is True,                 str(h_req))

    # Step 2: approve
    print(f"\n  {INFO}  Step 2b: approving ORD-002…")
    try:
        approved = post(
            "/cases/ORD-002/approve",
            {"approved_by": "validator@cashguard.ai", "comments": "Demo approval — scenario 2"},
        )
        h_status  = (approved.get("human_decision") or {}).get("status")
        invoice   = approved.get("invoice_id")
        approver  = (approved.get("human_decision") or {}).get("approved_by")

        failures += not check("human_decision.status == approved", h_status == "approved",             h_status)
        failures += not check("invoice_id is set after approval",  bool(invoice),                      invoice or "None")
        failures += not check("approved_by is recorded",           bool(approver),                     approver or "None")
    except Exception as exc:
        failures += 1
        print(f"    {FAIL}  Approval failed: {exc}")

    # Audit trail
    try:
        audit = get("/audit", params={"case_id": "ORD-002"})
        agents_in_audit = {e["agent"] for e in audit.get("entries", [])}
        failures += not check(
            "audit has risk_agent entry",
            "risk_agent" in agents_in_audit,
            str(agents_in_audit),
        )
        failures += not check(
            "audit has human_review_agent entry",
            "human_review_agent" in agents_in_audit,
            str(agents_in_audit),
        )
    except Exception as exc:
        failures += 1
        print(f"    {FAIL}  Could not fetch audit: {exc}")

    return failures == 0


# ---------------------------------------------------------------------------
# Scenario 3 — Invoice dispute (DISP-001)
# ---------------------------------------------------------------------------

def scenario_3() -> bool:
    section("Scenario 3 — Invoice Dispute (DISP-001)")
    failures = 0

    # Step 1: run dispute analysis
    print(f"\n  {INFO}  Step 3a: analysing DISP-001…")
    try:
        result = post("/disputes/run/DISP-001")
    except Exception as exc:
        print(f"  {FAIL}  Could not run DISP-001: {exc}")
        return False

    rec_action = result.get("recommended_action", "")
    confidence = result.get("confidence", 0)
    h_req      = result.get("human_approval_required", False)

    failures += not check("recommended_action is set",             bool(rec_action),  rec_action or "None")
    failures += not check("confidence > 0",                        confidence > 0,    str(confidence))
    failures += not check(
        "human_approval_required is True (credit_memo or escalation)",
        h_req is True,
        str(h_req),
    )
    failures += not check(
        "recommended_action is corrected_invoice or credit_memo",
        rec_action in ("corrected_invoice", "credit_memo"),
        rec_action,
    )

    # Step 2: resolve with human decision
    print(f"\n  {INFO}  Step 3b: resolving DISP-001 as corrected_invoice…")
    try:
        resolved = post(
            "/disputes/DISP-001/resolve",
            {
                "resolved_by":  "validator@cashguard.ai",
                "action_taken": "corrected_invoice",
                "notes":        "Customer claim verified. Corrected invoice issued at $220/unit.",
            },
        )
        failures += not check(
            "new_status == resolved",
            resolved.get("new_status") == "resolved",
            resolved.get("new_status"),
        )
        failures += not check(
            "action_taken echoed back",
            resolved.get("action_taken") == "corrected_invoice",
            resolved.get("action_taken"),
        )
    except Exception as exc:
        failures += 1
        print(f"    {FAIL}  Resolution failed: {exc}")

    return failures == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{BOLD}CashGuard — Demo Scenario Validation{RESET}")
    print(f"Target: {BASE_URL}\n")

    # Health check
    try:
        health = get("/health")
        print(f"{PASS}  Server reachable — {health}")
    except Exception as exc:
        print(f"{FAIL}  Server not reachable at {BASE_URL}: {exc}")
        print("       Start the server with: uvicorn app.main:app --reload")
        sys.exit(1)

    results = {
        "Scenario 1 — Clean Order":       scenario_1(),
        "Scenario 2 — Risky Exception":   scenario_2(),
        "Scenario 3 — Invoice Dispute":   scenario_3(),
    }

    # Summary
    section("Summary")
    all_passed = True
    for name, passed in results.items():
        icon = PASS if passed else FAIL
        print(f"  {icon}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print(f"{GREEN}{BOLD}All scenarios passed. CashGuard is demo-ready! 🚀{RESET}\n")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}One or more scenarios failed. Review output above.{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()