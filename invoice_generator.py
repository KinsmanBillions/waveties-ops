#!/usr/bin/env python3
"""
Shipping Invoice Generator – B.Y.B Port style
Modern, clean PDF invoices for sea / air / road freight.
Company name, logo and branding are fully configurable.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable, Flowable
)
from datetime import datetime, timedelta
from pathlib import Path
import json

# ──────────────────────────────────────────────────────────────
# CONFIGURATION – update when you have final name & logo
# ──────────────────────────────────────────────────────────────
COMPANY = {
    "name": "WAVETIES LOGISTICS AND SUPPLY CHAIN SOLUTIONS",
    "short_name": "WaveTies",
    "tagline": "Stronger Ties",
    "phone": "+233 (0)24 600 6186",
    "email": "billing@waveties.com",
    "address": "Accra, Ghana",
    "logo_path": str(Path(__file__).parent / "logo_waveties_badge.png"),
    # Brand colours from logo (deep navy + cyan)
    "primary": colors.HexColor("#00B4D8"),      # cyan / teal from logo
    "primary_dark": colors.HexColor("#0077B6"),
    "header_bg": colors.HexColor("#0A2540"),    # deep navy
    "light_bg": colors.HexColor("#F0F9FF"),
    "row_alt": colors.HexColor("#E8F4FC"),
    "text": colors.HexColor("#1A1A2E"),
    "muted": colors.HexColor("#5A6A7A"),
    "momo": "NANA KWAME KUSI-OHEMENG - 0206027020",
    "bank_lines": [
        "DEGREENS INNOVATION LTD",
        "STANBIC BANK, MADINA MAIN",
        "9040014136600",
    ],
}

DEFAULT_CURRENCY = "USD"


class ColoredBox(Flowable):
    """Simple coloured rectangle used as accent bar."""
    def __init__(self, width, height, color):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)


def create_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="CompanyName",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=COMPANY["header_bg"],
        alignment=TA_LEFT,
        spaceAfter=1,
        leading=13,
    ))
    styles.add(ParagraphStyle(
        name="InvoiceTitle",
        fontName="Helvetica-Bold",
        fontSize=26,
        textColor=COMPANY["header_bg"],
        alignment=TA_RIGHT,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="BillToLabel",
        fontName="Helvetica",
        fontSize=8,
        textColor=COMPANY["muted"],
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="CustomerName",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=COMPANY["text"],
        spaceAfter=1,
    ))
    styles.add(ParagraphStyle(
        name="CustomerEmail",
        fontName="Helvetica",
        fontSize=9,
        textColor=COMPANY["muted"],
    ))
    styles.add(ParagraphStyle(
        name="MetaLabel",
        fontName="Helvetica",
        fontSize=8,
        textColor=COMPANY["muted"],
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="MetaValue",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=COMPANY["text"],
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="TableHeader",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        textColor=colors.white,
        alignment=TA_CENTER,
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name="TableCell",
        fontName="Helvetica",
        fontSize=7.5,
        textColor=COMPANY["text"],
        alignment=TA_CENTER,
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name="TableCellLeft",
        fontName="Helvetica",
        fontSize=7.5,
        textColor=COMPANY["text"],
        alignment=TA_LEFT,
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name="TableCellRight",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        textColor=COMPANY["text"],
        alignment=TA_RIGHT,
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name="Notes",
        fontName="Helvetica",
        fontSize=8,
        textColor=COMPANY["text"],
        leading=11,
    ))
    styles.add(ParagraphStyle(
        name="Notice",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        textColor=COMPANY["primary_dark"],
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name="TotalsLabel",
        fontName="Helvetica",
        fontSize=9,
        textColor=COMPANY["muted"],
        alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="TotalsValue",
        fontName="Helvetica",
        fontSize=9,
        textColor=COMPANY["text"],
        alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="BalanceLabel",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=COMPANY["primary"],
        alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="BalanceValue",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=COMPANY["primary"],
        alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="Footer",
        fontName="Helvetica",
        fontSize=7,
        textColor=COMPANY["muted"],
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="Tagline",
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=COMPANY["primary_dark"],
        alignment=TA_CENTER,
        leading=10,
        spaceBefore=0,
        spaceAfter=0,
    ))
    return styles


def build_header(styles):
    """Header: logo (with WaveTies wordmark) + tagline centered under it + INVOICE."""
    logo_path = COMPANY.get("logo_path") or ""
    if logo_path and Path(logo_path).exists():
        logo = Image(logo_path, width=52*mm, height=32*mm)
        logo.hAlign = "CENTER"
        brand_rows = [[logo]]
        if COMPANY.get("tagline"):
            brand_rows.append([Paragraph(COMPANY["tagline"], styles["Tagline"])])
        left = Table(brand_rows, colWidths=[55*mm])
        left.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 1), (-1, 1), 1),
        ]))
    else:
        parts = [Paragraph(COMPANY.get("short_name") or COMPANY["name"], styles["CompanyName"])]
        if COMPANY.get("tagline"):
            parts.append(Paragraph(COMPANY["tagline"], styles["Tagline"]))
        left = parts

    right = [Paragraph("INVOICE", styles["InvoiceTitle"])]

    t = Table([[left, right]], colWidths=[100*mm, 80*mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    return t


def build_bill_to_and_meta(styles, data):
    bill_to = [
        Paragraph("Bill To:", styles["BillToLabel"]),
        Paragraph(data.get("customer_name", ""), styles["CustomerName"]),
    ]
    if data.get("customer_email"):
        bill_to.append(Paragraph(data["customer_email"], styles["CustomerEmail"]))

    inv_no = data.get("invoice_no", "")
    inv_date = data.get("invoice_date", "")
    due_date = data.get("due_date", "")

    meta_rows = [
        [Paragraph("Invoice Number:", styles["MetaLabel"]),
         Paragraph(inv_no, styles["MetaValue"])],
        [Paragraph("Date:", styles["MetaLabel"]),
         Paragraph(inv_date, styles["MetaValue"])],
        [Paragraph("Due Date:", styles["MetaLabel"]),
         Paragraph(f'<font color="#00B4D8">{due_date}</font>', styles["MetaValue"])],
    ]
    meta_table = Table(meta_rows, colWidths=[32*mm, 40*mm])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, COMPANY["primary"]),
    ]))

    outer = Table([[bill_to, meta_table]], colWidths=[105*mm, 75*mm])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def build_items_table(styles, items, currency=DEFAULT_CURRENCY):
    header = [
        Paragraph("Tracking No.", styles["TableHeader"]),
        Paragraph("Item Name", styles["TableHeader"]),
        Paragraph("Transport", styles["TableHeader"]),
        Paragraph("Boxes", styles["TableHeader"]),
        Paragraph("Wt (kg)", styles["TableHeader"]),
        Paragraph("Vol (CBM)", styles["TableHeader"]),
        Paragraph("Order Number", styles["TableHeader"]),
        Paragraph("Amount", styles["TableHeader"]),
    ]

    rows = [header]
    for it in items:
        amount = it.get("amount", 0)
        amount_str = f"{currency} {amount:,.2f}"
        rows.append([
            Paragraph(str(it.get("tracking", "")), styles["TableCell"]),
            Paragraph(str(it.get("item_name", "")), styles["TableCellLeft"]),
            Paragraph(str(it.get("transport", "")), styles["TableCell"]),
            Paragraph(str(it.get("boxes", 1)), styles["TableCell"]),
            Paragraph(f"{it.get('weight_kg', 0):.1f}", styles["TableCell"]),
            Paragraph(f"{it.get('vol_cbm', 0):.2f}", styles["TableCell"]),
            Paragraph(str(it.get("order_number", "") or "—"), styles["TableCell"]),
            Paragraph(amount_str, styles["TableCellRight"]),
        ])

    col_widths = [32*mm, 32*mm, 22*mm, 14*mm, 16*mm, 18*mm, 22*mm, 24*mm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COMPANY["header_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COMPANY["row_alt"]]),
        ("BOX", (0, 0), (-1, -1), 0.6, COMPANY["header_bg"]),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, colors.HexColor("#E0E0E0")),
    ]
    table.setStyle(TableStyle(style_cmds))
    return table


def build_notes_and_totals(styles, data):
    currency = data.get("currency", DEFAULT_CURRENCY)
    subtotal = data.get("subtotal", 0)
    tax = data.get("tax", 0)
    total = data.get("total", subtotal + tax)
    paid = data.get("paid", 0)
    balance = data.get("balance_due", total - paid)

    momo = (data.get("momo") or "").strip() or COMPANY.get("momo", "")
    momo_provider = (data.get("momo_provider") or "").strip() or "TELECEL CASH"
    bank_lines = data.get("bank_lines") or COMPANY.get("bank_lines", [])
    if isinstance(bank_lines, str):
        bank_lines = [bank_lines]
    bank_html = "<br/>".join(bank_lines)
    phone = data.get("contact_phone") or COMPANY["phone"]

    notes_text = f"""
    <b>Notes:</b><br/>
    Payment can be made into the accounts below:<br/>
    <b>{momo_provider}:</b> {momo}<br/>
    <b>BANK:</b> {bank_html}<br/><br/>
    If you have any query about this invoice please contact us on: {phone}.
    """
    notes_para = Paragraph(notes_text, styles["Notes"])
    notice = Paragraph(
        "THIS INVOICE IS VALID FOR 48 HOURS FROM ISSUE DATE<br/>TERMS AND CONDITIONS APPLY.",
        styles["Notice"]
    )
    left_content = [notes_para, Spacer(1, 4*mm), notice]

    totals_data = [
        [Paragraph("Subtotal:", styles["TotalsLabel"]),
         Paragraph(f"{currency} {subtotal:,.2f}", styles["TotalsValue"])],
        [Paragraph("Tax:", styles["TotalsLabel"]),
         Paragraph(f"{currency} {tax:,.2f}", styles["TotalsValue"])],
        [Paragraph("Total:", styles["TotalsLabel"]),
         Paragraph(f"<b>{currency} {total:,.2f}</b>", styles["TotalsValue"])],
        [Paragraph("Paid:", styles["TotalsLabel"]),
         Paragraph(f"({currency} {paid:,.2f})", styles["TotalsValue"])],
    ]
    totals_table = Table(totals_data, colWidths=[30*mm, 35*mm])
    totals_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 2), (-1, 2), 0.8, COMPANY["header_bg"]),
    ]))

    balance_data = [
        [Paragraph("Balance Due:", styles["BalanceLabel"]),
         Paragraph(f"{currency} {balance:,.2f}", styles["BalanceValue"])],
    ]
    balance_table = Table(balance_data, colWidths=[30*mm, 35*mm])
    balance_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF0E0")),
        ("BOX", (0, 0), (-1, -1), 1.2, COMPANY["primary"]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    right_content = [totals_table, Spacer(1, 3*mm), balance_table]

    outer = Table([[left_content, right_content]], colWidths=[110*mm, 70*mm])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def generate_invoice(data: dict, output_path: str):
    """
    Generate a modern B.Y.B-style shipping invoice PDF.

    Expected data keys:
        invoice_no, invoice_date, due_date,
        customer_name, customer_email,
        items: list of {
            tracking, item_name, transport, boxes,
            weight_kg, vol_cbm, order_number, amount
        },
        subtotal, tax, total, paid, balance_due, currency,
        momo, bank_lines, contact_phone  (all optional overrides)
    """
    styles = create_styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=14*mm,
        leftMargin=14*mm,
        topMargin=12*mm,
        bottomMargin=12*mm,
    )

    story = []
    story.append(ColoredBox(182*mm, 2.2*mm, COMPANY["primary"]))
    story.append(Spacer(1, 5*mm))
    story.append(build_header(styles))
    story.append(Spacer(1, 5*mm))
    story.append(build_bill_to_and_meta(styles, data))
    story.append(Spacer(1, 6*mm))

    items = data.get("items", [])
    currency = data.get("currency", DEFAULT_CURRENCY)
    story.append(build_items_table(styles, items, currency))
    story.append(Spacer(1, 7*mm))
    story.append(build_notes_and_totals(styles, data))
    story.append(Spacer(1, 8*mm))

    story.append(HRFlowable(
        width="100%", thickness=0.4,
        color=colors.HexColor("#CCCCCC"), spaceBefore=2, spaceAfter=3
    ))
    story.append(Paragraph(
        f"Generated by {COMPANY['short_name']} Invoicing System  •  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        styles["Footer"]
    ))

    doc.build(story)
    return output_path


# ──────────────────────────────────────────────────────────────


def next_receipt_no(db):
    now = datetime.now()
    prefix = f"RCT-{now.strftime('%Y%m')}-"
    seq = int(db.get("next_receipt_seq") or 1)
    db["next_receipt_seq"] = seq + 1
    return f"{prefix}{seq:04d}"


def generate_receipt(data: dict, output_path: str):
    """Official payment receipt PDF — layout similar to professional port receipts.

    Expected keys:
      receipt_no, receipt_date, method, reference,
      customer_name, customer_email, customer_phone,
      invoice_no, currency,
      amount_received, amount_allocated, amount_unallocated,
      notes (optional)
    """
    styles = create_styles()

    def _add(**kw):
        try:
            styles.add(ParagraphStyle(**kw))
        except Exception:
            pass

    _add(name="ReceiptTitle", fontName="Helvetica-Bold", fontSize=18,
         textColor=COMPANY["header_bg"], alignment=TA_RIGHT, leading=22)
    _add(name="ReceiptMetaLabel", fontName="Helvetica", fontSize=8,
         textColor=COMPANY["muted"], leading=11)
    _add(name="ReceiptMetaValue", fontName="Helvetica-Bold", fontSize=9,
         textColor=COMPANY["text"], leading=12)
    _add(name="ReceiptFromLabel", fontName="Helvetica", fontSize=8,
         textColor=COMPANY["muted"], leading=10)
    _add(name="ReceiptFromName", fontName="Helvetica-Bold", fontSize=11,
         textColor=COMPANY["text"], leading=14)
    _add(name="ReceiptAmtLabel", fontName="Helvetica", fontSize=8,
         textColor=COMPANY["muted"], alignment=TA_CENTER, leading=10)
    _add(name="ReceiptAmtValue", fontName="Helvetica-Bold", fontSize=14,
         textColor=COMPANY["text"], alignment=TA_CENTER, leading=18)
    _add(name="ReceiptAmtGreen", fontName="Helvetica-Bold", fontSize=14,
         textColor=colors.HexColor("#059669"), alignment=TA_CENTER, leading=18)
    _add(name="ReceiptAmtOrange", fontName="Helvetica-Bold", fontSize=14,
         textColor=colors.HexColor("#EA580C"), alignment=TA_CENTER, leading=18)
    _add(name="ReceiptThanks", fontName="Helvetica-Oblique", fontSize=10,
         textColor=COMPANY["muted"], alignment=TA_CENTER, leading=14)

    doc = SimpleDocTemplate(

        output_path,
        pagesize=A4,
        rightMargin=16*mm,
        leftMargin=16*mm,
        topMargin=12*mm,
        bottomMargin=16*mm,
    )
    story = []

    # Top accent bar (orange/cyan like reference)
    accent = colors.HexColor("#F97316")  # warm orange accent like reference
    story.append(ColoredBox(178*mm, 2*mm, accent))
    story.append(Spacer(1, 6*mm))

    # Header: logo + company | PAYMENT RECEIPT
    logo_path = COMPANY.get("logo_path") or ""
    left_bits = []
    if logo_path and Path(logo_path).exists():
        try:
            left_bits.append(Image(logo_path, width=28*mm, height=28*mm))
        except Exception:
            pass
    left_bits.append(Spacer(1, 1.5*mm))
    left_bits.append(Paragraph(COMPANY.get("short_name") or "WaveTies", styles["CompanyName"]))
    left_bits.append(Paragraph(
        f'<font size="7" color="#5A6A7A">{COMPANY.get("tagline") or ""}</font>',
        styles["ReceiptFromLabel"],
    ))

    right_bits = [
        Paragraph("PAYMENT RECEIPT", styles["ReceiptTitle"]),
    ]
    header = Table([[left_bits, right_bits]], colWidths=[95*mm, 83*mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 8*mm))

    # Received From | meta (receipt no, date, method, ref)
    currency = data.get("currency") or "GHS"
    cust_name = data.get("customer_name") or "—"
    cust_email = data.get("customer_email") or ""
    cust_phone = data.get("customer_phone") or ""
    from_lines = [
        Paragraph("Received From", styles["ReceiptFromLabel"]),
        Spacer(1, 1*mm),
        Paragraph(cust_name, styles["ReceiptFromName"]),
    ]
    if cust_email:
        from_lines.append(Paragraph(
            f'<font size="8" color="#5A6A7A">{cust_email}</font>',
            styles["ReceiptFromLabel"],
        ))
    if cust_phone:
        from_lines.append(Paragraph(
            f'<font size="8" color="#5A6A7A">{cust_phone}</font>',
            styles["ReceiptFromLabel"],
        ))
    if data.get("invoice_no"):
        from_lines.append(Spacer(1, 2*mm))
        from_lines.append(Paragraph(
            f'<font size="8" color="#5A6A7A">Invoice: {data.get("invoice_no")}</font>',
            styles["ReceiptFromLabel"],
        ))

    meta_rows = [
        [Paragraph("Receipt No.", styles["ReceiptMetaLabel"]),
         Paragraph(str(data.get("receipt_no") or "—"), styles["ReceiptMetaValue"])],
        [Paragraph("Date:", styles["ReceiptMetaLabel"]),
         Paragraph(str(data.get("receipt_date") or "—"), styles["ReceiptMetaValue"])],
        [Paragraph("Method:", styles["ReceiptMetaLabel"]),
         Paragraph(str(data.get("method") or "—"), styles["ReceiptMetaValue"])],
        [Paragraph("Ref:", styles["ReceiptMetaLabel"]),
         Paragraph(str(data.get("reference") or "—"), styles["ReceiptMetaValue"])],
    ]
    meta_table = Table(meta_rows, colWidths=[28*mm, 50*mm])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, accent),
    ]))

    mid = Table([[from_lines, meta_table]], colWidths=[100*mm, 78*mm])
    mid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(mid)
    story.append(Spacer(1, 10*mm))

    # Amount boxes: Total Received | Allocated | Unallocated
    received = float(data.get("amount_received") or 0)
    allocated = float(data.get("amount_allocated") or received)
    unallocated = float(data.get("amount_unallocated") or max(0, received - allocated))

    def amt_cell(label, value, value_style):
        return [
            Paragraph(label, styles["ReceiptAmtLabel"]),
            Spacer(1, 2*mm),
            Paragraph(f"{currency} {value:,.2f}", styles[value_style]),
        ]

    boxes = Table([[
        amt_cell("Total Received", received, "ReceiptAmtValue"),
        amt_cell("Allocated", allocated, "ReceiptAmtGreen"),
        amt_cell("Unallocated", unallocated, "ReceiptAmtOrange"),
    ]], colWidths=[59*mm, 59*mm, 59*mm])
    boxes.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(boxes)
    story.append(Spacer(1, 10*mm))

    # Notes
    notes = (data.get("notes") or "").strip()
    story.append(Paragraph("Notes", styles["ReceiptFromLabel"]))
    story.append(Spacer(1, 2*mm))
    if notes:
        story.append(Paragraph(notes.replace("\n", "<br/>"), styles["ReceiptMetaValue"]))
    else:
        story.append(Spacer(1, 8*mm))

    story.append(Spacer(1, 20*mm))
    story.append(Paragraph("Thank you for your payment!", styles["ReceiptThanks"]))
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(
        width="40%", thickness=0.4, color=colors.HexColor("#CCCCCC"),
        spaceBefore=2, spaceAfter=3, hAlign="CENTER",
    ))
    story.append(Paragraph(
        f'<font size="7" color="#5A6A7A">{COMPANY.get("name") or ""} · '
        f'{COMPANY.get("phone") or ""} · {COMPANY.get("email") or ""}</font>',
        styles["ReceiptThanks"],
    ))

    doc.build(story)
    return output_path


def create_receipt_for_payment(invoice: dict, payment: dict, invoice_no: str) -> tuple:
    """Create receipt record + PDF for one invoice payment. Returns (receipt_no, pdf_path)."""
    db = load_db()
    receipt_no = next_receipt_no(db)
    currency = invoice.get("currency") or "GHS"
    amount = float(payment.get("amount") or 0)
    # Allocated up to remaining invoice total context
    total = float(invoice.get("total") or 0)
    paid = float(invoice.get("paid") or 0)
    # This payment is fully allocated to the invoice
    allocated = amount
    unallocated = 0.0

    method = payment.get("method") or payment.get("account") or "—"
    if method in ("momo", "cash", "bank"):
        method = {"momo": "MOBILE_MONEY", "cash": "CASH", "bank": "BANK_TRANSFER"}.get(method, method)
    method = str(method).upper().replace(" ", "_")

    receipt_date = payment.get("at") or datetime.now().isoformat(timespec="seconds")
    try:
        # pretty date
        if "T" in str(receipt_date):
            receipt_date = datetime.fromisoformat(str(receipt_date).replace("Z", "")).strftime("%b %d, %Y")
    except Exception:
        receipt_date = datetime.now().strftime("%b %d, %Y")

    data = {
        "receipt_no": receipt_no,
        "receipt_date": receipt_date,
        "method": method,
        "reference": payment.get("note") or payment.get("reference") or invoice_no,
        "customer_name": invoice.get("customer_name") or "",
        "customer_email": invoice.get("customer_email") or "",
        "customer_phone": invoice.get("customer_phone") or "",
        "invoice_no": invoice_no,
        "currency": currency,
        "amount_received": amount,
        "amount_allocated": allocated,
        "amount_unallocated": unallocated,
        "notes": payment.get("note") or "",
    }

    safe = receipt_no.replace("/", "-")
    pdf_path = OUTPUT_DIR / f"Receipt_{safe}.pdf"
    generate_receipt(data, str(pdf_path))

    receipts = db.setdefault("receipts", {})
    receipts[receipt_no] = {
        **data,
        "invoice_no": invoice_no,
        "pdf": str(pdf_path.name),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    inv = db.get("invoices", {}).get(invoice_no)
    if inv and inv.get("payments"):
        # Prefer payment matching same timestamp, else last without receipt_no, else last
        tagged = False
        pay_at = payment.get("at")
        for p in inv["payments"]:
            if pay_at and p.get("at") == pay_at and not p.get("receipt_no"):
                p["receipt_no"] = receipt_no
                tagged = True
                break
        if not tagged:
            for p in reversed(inv["payments"]):
                if not p.get("receipt_no"):
                    p["receipt_no"] = receipt_no
                    tagged = True
                    break
        if not tagged:
            inv["payments"][-1]["receipt_no"] = receipt_no
        db["invoices"][invoice_no] = inv
    save_db(db)
    return receipt_no, pdf_path


# JSON store + CLI
# ──────────────────────────────────────────────────────────────
try:
    from paths_config import DATA_DIR as _DATA
except Exception:
    _DATA = Path(__file__).parent / "data"
    _DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = _DATA / "invoices_db.json"
OUTPUT_DIR = _DATA / "invoices"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_db():
    if DB_PATH.exists():
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"next_invoice_seq": 1, "invoices": {}, "customers": {}}


def save_db(db):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def next_invoice_no(db):
    now = datetime.now()
    prefix = f"INV-{now.strftime('%Y%m')}-"
    seq = db.get("next_invoice_seq", 1)
    db["next_invoice_seq"] = seq + 1
    return f"{prefix}{seq:04d}"


def create_invoice(data: dict, created_by: str = "worker") -> str:
    db = load_db()
    inv_no = data.get("invoice_no") or next_invoice_no(db)
    data["invoice_no"] = inv_no

    data.setdefault("invoice_date", datetime.now().strftime("%b %d, %Y"))
    if "due_date" not in data:
        due = datetime.now() + timedelta(days=30)
        data["due_date"] = due.strftime("%b %d, %Y")
    data.setdefault("currency", DEFAULT_CURRENCY)
    data.setdefault("tax", 0.0)
    data.setdefault("paid", 0.0)

    if "subtotal" not in data:
        data["subtotal"] = round(sum(i.get("amount", 0) for i in data.get("items", [])), 2)
    if "total" not in data:
        data["total"] = round(data["subtotal"] + data.get("tax", 0), 2)
    if "balance_due" not in data:
        data["balance_due"] = round(data["total"] - data.get("paid", 0), 2)

    data["created_at"] = datetime.now().isoformat(timespec="seconds")
    data["created_by"] = created_by

    db["invoices"][inv_no] = data

    email = data.get("customer_email", "")
    name = data.get("customer_name", "")
    if email or name:
        key = email or name
        db["customers"][key] = {
            "name": name,
            "email": email,
            "phone": data.get("customer_phone", ""),
        }

    save_db(db)

    safe_name = inv_no.replace("/", "-")
    pdf_path = OUTPUT_DIR / f"Invoice_{safe_name}.pdf"
    generate_invoice(data, str(pdf_path))
    return inv_no


def list_invoices():
    db = load_db()
    invs = db.get("invoices", {})
    if not invs:
        print("No invoices yet.")
        return
    print(f"{'Invoice No':<18} {'Date':<14} {'Customer':<22} {'Total':>12}  Status")
    print("-" * 78)
    for no, inv in sorted(invs.items(), reverse=True):
        total = inv.get("total", 0)
        currency = inv.get("currency", "GHS")
        bal = inv.get("balance_due", total)
        status = "Paid" if bal <= 0 else "Due"
        print(f"{no:<18} {inv.get('invoice_date',''):<14} "
              f"{inv.get('customer_name','')[:20]:<22} "
              f"{currency} {total:>8.2f}  {status}")


def regenerate(invoice_no: str):
    db = load_db()
    inv = db["invoices"].get(invoice_no)
    if not inv:
        print(f"Invoice {invoice_no} not found.")
        return
    safe_name = invoice_no.replace("/", "-")
    pdf_path = OUTPUT_DIR / f"Invoice_{safe_name}.pdf"
    generate_invoice(inv, str(pdf_path))
    print(f"Regenerated → {pdf_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="B.Y.B Port style Shipping Invoice System")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List all invoices")
    p_reg = sub.add_parser("regenerate", help="Regenerate PDF for an invoice")
    p_reg.add_argument("invoice_no")

    sub.add_parser("sample", help="Generate the Benjamin Kinsman BEA222 sample")

    p_create = sub.add_parser("create", help="Create a new invoice (demo)")
    p_create.add_argument("--customer", required=True)
    p_create.add_argument("--email", default="")
    p_create.add_argument("--tracking", action="append", default=[])
    p_create.add_argument("--item", action="append", default=[])
    p_create.add_argument("--weight", type=float, action="append", default=[])
    p_create.add_argument("--amount", type=float, action="append", default=[])
    p_create.add_argument("--transport", default="SEA_FREIGHT")

    args = parser.parse_args()

    if args.cmd == "list":
        list_invoices()

    elif args.cmd == "regenerate":
        regenerate(args.invoice_no)

    elif args.cmd == "sample":
        sample = {
            "invoice_no": "INV-202609-0058",
            "invoice_date": "Sep 08, 2026",
            "due_date": "Oct 08, 2026",
            "customer_name": "Benjamin Kinsman",
            "customer_email": "kinsmanbenjamin@gmail.com",
            "currency": "GHS",
            "subtotal": 308.55,
            "tax": 0.00,
            "total": 308.55,
            "paid": 0.00,
            "balance_due": 308.55,
            "momo": "NANA KWAME KUSI-OHEMENG - 0206027020",
            "bank_lines": [
                "DEGREENS INNOVATION LTD",
                "STANBIC BANK, MADINA MAIN",
                "9040014136600",
            ],
            "contact_phone": "+233 (0)24 600 6186",
            "items": [
                {
                    "tracking": "KK300135928641",
                    "item_name": "A4 paperA4",
                    "transport": "SEA_FREIGHT",
                    "boxes": 1,
                    "weight_kg": 12.9,
                    "vol_cbm": 0.05,
                    "order_number": "",
                    "amount": 154.28,
                },
                {
                    "tracking": "KK300135928242",
                    "item_name": "A4 paperA4",
                    "transport": "SEA_FREIGHT",
                    "boxes": 1,
                    "weight_kg": 13.0,
                    "vol_cbm": 0.05,
                    "order_number": "",
                    "amount": 154.28,
                },
            ],
        }
        no = create_invoice(sample, created_by="demo")
        print(f"Sample invoice created: {no}")
        print(f"PDF → {OUTPUT_DIR / f'Invoice_{no}.pdf'}")

    elif args.cmd == "create":
        items = []
        for i, tr in enumerate(args.tracking):
            items.append({
                "tracking": tr,
                "item_name": args.item[i] if i < len(args.item) else "Goods",
                "transport": args.transport,
                "boxes": 1,
                "weight_kg": args.weight[i] if i < len(args.weight) else 1.0,
                "vol_cbm": 0.05,
                "order_number": "",
                "amount": args.amount[i] if i < len(args.amount) else 100.0,
            })
        if not items:
            items = [{
                "tracking": "TBD",
                "item_name": "Goods",
                "transport": args.transport,
                "boxes": 1,
                "weight_kg": 1.0,
                "vol_cbm": 0.05,
                "order_number": "",
                "amount": 100.0,
            }]
        data = {
            "customer_name": args.customer,
            "customer_email": args.email,
            "items": items,
        }
        no = create_invoice(data)
        print(f"Created invoice {no}")
        safe = no.replace("/", "-")
        print(f"PDF → {OUTPUT_DIR / f'Invoice_{safe}.pdf'}")

    else:
        parser.print_help()
        print("\nQuick start:")
        print("  python invoice_generator.py sample")
        print("  python invoice_generator.py list")
        print("  python invoice_generator.py create --customer 'John Doe' \\")
        print("         --email john@example.com --tracking KK123 --weight 10 \\")
        print("         --amount 150 --item 'A4 Paper'")
