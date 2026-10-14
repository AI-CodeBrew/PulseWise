"""A weekly report as an HTML email, a plain-text email, and a PDF."""

import html
from datetime import date
from typing import Any

from fpdf import FPDF

from app.billing.pdf import ACCENT, INK, LINE, MUTED, latin

DIRECTION = {"en": "ltr", "roman_ur": "ltr", "ur": "rtl"}
LABELS = {  # the labels around the numbers stay in English (the summary text is what gets translated)
    "visitors": "Visitors", "pageviews": "Pageviews", "sessions": "Visits", "avg_session_duration": "Average visit", "bounce_rate": "Left after 1 page",
}


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def kpi_value(key: str, metric: dict[str, Any]) -> str:
    value = metric["current"]
    if key == "avg_session_duration":
        return fmt_duration(value)
    if key == "bounce_rate":
        return f"{value:.0f}%"
    return f"{int(value):,}"


def change_text(metric: dict[str, Any], *, good_when_down: bool = False) -> tuple[str, str]:
    """('+12% vs last week', 'up'|'down'|'same'|'new')"""
    pct = metric["change_pct"]
    if pct is None:
        return "new", "new"
    if abs(pct) < 1:
        return "no change", "same"
    return f"{'+' if pct > 0 else ''}{pct:g}% vs last week", "up" if pct > 0 else "down"


def period_label(period: dict[str, Any]) -> str:
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    if start.month == end.month:
        return f"{start.day}-{end.day} {end:%b %Y}"
    return f"{start.day} {start:%b} - {end.day} {end:%b %Y}"


def sales_lines(d: dict[str, Any]) -> list[tuple[str, str]]:
    """(label, value) rows for the store's week, or [] when there is no store."""
    sales = d.get("sales")
    if not sales:
        return []
    cur = sales["currency"]
    rows = [
        ("Orders", f"{sales['orders']['current']:,} ({change_text(sales['orders'])[0]})"),
        ("Sales", f"{cur} {sales['revenue']['current']:,.0f} ({change_text(sales['revenue'])[0]})".strip()),
        ("Average order", f"{cur} {sales['average_order_value']['current']:,.0f}".strip()),
    ]
    if sales.get("top_product"):
        rows.append(("Best seller", sales["top_product"]["title"]))
    return rows


def render_text(report: dict[str, Any], website_name: str, dashboard_url: str) -> str:
    d, s = report["data"], report["summary"]
    lines = [f"Weekly report: {website_name} ({period_label(d['period'])})", "", s["headline"], ""]
    lines += [f"- {b}" for b in s["bullets"]]
    if s["recommendation"]:
        lines += ["", f"What to do this week: {s['recommendation']}"]
    lines += ["", "The numbers:"]
    for key, label in LABELS.items():
        lines.append(f"  {label}: {kpi_value(key, d['kpis'][key])} ({change_text(d['kpis'][key])[0]})")
    if sales_lines(d):
        lines += ["", "Your store:"] + [f"  {label}: {value}" for label, value in sales_lines(d)]
    if d["top_pages"]:
        lines += ["", "Most viewed pages:"] + [f"  {p['path']}: {p['views']} views" for p in d["top_pages"]]
    lines += ["", f"See everything in your dashboard: {dashboard_url}"]
    return "\n".join(lines)


def render_html(report: dict[str, Any], website_name: str, client_name: str, dashboard_url: str, brand: str) -> str:
    """An email-safe page: inline styles only, every piece of data escaped."""
    e = html.escape
    d, s = report["data"], report["summary"]
    rtl = DIRECTION.get(report["language"], "ltr") == "rtl"
    arrow = {"up": "▲", "down": "▼", "same": "●", "new": "●"}

    cards = []
    for key, label in LABELS.items():
        metric = d["kpis"][key]
        text, direction = change_text(metric)
        cards.append(
            f'<td style="padding:12px;border:1px solid #e1e0d9;border-radius:8px;width:20%;vertical-align:top">'
            f'<div style="font-size:12px;color:#6e6c66">{e(label)}</div>'
            f'<div style="font-size:22px;font-weight:600;margin:4px 0">{e(kpi_value(key, metric))}</div>'
            f'<div style="font-size:12px;color:#6e6c66">{arrow[direction]} {e(text)}</div></td>'
        )
    bullets = "".join(f'<li style="margin:6px 0">{e(b)}</li>' for b in s["bullets"])
    pages = "".join(
        f'<tr><td style="padding:4px 0;word-break:break-all">{e(p["path"])}</td><td style="padding:4px 0;text-align:right">{p["views"]:,}</td></tr>' for p in d["top_pages"]
    )
    store = "".join(f'<tr><td style="padding:4px 0">{e(label)}</td><td style="padding:4px 0;text-align:right">{e(value)}</td></tr>' for label, value in sales_lines(d))
    store_table = (
        f'<table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:8px"><tr><td colspan="2" style="font-weight:600;padding:8px 0;border-bottom:1px solid #e1e0d9">Your store</td></tr>{store}</table>'
        if store else ""
    )
    sources = "".join(f'<tr><td style="padding:4px 0">{e(x["name"])}</td><td style="padding:4px 0;text-align:right">{x["sessions"]:,}</td></tr>' for x in d["sources"])
    return f"""<!doctype html><html><body style="margin:0;background:#f6f6f3;font-family:Segoe UI,Arial,sans-serif;color:#0b0b0b">
<div style="max-width:640px;margin:0 auto;padding:24px 16px">
<p style="font-size:13px;color:#6e6c66;margin:0 0 4px">{e(brand)} · weekly report</p>
<h1 style="font-size:20px;margin:0 0 16px">{e(website_name)} <span style="color:#6e6c66;font-weight:400">· {e(period_label(d["period"]))}</span></h1>
<div dir="{'rtl' if rtl else 'ltr'}" style="background:#fff;border:1px solid #e1e0d9;border-radius:12px;padding:20px;margin-bottom:16px">
<p style="font-size:17px;font-weight:600;margin:0 0 12px">{e(s["headline"])}</p>
<ul style="padding-{'right' if rtl else 'left'}:20px;margin:0 0 12px">{bullets}</ul>
<p style="margin:0;padding:12px;background:#eef4fc;border-radius:8px"><strong>{"اس ہفتے کیا کریں" if report["language"] == "ur" else "What to do this week"}:</strong> {e(s["recommendation"])}</p>
</div>
<table style="width:100%;border-collapse:separate;border-spacing:6px 0;margin-bottom:16px"><tr>{"".join(cards)}</tr></table>
{store_table}<table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:8px"><tr><td colspan="2" style="font-weight:600;padding:8px 0;border-bottom:1px solid #e1e0d9">Most viewed pages</td></tr>{pages}</table>
<table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:16px"><tr><td colspan="2" style="font-weight:600;padding:8px 0;border-bottom:1px solid #e1e0d9">Where visitors came from</td></tr>{sources}</table>
<p style="margin:20px 0"><a href="{e(dashboard_url)}" style="background:#2a78d6;color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px;display:inline-block">Open your dashboard</a></p>
<p style="font-size:12px;color:#6e6c66">{e(client_name)} · a PDF copy is attached. The numbers are exact; the sentences are an automatic summary of them.</p>
</div></body></html>"""


def report_pdf(report: dict[str, Any], website_name: str, client_name: str, brand: str, logo: bytes | None = None) -> bytes:
    d, s = report["data"], report["summary"]
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.set_margins(16, 16, 16)
    pdf.set_title(latin(f"Weekly report: {website_name}"))

    top = pdf.get_y()
    if logo:
        try:
            pdf.image(logo, x=16, y=top, h=12)
            pdf.set_y(top + 14)
        except Exception:  # noqa: BLE001 - a broken logo must not stop the report
            pdf.set_y(top)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, latin(f"{brand} - weekly report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 8, latin(website_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, latin(f"{client_name}  |  {period_label(d['period'])}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # The sentences: PDF fonts can't draw Urdu script, so an Urdu report keeps the text in the email / dashboard.
    pdf.set_text_color(*INK)
    if report["language"] == "ur":
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 5.5, "The written summary of this report is in Urdu: you can read it in the email and in your dashboard. This PDF has the numbers.", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 6.5, latin(s["headline"]), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 10)
        for bullet in s["bullets"]:
            pdf.multi_cell(0, 5.5, latin("-  " + bullet), new_x="LMARGIN", new_y="NEXT")
        if s["recommendation"]:
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*ACCENT)
            pdf.multi_cell(0, 5.5, latin("What to do this week: " + s["recommendation"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # KPI table
    pdf.set_draw_color(*LINE)
    pdf.set_text_color(*MUTED)
    pdf.set_font("Helvetica", "B", 8)
    for header, width in (("", 60), ("THIS WEEK", 40), ("LAST WEEK", 40), ("CHANGE", 36)):
        pdf.cell(width, 6, header, border="B", align="L" if not header else "R")
    pdf.ln()
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*INK)
    for key, label in LABELS.items():
        metric = d["kpis"][key]
        previous = {**metric, "current": metric["previous"]}
        pdf.cell(60, 7, label)
        pdf.cell(40, 7, kpi_value(key, metric), align="R")
        pdf.cell(40, 7, kpi_value(key, previous), align="R")
        pdf.cell(36, 7, latin(change_text(metric)[0].replace(" vs last week", "")), align="R")
        pdf.ln()
    pdf.ln(5)

    def table(title: str, rows: list[tuple[str, str]]) -> None:
        if not rows:
            return
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*INK)
        pdf.cell(0, 7, title, border="B", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for name, value in rows:
            pdf.cell(140, 6, latin(name)[:70])
            pdf.cell(36, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    table("Your store", [(label, value) for label, value in sales_lines(d)])
    table("Most viewed pages", [(p["path"], f"{p['views']:,} views") for p in d["top_pages"]])
    table("Where visitors came from", [(x["name"], f"{x['sessions']:,} visits") for x in d["sources"]])
    table("Countries", [(x["name"], f"{x['visitors']:,} visitors") for x in d["countries"]])
    table("Devices", [(x["name"], f"{x['visitors']:,} visitors") for x in d["devices"]])
    table("Actions people took", [(x["event"], f"{x['count']:,} times") for x in d["custom_events"]])

    pdf.set_y(-20)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "The numbers are exact. The sentences are an automatic summary of them.", align="C")
    return bytes(pdf.output())
