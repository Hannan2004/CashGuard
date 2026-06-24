"""
Dispute Agent
=============
Investigates open disputes by:
  1. Loading the dispute record from disputes.json
  2. Gathering corroborating evidence from invoices.json, orders.json, contracts.json
  3. Fetching the relevant contract PDF from Google Drive (via OAuth2 / Service Account)
  4. Passing all evidence to Gemini for a structured resolution recommendation
  5. Returning one of: credit_memo | corrected_invoice | escalate_to_sales | proceed_with_collection

Human approval is always required for credit_memo and escalate_to_sales outcomes.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any

from app.drive_client import fetch_contract_pdf_bytes
from app.llm import call_gemini_json
from app.utils import find_one, load_json

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

DisputeRecommendation = dict[str, Any]


# ---------------------------------------------------------------------------
# Evidence gathering
# ---------------------------------------------------------------------------

def _gather_evidence(dispute: dict) -> dict[str, Any]:
    """
    Pull all structured evidence for a single dispute from local JSON files.
    Returns a dict that will be embedded in the Gemini prompt.
    """
    invoices  = load_json("invoices.json")
    orders    = load_json("orders.json")
    contracts = load_json("contracts.json")
    customers = load_json("customers.json")

    invoice  = find_one(invoices,  "invoice_id",  dispute["invoice_id"])
    order    = find_one(orders,    "order_id",    dispute["order_id"])
    customer = find_one(customers, "customer_id", dispute["customer_id"])

    # Find the contracted price for every SKU on the disputed order
    contract_prices: list[dict] = []
    if order and order.get("lines"):
        for line in order["lines"]:
            contract_row = next(
                (
                    c for c in contracts
                    if c["customer_id"] == dispute["customer_id"]
                    and c["sku"] == line["sku"]
                ),
                None,
            )
            contract_prices.append(
                {
                    "sku":            line["sku"],
                    "ordered_qty":    line["quantity"],
                    "submitted_price": line["unit_price"],
                    "contract_price": contract_row["contract_price"] if contract_row else "N/A",
                    "price_delta":    (
                        round(line["unit_price"] - contract_row["contract_price"], 2)
                        if contract_row else "N/A"
                    ),
                }
            )

    return {
        "dispute":         dispute,
        "invoice":         invoice,
        "order":           order,
        "customer":        customer,
        "contract_prices": contract_prices,
    }

def _fetch_drive_contract(customer_id: str, sku: str) -> dict[str, Any]:
    """
    Attempt to fetch the contract PDF from Google Drive.

    File naming convention in Drive: <CUSTOMER_ID>-<SKU>.pdf
    e.g.  CUST-2002-SKU-MONITOR-27.pdf

    Returns a dict with keys:
      - fetched (bool)
      - filename (str)
      - content_preview (str)  — first 500 chars of extracted text, or base64 snippet
      - error (str | None)
    """
    filename = f"{customer_id}-{sku}.pdf"

    try:
        pdf_bytes = fetch_contract_pdf_bytes(filename)

        if pdf_bytes is None:
            return {
                "fetched":          False,
                "filename":         filename,
                "content_preview":  None,
                "error":            "File not found in Google Drive contracts folder.",
            }

        try:
            import fitz 
            doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            preview = text[:1500].strip()
        except ImportError:
            # PyMuPDF not installed — give Gemini a base64 note instead
            b64 = base64.b64encode(pdf_bytes[:512]).decode()
            preview = f"[Binary PDF — base64 snippet]: {b64}"

        return {
            "fetched":          True,
            "filename":         filename,
            "content_preview":  preview,
            "error":            None,
        }

    except Exception as exc:  # noqa: BLE001
        return {
            "fetched":          False,
            "filename":         filename,
            "content_preview":  None,
            "error":            str(exc),
        }

def _build_prompt(evidence: dict[str, Any], drive_result: dict[str, Any], policy_text: str) -> str:
    dispute = evidence["dispute"]

    drive_section = (
        f"CONTRACT PDF ({drive_result['filename']}):\n{drive_result['content_preview']}"
        if drive_result["fetched"]
        else f"CONTRACT PDF: Not available — {drive_result['error']}"
    )

    return f"""
You are a finance dispute resolution engine for an order-to-cash system.

FINANCE POLICIES:
{policy_text}

DISPUTE RECORD:
  Dispute ID      : {dispute['dispute_id']}
  Invoice ID      : {dispute['invoice_id']}
  Customer        : {dispute['customer_name']} ({dispute['customer_id']})
  Dispute Reason  : {dispute['dispute_reason']}
  Description     : {dispute['description']}
  Amount in Dispute: ${dispute['amount_in_dispute']}
  Status          : {dispute['status']}

INVOICE EVIDENCE:
{evidence['invoice']}

ORDER EVIDENCE:
{evidence['order']}

CONTRACT PRICE COMPARISON (from system records):
{evidence['contract_prices']}

CUSTOMER PROFILE:
  Payment Risk    : {evidence['customer']['payment_risk'] if evidence['customer'] else 'unknown'}
  Dispute History : {evidence['customer']['dispute_history'] if evidence['customer'] else 'unknown'}

{drive_section}

Based on ALL of the above evidence and the stated finance policies, determine the most appropriate
resolution action. Your response must be ONLY valid JSON — no markdown fences, no commentary.

Use exactly this shape:
{{
  "recommended_action": "credit_memo" | "corrected_invoice" | "escalate_to_sales" | "proceed_with_collection",
  "reason": "One or two sentences explaining your decision.",
  "policy_references": ["List of policy clauses that apply"],
  "financial_impact": <number — the dollar amount being resolved>,
  "human_approval_required": true | false,
  "confidence": <0.0–1.0>
}}

Rules:
- credit_memo          → human_approval_required MUST be true
- escalate_to_sales    → human_approval_required MUST be true
- corrected_invoice    → human_approval_required false (system can auto-correct)
- proceed_with_collection → human_approval_required false
- Per policy: credit memo for valid pricing disputes under $500; escalate at $500+
""".strip()

def analyze_dispute(dispute: dict) -> DisputeRecommendation:
    """
    Run the full dispute investigation for a single dispute record and
    return a structured recommendation dict.
    """
    from pathlib import Path

    # Load policy text
    policy_path = Path(__file__).parent.parent / "data" / "policy.txt"
    policy_text = policy_path.read_text(encoding="utf-8") if policy_path.exists() else "No policy found."

    # 1. Gather structured evidence from JSON data files
    evidence = _gather_evidence(dispute)

    # 2. Determine which SKU to look up in Drive
    #    Use the first SKU on the order, or fall back to a generic name
    sku = "UNKNOWN-SKU"
    if evidence["order"] and evidence["order"].get("lines"):
        sku = evidence["order"]["lines"][0]["sku"]

    # 3. Fetch contract PDF from Google Drive
    drive_result = _fetch_drive_contract(dispute["customer_id"], sku)

    # 4. Ask Gemini for a resolution recommendation
    prompt       = _build_prompt(evidence, drive_result, policy_text)
    gemini_result = call_gemini_json(prompt)

    # 5. If Gemini fails, apply deterministic fallback based on policy
    if "error" in gemini_result:
        amount = float(dispute.get("amount_in_dispute", 0))
        if amount >= 500:
            fallback_action   = "escalate_to_sales"
            fallback_required = True
            fallback_reason   = f"Gemini unavailable. Amount ${amount} ≥ $500 — escalating per policy."
        else:
            fallback_action   = "credit_memo"
            fallback_required = True
            fallback_reason   = f"Gemini unavailable. Amount ${amount} < $500 — credit memo per policy."

        gemini_result = {
            "recommended_action":    fallback_action,
            "reason":                fallback_reason,
            "policy_references":     ["Dispute Policy §4"],
            "financial_impact":      amount,
            "human_approval_required": fallback_required,
            "confidence":            0.50,
        }

    return {
        # Core dispute identifiers
        "dispute_id":           dispute["dispute_id"],
        "invoice_id":           dispute["invoice_id"],
        "order_id":             dispute["order_id"],
        "customer_id":          dispute["customer_id"],
        "customer_name":        dispute["customer_name"],
        "dispute_reason":       dispute["dispute_reason"],
        "amount_in_dispute":    dispute["amount_in_dispute"],
        "status":               dispute["status"],

        # Evidence summary
        "contract_prices":      evidence["contract_prices"],
        "drive_contract":       drive_result,

        # Gemini recommendation
        "recommended_action":   gemini_result.get("recommended_action"),
        "reason":               gemini_result.get("reason"),
        "policy_references":    gemini_result.get("policy_references", []),
        "financial_impact":     gemini_result.get("financial_impact"),
        "human_approval_required": gemini_result.get("human_approval_required", True),
        "confidence":           gemini_result.get("confidence", 0.0),
    }


def run_disputes(dispute_id: str | None = None) -> list[DisputeRecommendation]:
    """
    Run dispute analysis.

    - If dispute_id is provided, analyse that specific dispute (any status).
    - Otherwise, analyse all disputes with status == 'open'.
    """
    disputes = load_json("disputes.json")

    if dispute_id is not None:
        target = find_one(disputes, "dispute_id", dispute_id)
        if target is None:
            return []
        return [analyze_dispute(target)]

    open_disputes = [d for d in disputes if d["status"] == "open"]
    return [analyze_dispute(d) for d in open_disputes]