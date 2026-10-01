"""One print template for both single and batch equipment QR labels."""
from dataclasses import dataclass
from io import BytesIO

import qrcode
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app.services.service_act_pdf import _font_name

LABEL_WIDTH = 90 * mm
LABEL_HEIGHT = 60 * mm


@dataclass(frozen=True)
class EquipmentLabel:
    token: str
    site_name: str
    equipment_name: str | None = None
    inventory_number: int | None = None
    batch_id: str | None = None


def public_equipment_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/e/{token}"


def _fit(value: str, font: str, size: float, width: float) -> str:
    text = str(value or "").strip()
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return (text.rstrip() + "…") if text else "…"


def draw_equipment_label(canvas: Canvas, *, x: float, y: float, label: EquipmentLabel, base_url: str, cut_line: bool = True) -> None:
    font = _font_name()
    url = public_equipment_url(base_url, label.token)
    if cut_line:
        canvas.setStrokeColorRGB(.7, .7, .7)
        canvas.setDash(2, 3)
        canvas.rect(x, y, LABEL_WIDTH, LABEL_HEIGHT)
        canvas.setDash()
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=10)
    qr.add_data(url)
    qr.make(fit=True)
    canvas.drawImage(ImageReader(qr.make_image().convert("RGB")), x + 3*mm, y + 11*mm, 40*mm, 40*mm)
    canvas.setFont(font, 11)
    canvas.drawString(x + 46*mm, y + 43*mm, "FIXIT")
    canvas.setFont(font, 10)
    number = f"№ {label.inventory_number:03d}" if label.inventory_number is not None else "Оборудование"
    canvas.drawString(x + 46*mm, y + 35*mm, number)
    canvas.setFont(font, 7)
    if label.batch_id:
        canvas.drawString(x + 46*mm, y + 28*mm, f"Партия {label.batch_id[:8]}")
    elif label.equipment_name:
        canvas.drawString(x + 46*mm, y + 28*mm, _fit(label.equipment_name, font, 7, 40*mm))
    footer = label.site_name
    if label.equipment_name and label.inventory_number is not None:
        footer = f"{label.equipment_name} · {label.site_name}"
    canvas.setFont(font, 8)
    canvas.drawString(x + 4*mm, y + 5*mm, _fit(footer, font, 8, 81*mm))
    canvas.linkURL(url, (x + 3*mm, y + 11*mm, x + 43*mm, y + 51*mm), relative=0)


def build_single_label_pdf(label: EquipmentLabel, base_url: str) -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
    canvas.setTitle("Fixit - QR оборудования")
    draw_equipment_label(canvas, x=0, y=0, label=label, base_url=base_url, cut_line=False)
    canvas.save()
    return stream.getvalue()
