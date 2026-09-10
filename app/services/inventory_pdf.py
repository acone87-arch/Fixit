"""A4 sheets, eight 90 x 60 mm labels with permanent /e/ URLs."""
from io import BytesIO

import qrcode
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

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
        canvas.setStrokeColorRGB(.7, .7, .7)
        canvas.setDash(2, 3)
        canvas.rect(x, y, 90*mm, 60*mm)
        canvas.setDash()
        url = f'{base_url}/e/{token}'
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=10)
        qr.add_data(url); qr.make(fit=True)
        image = qr.make_image().convert('RGB')
        canvas.drawImage(ImageReader(image), x+3*mm, y+11*mm, 40*mm, 40*mm)
        canvas.setFont(font, 11)
        canvas.drawString(x+46*mm, y+43*mm, 'FIXIT')
        canvas.setFont(font, 10)
        canvas.drawString(x+46*mm, y+35*mm, f'№ {number:03d}')
        canvas.setFont(font, 7)
        canvas.drawString(x+46*mm, y+28*mm, f'Партия {batch_id[:8]}')
        title = str(site_name)
        while stringWidth(title, font, 8) > 81*mm:
            title = title[:-2] + '…'
        canvas.setFont(font, 8)
        canvas.drawString(x+4*mm, y+5*mm, title)
        canvas.linkURL(url, (x+3*mm, y+11*mm, x+43*mm, y+51*mm), relative=0)
    canvas.save()
    return stream.getvalue()
