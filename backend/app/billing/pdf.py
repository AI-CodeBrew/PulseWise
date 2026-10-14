"""Invoice PDFs (fpdf2: pure Python, no system libraries needed).

The built-in PDF fonts only know Latin letters, so any other character (Urdu script, emoji...) is replaced by "?".
Business names in Roman Urdu / English print fine.
"""

from datetime import date
from decimal import Decimal

from fpdf import FPDF

from app.models import Client, Invoice

ACCENT = (42, 120, 214)
INK = (11, 11, 11)
MUTED = (110, 108, 102)
LINE = (214, 213, 206)

SYMBOLS = {"PKR": "Rs ", "USD": "$"}


def latin(text: str | None) -> str:
    """Make text safe for the built-in PDF fonts."""
    return (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-").encode("latin-1", "replace").decode("latin-1")


def fmt(amount: Decimal | float | str, currency: str) -> str:
    return f"{SYMBOLS.get(currency, currency + ' ')}{Decimal(str(amount)):,.2f}"


def fmt_date(value: date | None) -> str:
    return value.strftime("%d %b %Y") if value else "-"


def invoice_pdf(invoice: Invoice, client: Client, *, business_name: str, business_address: str, payment_instructions: str, footer: str, paid_total: Decimal, logo: bytes | None = None) -> bytes:
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)
    pdf.set_title(latin(f"Invoice {invoice.number}"))
    pdf.set_author(latin(business_name))

    # --- header: logo or name on the left, "INVOICE" on the right
    top = pdf.get_y()
    left_x = 18
    if logo:
        try:
            pdf.image(logo, x=left_x, y=top, h=14)
            pdf.set_xy(left_x, top + 16)
        except Exception:  # noqa: BLE001 - a broken logo must never stop an invoice from being created
            pdf.set_xy(left_x, top)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(100, 8, latin(business_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    if business_address:
        pdf.multi_cell(100, 4.5, latin(business_address), new_x="LMARGIN", new_y="NEXT")
    left_bottom = pdf.get_y()

    pdf.set_xy(120, top)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*ACCENT)
    pdf.cell(72, 10, "INVOICE", align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*INK)
    for label, value in (("Number", invoice.number), ("Issued", fmt_date(invoice.issue_date)), ("Due", fmt_date(invoice.due_date))):
        pdf.set_x(120)
        pdf.cell(30, 5.5, label, align="R")
        pdf.cell(42, 5.5, latin(value), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 8)

    # --- bill to
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "BILL TO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, latin(client.name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for line in (client.contact_email, client.phone):
        if line:
            pdf.cell(0, 5, latin(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # --- line items
    pdf.set_draw_color(*LINE)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(130, 7, "DESCRIPTION", border="B")
    pdf.cell(44, 7, "AMOUNT", border="B", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*INK)
    for item in invoice.line_items or []:
        y = pdf.get_y()
        pdf.multi_cell(130, 6.5, latin(str(item.get("description", ""))), new_x="RIGHT", new_y="TOP")
        pdf.set_xy(148, y)
        pdf.cell(44, 6.5, fmt(item.get("amount", 0), invoice.currency), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(max(pdf.get_y(), y + 6.5))
        pdf.line(18, pdf.get_y() + 1, 192, pdf.get_y() + 1)
        pdf.ln(2)

    # --- totals
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(130, 8, "Total", align="R")
    pdf.cell(44, 8, fmt(invoice.amount, invoice.currency), align="R", new_x="LMARGIN", new_y="NEXT")
    if paid_total > 0:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(130, 6, "Paid", align="R")
        pdf.cell(44, 6, fmt(paid_total, invoice.currency), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(130, 6, "Balance due", align="R")
        pdf.cell(44, 6, fmt(max(Decimal(str(invoice.amount)) - paid_total, Decimal("0")), invoice.currency), align="R", new_x="LMARGIN", new_y="NEXT")

    # --- status stamp
    status_text = {"paid": "PAID", "void": "CANCELLED"}.get(invoice.status)
    if status_text:
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*(ACCENT if invoice.status == "paid" else MUTED))
        pdf.cell(0, 8, status_text + (f" on {fmt_date(invoice.paid_at.date())}" if invoice.status == "paid" and invoice.paid_at else ""), new_x="LMARGIN", new_y="NEXT")

    # --- how to pay
    if payment_instructions and invoice.status == "open":
        pdf.ln(8)
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "How to pay", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5.5, latin(payment_instructions), new_x="LMARGIN", new_y="NEXT")
    if invoice.notes:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 5, latin(invoice.notes), new_x="LMARGIN", new_y="NEXT")
    if footer:
        pdf.set_y(-26)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, latin(footer), align="C")

    return bytes(pdf.output())
