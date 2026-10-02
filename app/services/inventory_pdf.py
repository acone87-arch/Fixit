"""A4 sheets, eight 90 x 60 mm labels with permanent /e/ URLs."""
from io import BytesIO

from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.services.equipment_label_pdf import EquipmentLabel, draw_equipment_label
from app.services.service_act_pdf import _font_name


def build_inventory_pdf(site_name, batch_id, labels, base_url):
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=A4)
    canvas.setTitle('Fixit - QR инвентаризация')
    font = _font_name()
    # 2 columns x 4 rows; large QR remains readable after printing at 100%.
    for index, (number, token) in enumerate(labels):
        if index % 8 == 0:
            if index:
                canvas.showPage()
            canvas.setFont(font, 10)
            canvas.drawString(15*mm, 282*mm, 'FIXIT / Инвентаризация оборудования')
            canvas.setFont(font, 8)
            canvas.drawString(15*mm, 276*mm, f'Партия {batch_id[:8]}  |  Печать A4, масштаб 100%')
            canvas.drawRightString(195*mm, 12*mm, f'{index // 8 + 1} / {(len(labels) + 7) // 8}')
        column, row = index % 2, (index % 8) // 2
        x, y = (15 + column*90)*mm, (208 - row*63)*mm
        draw_equipment_label(canvas, x=x, y=y, label=EquipmentLabel(
            token=token, site_name=str(site_name), inventory_number=number, batch_id=batch_id,
        ), base_url=base_url)
    canvas.save()
    return stream.getvalue()
