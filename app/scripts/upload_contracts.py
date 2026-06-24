"""
scripts/upload_contracts.py
============================
Creates two minimal contract PDFs and uploads them to the Google Drive
folder specified by GDRIVE_CONTRACTS_FOLDER_ID.

Run this once to stage the demo data before presenting to judges.

Usage
-----
  # Make sure you have run drive_auth.py first (OAuth) or set
  # GDRIVE_SERVICE_ACCOUNT_JSON (Service Account)

  python scripts/upload_contracts.py

What it uploads
---------------
  CUST-1001-SKU-LAPTOP-14.pdf      Contract: Northstar Retail, SKU-LAPTOP-14 @ $950
  CUST-2002-SKU-MONITOR-27.pdf     Contract: MetroBuild Supplies, SKU-MONITOR-27 @ $220
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# We use reportlab to generate PDFs if available, otherwise fpdf2, otherwise
# we write a minimal hand-crafted PDF (no dependencies needed).
def _make_pdf_bytes(text: str) -> bytes:
    """Generate a simple single-page PDF containing `text`."""

    # ── Try reportlab ──────────────────────────────────────────────────────
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        import io

        buf = io.BytesIO()
        c   = canvas.Canvas(buf, pagesize=letter)
        c.setFont("Helvetica", 12)
        y = 750
        for line in text.split("\n"):
            c.drawString(50, y, line)
            y -= 18
            if y < 50:
                c.showPage()
                y = 750
        c.save()
        return buf.getvalue()
    except ImportError:
        pass

    # ── Try fpdf2 ──────────────────────────────────────────────────────────
    try:
        from fpdf import FPDF
        import io

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        for line in text.split("\n"):
            pdf.cell(0, 8, line, ln=True)
        return pdf.output()
    except ImportError:
        pass

    # ── Minimal hand-crafted PDF (no library) ─────────────────────────────
    # Produces a valid single-page PDF with the text as a stream.
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines     = safe_text.split("\n")

    text_ops = "\n".join(f"({line}) Tj\n0 -18 Td" for line in lines)

    stream_content = (
        "BT\n"
        "/F1 12 Tf\n"
        "50 750 Td\n"
        f"{text_ops}\n"
        "ET"
    )

    stream_bytes = stream_content.encode("latin-1")
    stream_len   = len(stream_bytes)

    pdf_str = (
        "%PDF-1.4\n"
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        "   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n"
    ).encode("latin-1") + stream_bytes + (
        b"\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000274 00000 n \n"
        b"0000000400 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n490\n%%EOF\n"
    )
    return pdf_str


# ---------------------------------------------------------------------------
# Contract content
# ---------------------------------------------------------------------------

CONTRACTS = [
    {
        "filename":    "CUST-1001-SKU-LAPTOP-14.pdf",
        "content":     (
            "SUPPLY CONTRACT\n"
            "================\n\n"
            "Party A (Supplier): CashGuard Distributors Ltd.\n"
            "Party B (Customer): Northstar Retail\n"
            "Customer ID: CUST-1001\n\n"
            "PRODUCT SCHEDULE\n"
            "----------------\n"
            "SKU          : SKU-LAPTOP-14\n"
            "Description  : 14-inch Business Laptop\n"
            "Contract Price: $950.00 per unit\n"
            "Payment Terms : Net 30\n\n"
            "This price is valid for purchase orders placed in 2026.\n"
            "Any deviation from the above unit price requires written approval\n"
            "from the Sales Director before invoicing.\n\n"
            "Signed: ___________________    Date: ___________\n"
        ),
    },
    {
        "filename":    "CUST-2002-SKU-MONITOR-27.pdf",
        "content":     (
            "SUPPLY CONTRACT\n"
            "================\n\n"
            "Party A (Supplier): CashGuard Distributors Ltd.\n"
            "Party B (Customer): MetroBuild Supplies\n"
            "Customer ID: CUST-2002\n\n"
            "PRODUCT SCHEDULE\n"
            "----------------\n"
            "SKU          : SKU-MONITOR-27\n"
            "Description  : 27-inch Commercial Monitor\n"
            "Contract Price: $220.00 per unit\n"
            "Payment Terms : Net 30\n\n"
            "IMPORTANT: Customer's quoted price of $210 is NOT the contracted rate.\n"
            "The contracted unit price is $220. Any order submitted at $210 constitutes\n"
            "a pricing mismatch and must be reviewed by the Finance team.\n\n"
            "Signed: ___________________    Date: ___________\n"
        ),
    },
]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def main():
    folder_id = os.environ.get("GDRIVE_CONTRACTS_FOLDER_ID")
    if not folder_id:
        print(
            "❌  GDRIVE_CONTRACTS_FOLDER_ID is not set.\n"
            "    Set it in your .env file — it's the ID from the Drive folder URL:\n"
            "    https://drive.google.com/drive/folders/<FOLDER_ID>"
        )
        sys.exit(1)

    from app.drive_client import upload_pdf_to_folder

    with tempfile.TemporaryDirectory() as tmpdir:
        for contract in CONTRACTS:
            local_path = Path(tmpdir) / contract["filename"]
            local_path.write_bytes(_make_pdf_bytes(contract["content"]))

            print(f"Uploading {contract['filename']} ...", end=" ", flush=True)
            result = upload_pdf_to_folder(str(local_path), folder_id)
            print(f"✅  {result.get('webViewLink', result.get('id'))}")

    print("\nAll contracts uploaded. Add the folder ID to your .env:")
    print(f"  GDRIVE_CONTRACTS_FOLDER_ID={folder_id}")


if __name__ == "__main__":
    main()