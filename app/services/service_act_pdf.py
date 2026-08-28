"""PDF generation for an immutable view of a completed service act."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image as PillowImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as PdfImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _font_name() -> str:
    """Register a Cyrillic font both in the Docker image and on Windows dev hosts."""
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont("FixitSans", str(path)))
                return "FixitSans"
            except Exception:  # pragma: no cover - only a local font fallback
                continue
    return "Helvetica"


def _safe(value: object | None) -> str:
    return str(value or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _signature_flowable(data: bytes | None):
    """Skip a corrupted upload instead of making the whole PDF unavailable."""
    if not data:
        return None
    try:
        image = PillowImage.open(BytesIO(data))
        image.verify()
        return PdfImage(BytesIO(data), width=50 * mm, height=16 * mm, kind="proportional")
    except Exception:  # an attachment is supplementary, the act itself is not
        return None


def build_service_act(
    stream,
    *,
    organization_name: str,
    repair_id: str,
    client_name: str,
    site_name: str,
    site_address: str | None,
    equipment_name: str,
    manufacturer: str | None,
    model: str | None,
    serial_number: str,
    technician_name: str,
    fault_type: str | None,
    description: str,
    labor_minutes: int,
    closed_at: object | None,
    client_signer_name: str | None,
    client_signed_at: object | None,
    signature_image: bytes | None,
    parts: list[tuple[str, str, int]],
) -> None:
    """Build a one- or two-page Russian service act into a binary stream."""
    font = _font_name()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("FixitNormal", parent=styles["BodyText"], fontName=font, fontSize=9.2, leading=13)
    muted = ParagraphStyle("FixitMuted", parent=normal, textColor=colors.HexColor("#64748B"), fontSize=8)
    heading = ParagraphStyle("FixitHeading", parent=styles["Heading1"], fontName=font, fontSize=18, leading=22, textColor=colors.HexColor("#0F172A"))
    subheading = ParagraphStyle("FixitSubheading", parent=styles["Heading2"], fontName=font, fontSize=10.5, leading=14, textColor=colors.HexColor("#0F766E"), spaceBefore=9, spaceAfter=4)
    right = ParagraphStyle("FixitRight", parent=muted, alignment=TA_RIGHT)

    doc = SimpleDocTemplate(
        stream, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Service act {repair_id}", author=organization_name,
    )
    story = [
        Table([[Paragraph("FIXIT <font color='#14B8A6'>PULSE</font>", heading), Paragraph(_safe(organization_name), right)]], colWidths=[105 * mm, 73 * mm]),
        Spacer(1, 7 * mm),
        Paragraph("Сервисный акт", heading),
        Paragraph(f"№ {repair_id[:8].upper()} · закрыт: {_safe(closed_at)}", muted),
        Spacer(1, 5 * mm),
    ]

    details = [
        [Paragraph("Клиент", muted), Paragraph(_safe(client_name), normal)],
        [Paragraph("Объект", muted), Paragraph(_safe(site_name), normal)],
        [Paragraph("Адрес", muted), Paragraph(_safe(site_address), normal)],
        [Paragraph("Оборудование", muted), Paragraph(_safe(equipment_name), normal)],
        [Paragraph("Модель / серийный №", muted), Paragraph(f"{_safe(manufacturer)} {_safe(model)} · {_safe(serial_number)}", normal)],
        [Paragraph("Исполнитель", muted), Paragraph(_safe(technician_name), normal)],
    ]
    detail_table = Table(details, colWidths=[48 * mm, 130 * mm], hAlign="LEFT")
    detail_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#DDE5E7")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [detail_table, Paragraph("Выполненные работы", subheading), Paragraph(_safe(description), normal)]
    story += [Paragraph("Неисправность", subheading), Paragraph(_safe(fault_type), normal)]
    story += [Paragraph("Трудозатраты", subheading), Paragraph(f"{max(0, labor_minutes)} мин.", normal)]
    story.append(Paragraph("Использованные запчасти", subheading))
    if parts:
        rows = [[Paragraph("Наименование", muted), Paragraph("Артикул", muted), Paragraph("Кол-во", muted)]]
        rows.extend([[Paragraph(_safe(name), normal), Paragraph(_safe(article), normal), Paragraph(str(quantity), normal)] for name, article, quantity in parts])
        table = Table(rows, colWidths=[95 * mm, 55 * mm, 28 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F7F5")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9D9D8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("Запчасти не использовались.", muted))

    story += [Paragraph("Подтверждение клиента", subheading)]
    if client_signer_name:
        story.append(Paragraph(f"Работы принял(а): {_safe(client_signer_name)} · {_safe(client_signed_at)}", normal))
        signature = _signature_flowable(signature_image)
        if signature:
            story += [Spacer(1, 3 * mm), signature]
    else:
        story.append(Paragraph("Подтверждение клиента не получено.", muted))
    story += [Spacer(1, 10 * mm), Paragraph("Сформировано в Fixit Pulse. Документ отражает сведения, внесённые при закрытии ремонта.", muted)]
    doc.build(story)
